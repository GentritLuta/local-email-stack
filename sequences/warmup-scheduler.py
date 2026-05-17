"""warmup-scheduler.py — autonomous warmup ramp with snowball curve.

Runs once per day (or on demand). For each profile with warmup.enabled:
  1. If reputation thresholds exceeded → pause (don't advance current_day).
  2. Compute today's daily quota from the ramp curve at current_day.
  3. Split today's quota: warmup_pct → warmup_targets,  rest → real-prospect queue.
  4. Send each batch via Resend with realistic jitter (9–18h sender-local window).
  5. Record what was sent in warmup-state/<profile>.log.jsonl
  6. Advance current_day by 1.

Best-practice ramp curve hard-coded as snowball_v1 in each profile:
    day 1-3:   10/day
    day 4-7:   20/day
    day 8-14:  40/day
    day 15-21: 80/day
    day 22-30: 150/day
    day 31-45: 250/day
    day 46+:   max_daily_sends (full scale)

Mix curve (warmup-target % vs real-prospect %):
    day  1-14:  80% warmup / 20% real
    day 15-30:  30% warmup / 70% real
    day 31-45:  10% warmup / 90% real
    day 46+:     5% warmup / 95% real (maintenance)

Usage:
    py warmup-scheduler.py tick                          # all profiles, advance day if eligible
    py warmup-scheduler.py tick --profile bernhard       # one profile
    py warmup-scheduler.py status                        # print ramp state per profile
    py warmup-scheduler.py start <slug>                  # set current_day=1, started_at=today
    py warmup-scheduler.py pause <slug>                  # disable warmup
    py warmup-scheduler.py resume <slug>                 # re-enable
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import sys
import time
from pathlib import Path

import httpx

from profile_lib import (
    REPO_ROOT,
    current_warmup_day,
    daily_target_for,
    list_profiles,
    load_profile,
    reputation_exceeded,
    save_profile,
    today_iso,
    warmup_pct_for,
)

WARMUP_DIR = REPO_ROOT / "warmup-state"
WARMUP_DIR.mkdir(exist_ok=True)
RESEND_API = "https://api.resend.com"

# Topic pool — generic, conversational, link-free, varied
WARMUP_TOPICS = [
    ("quick thought on the week", "Hey,\n\nQuick one — saw the {sector} numbers earlier and figured you'd want to compare notes. Anything notable on your end?\n\n"),
    ("re: that thing we discussed", "Hey,\n\nThinking about what we touched on last week. I think you're right that the lower-hanging fruit is the bookings flow, not the top-of-funnel. Worth sketching out?\n\n"),
    ("Q3 numbers", "Hey,\n\nDid you see the Q3 report? The shift in customer cohorts is wilder than I expected. Worth a 15-min chat sometime this week.\n\n"),
    ("morning",  "Morning,\n\nNo agenda — just wanted to check in. How's the launch going?\n\n"),
    ("one question", "Hey,\n\nOne question: did you end up going with the in-house route or with the vendor? Curious how it played out.\n\n"),
    ("podcast rec", "Hey,\n\nQuick rec — the Cohost episode from last Friday is worth 30 minutes if you haven't already. The framing on retention is sharp.\n\n"),
    ("dinner thursday?", "Hey,\n\nThinking dinner Thursday if you're around. Same place as last time?\n\n"),
    ("thanks for the intro", "Hey,\n\nMeant to say — thanks for the intro to Maya last week. We had a good first call. Will keep you posted.\n\n"),
    ("draft", "Hey,\n\nFinally finished the first draft of the doc. Sending over a link tomorrow once I've slept on it.\n\n"),
    ("review note", "Hey,\n\nOne note on the review doc: section 4 reads a bit dry. Maybe move the founding-customer anecdote up?\n\n"),
]


def _log_path(profile: dict) -> Path:
    return WARMUP_DIR / f"{profile['slug']}.log.jsonl"


def _publish_status(profile: dict, status: dict) -> None:
    """Write current ramp + send status to the desktop app's public dir."""
    pub = REPO_ROOT / "desktop" / "frontend" / "public" / "profiles" / f"{profile['slug']}.warmup.json"
    pub.parent.mkdir(parents=True, exist_ok=True)
    pub.write_text(json.dumps(status, indent=2), encoding="utf-8")


def _send_warmup_email(profile: dict, to_addr: str, topic: tuple) -> dict:
    """Render + Resend send. Each warmup email is unique enough to avoid content classifiers."""
    api_key = profile.get("relay", {}).get("resend_api_key", "").strip()
    if not api_key:
        return {"sent": False, "error": "no Resend API key on profile"}
    ident = profile["identity"]
    subject_root, body_root = topic
    # Small randomized variation so two warmup mails from the same profile aren't identical
    nonce = random.randint(1000, 9999)
    subject = subject_root if random.random() < 0.5 else subject_root.lower()
    body = body_root.format(sector=random.choice(["SaaS", "fintech", "infra", "media", "DTC"]))
    body = body + ident["signature"] + f"\n\n.ref={nonce}"
    payload = {
        "from":    f'{ident["from_name"]} <{ident["from_addr"]}>',
        "to":      [to_addr],
        "reply_to": ident["reply_to"],
        "subject": subject,
        "text":    body,
        "tags": [
            {"name": "profile", "value": profile["slug"]},
            {"name": "kind",    "value": "warmup"},
        ],
    }
    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(f"{RESEND_API}/emails",
                       headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                       json=payload)
        if r.status_code in (200, 202):
            return {"sent": True, "remote_id": r.json().get("id"), "to": to_addr}
        return {"sent": False, "error": f"{r.status_code}: {r.text[:200]}", "to": to_addr}
    except Exception as e:
        return {"sent": False, "error": str(e), "to": to_addr}


def _within_send_window() -> bool:
    """Best-practice: send during business hours (9am–6pm), random within."""
    now = dt.datetime.now()
    return 9 <= now.hour < 18


def _tick_profile(profile: dict, force_window: bool = False) -> dict:
    slug = profile["slug"]
    print(f"\n=== {profile['name']} ({slug})")
    w = profile.setdefault("warmup", {})
    if not w.get("enabled", False):
        print("  warmup disabled — skipping")
        return {"slug": slug, "skipped": "disabled"}

    blocked, why = reputation_exceeded(profile)
    if blocked:
        print(f"  PAUSED: reputation threshold exceeded ({why})")
        status = {"slug": slug, "paused": True, "reason": why,
                  "current_day": current_warmup_day(profile)}
        _publish_status(profile, status)
        return status

    day = current_warmup_day(profile)
    started = w.get("started_at")
    if not started:
        # Auto-start at day 1
        w["started_at"] = today_iso()
        w["current_day"] = 1
        day = 1
        save_profile(profile)
        print(f"  starting warmup → day 1")

    daily = daily_target_for(profile, day)
    pct   = warmup_pct_for(profile, day)
    n_warm = max(1, int(round(daily * pct)))
    n_real = daily - n_warm

    targets = w.get("warmup_targets") or []
    if not targets:
        print(f"  no warmup_targets configured — fill profile.warmup.warmup_targets first")
        status = {"slug": slug, "skipped": "no_targets",
                  "current_day": day, "daily": daily, "warmup_planned": n_warm, "real_planned": n_real}
        _publish_status(profile, status)
        return status

    if not _within_send_window() and not force_window:
        print(f"  outside 09:00–18:00 send window — deferring (re-run later)")
        status = {"slug": slug, "deferred": True, "current_day": day,
                  "daily": daily, "warmup_planned": n_warm, "real_planned": n_real}
        _publish_status(profile, status)
        return status

    sent = 0
    fails = 0
    log = _log_path(profile)
    print(f"  day {day}: daily={daily}, warmup={n_warm}, real={n_real} (real sends pulled separately from sequences)")
    for i in range(n_warm):
        to = random.choice(targets)
        topic = random.choice(WARMUP_TOPICS)
        outcome = _send_warmup_email(profile, to, topic)
        row = {"ts": dt.datetime.now().isoformat(), "kind": "warmup", "day": day, **outcome}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        if outcome.get("sent"): sent += 1
        else:                   fails += 1
        # Spread sends randomly across the next ~30 minutes (don't burst)
        time.sleep(random.uniform(8.0, 22.0))

    # Advance the ramp day if we sent at least 60% of plan
    if n_warm == 0 or sent / max(n_warm, 1) >= 0.6:
        w["current_day"] = day + 1
        save_profile(profile)
        print(f"  advanced to day {day + 1}")
    else:
        print(f"  send success {sent}/{n_warm} below threshold — not advancing")

    status = {
        "slug": slug, "current_day": w["current_day"],
        "daily": daily, "warmup_planned": n_warm, "warmup_sent": sent, "warmup_failed": fails,
        "real_planned": n_real, "last_tick": dt.datetime.now().isoformat(),
    }
    _publish_status(profile, status)
    return status


def _print_status_for(profile: dict) -> None:
    w = profile.get("warmup", {})
    rep = w.get("reputation", {})
    day = current_warmup_day(profile)
    daily = daily_target_for(profile, day)
    pct = warmup_pct_for(profile, day)
    blocked, why = reputation_exceeded(profile)
    print(f"\n{profile['name']} ({profile['slug']})")
    print(f"  enabled:       {w.get('enabled')}")
    print(f"  started_at:    {w.get('started_at') or '(not started)'}")
    print(f"  current_day:   {day}")
    print(f"  daily target:  {daily}")
    print(f"  warmup share:  {pct*100:.0f}%   (real share: {100-pct*100:.0f}%)")
    print(f"  reputation:    bounce_7d={rep.get('bounce_rate_7d',0):.3f}  "
          f"complaint_7d={rep.get('complaint_rate_7d',0):.4f}  "
          f"delivered_7d={rep.get('delivered_7d',0)}")
    if blocked:
        print(f"  ⚠ PAUSED:    {why}")
    targets = w.get('warmup_targets') or []
    print(f"  targets:       {len(targets)} address(es)")
    if not targets:
        print(f"  → add 3–5 friendly inboxes in profile.warmup.warmup_targets")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    tick = sub.add_parser("tick"); tick.add_argument("--profile"); tick.add_argument("--force-window", action="store_true")
    st = sub.add_parser("status"); st.add_argument("--profile")
    for c in ("start", "pause", "resume"):
        p = sub.add_parser(c); p.add_argument("slug")
    args = ap.parse_args()

    if args.cmd == "status":
        profiles = [load_profile(args.profile)] if args.profile else list_profiles()
        for p in profiles:
            _print_status_for(p)
        return 0

    if args.cmd in ("start", "pause", "resume"):
        p = load_profile(args.slug)
        w = p.setdefault("warmup", {})
        if args.cmd == "start":
            w["enabled"] = True
            w["started_at"] = today_iso()
            w["current_day"] = 1
            print(f"started warmup for {args.slug} at {today_iso()}, day 1")
        elif args.cmd == "pause":
            w["enabled"] = False
            print(f"paused {args.slug}")
        elif args.cmd == "resume":
            w["enabled"] = True
            print(f"resumed {args.slug}")
        save_profile(p)
        return 0

    if args.cmd == "tick":
        profiles = [load_profile(args.profile)] if args.profile else list_profiles()
        for p in profiles:
            _tick_profile(p, force_window=args.force_window)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
