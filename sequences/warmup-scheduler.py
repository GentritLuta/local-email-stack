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
    iter_send_domains,
    daily_target_for_domain,
    current_warmup_day_for_domain,
    reputation_exceeded_for_domain,
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
    """Per-profile tick that loops over every sending subdomain in the pool
    and advances each one's warmup day independently. Paused domains stay on
    their day, sending domains tick forward, and a domain over the bounce/
    complaint threshold pauses without affecting siblings."""
    slug = profile["slug"]
    print(f"\n=== {profile['name']} ({slug})")
    domains = iter_send_domains(profile, only_verified=True, only_enabled=False)
    if not domains:
        print("  no verified sending domains in relay.from_domains — skipping")
        return {"slug": slug, "skipped": "no_domains"}

    targets = (profile.get("warmup") or {}).get("warmup_targets") or []
    if not targets:
        print(f"  no warmup_targets configured — fill profile.warmup.warmup_targets first")
        return {"slug": slug, "skipped": "no_targets"}

    if not _within_send_window() and not force_window:
        print(f"  outside 09:00–18:00 send window — deferring (re-run later)")
        return {"slug": slug, "deferred": True}

    per_domain_status = []
    for d in domains:
        ds = _tick_domain(profile, d, targets)
        per_domain_status.append(ds)
    save_profile(profile)
    status = {
        "slug": slug,
        "domains": per_domain_status,
        "last_tick": dt.datetime.now().isoformat(),
    }
    _publish_status(profile, status)
    return status


def _tick_domain(profile: dict, d: dict, targets: list[str]) -> dict:
    """Advance one subdomain's warmup ramp by one day. Sends today's planned
    warmup-target batch over a randomized 20-min window. Pauses if the
    domain's reputation snapshot exceeds the profile's auto_pause thresholds."""
    domain = d["domain"]
    w = d.setdefault("warmup", {})
    if not w.get("enabled", True):
        print(f"  · {domain}: warmup disabled — skipping")
        return {"domain": domain, "skipped": "disabled"}

    blocked, why = reputation_exceeded_for_domain(profile, d)
    if blocked:
        print(f"  · {domain}: PAUSED — {why}")
        return {"domain": domain, "paused": True, "reason": why,
                "current_day": current_warmup_day_for_domain(d)}

    day = current_warmup_day_for_domain(d)
    if not w.get("started_at"):
        w["started_at"] = today_iso()
        w["current_day"] = 1
        day = 1
        print(f"  · {domain}: starting warmup → day 1")

    daily = daily_target_for_domain(profile, d)
    pct   = warmup_pct_for(profile, day)
    n_warm = max(1, int(round(daily * pct)))

    print(f"  · {domain}: day {day} — daily {daily}, warmup {n_warm}")

    sent  = 0
    fails = 0
    log   = _log_path(profile)
    for _ in range(n_warm):
        to = random.choice(targets)
        topic = random.choice(WARMUP_TOPICS)
        outcome = _send_warmup_email_from_domain(profile, d, to, topic)
        row = {"ts": dt.datetime.now().isoformat(), "kind": "warmup",
               "domain": domain, "day": day, **outcome}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        if outcome.get("sent"): sent += 1
        else:                   fails += 1
        time.sleep(random.uniform(8.0, 22.0))

    if n_warm == 0 or sent / max(n_warm, 1) >= 0.6:
        w["current_day"] = day + 1
        print(f"  · {domain}: advanced to day {day + 1}")
    else:
        print(f"  · {domain}: send success {sent}/{n_warm} below threshold — not advancing")

    return {"domain": domain, "current_day": w["current_day"],
            "daily": daily, "warmup_planned": n_warm,
            "warmup_sent": sent, "warmup_failed": fails}


def _send_warmup_email_from_domain(profile: dict, domain_entry: dict, to_addr: str, topic: tuple) -> dict:
    """Like _send_warmup_email but sends from a specific subdomain in the pool.
    Uses the first persona's name as the human display name; addr is
    <persona-slug>@<domain> so the warmup also exercises the same alias
    space the real sequences use."""
    api_key = profile.get("relay", {}).get("resend_api_key", "").strip()
    if not api_key:
        return {"sent": False, "error": "no Resend API key on profile"}
    personas = profile.get("personas") or []
    if not personas:
        return {"sent": False, "error": "no personas on profile"}
    # Rotate through personas so warmup also exercises each From-address.
    p = personas[random.randrange(len(personas))]
    from_name = p.get("from_name") or p.get("slug", "Team")
    from_addr = f'{p["slug"]}@{domain_entry["domain"]}'
    reply_to  = p.get("reply_to") or f'info@{domain_entry["domain"].split(".", 1)[-1]}'
    sig = p.get("signature") or from_name
    subject_root, body_root = topic
    nonce = random.randint(1000, 9999)
    subject = subject_root if random.random() < 0.5 else subject_root.lower()
    body = body_root.format(sector=random.choice(["SaaS", "fintech", "infra", "media", "DTC"]))
    body = body + sig + f"\n\n.ref={nonce}"
    payload = {
        "from":     f'{from_name} <{from_addr}>',
        "to":       [to_addr],
        "reply_to": reply_to,
        "subject":  subject,
        "text":     body,
        "tags": [
            {"name": "profile", "value": profile["slug"]},
            {"name": "domain",  "value": domain_entry["domain"]},
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
