"""resend-status-reconcile.py - poll Resend for ground-truth delivery
status and update Supabase send_log + suppress bounced prospects.

The proper way to do this is a Resend webhook (resend-webhook.py exists
but needs Cloudflare Tunnel + manual config in Resend dashboard). This
script is the polling alternative: simple, scheduled, no inbound port
required. Runs hourly, walks recent send_log rows that don't yet have a
definitive terminal status, fetches each from Resend /emails/{id}, and
patches the row + the prospect record + any in-flight run.

What it does, per send_log row in scope:
  1. GET https://api.resend.com/emails/{resend_id}
  2. Read .last_event:  delivered / bounced / complained / opened / clicked / sent
  3. PATCH send_log with the boolean flags that match. Pre-existing True
     flags are NOT cleared (e.g. webhook firing first wins).
  4. If `bounced`: mark the prospect verified=false + unsubscribed=true so
     no future steps go to a bad address; also pause the prospect's run.
  5. If `complained`: same treatment - hard suppress.

Scope of rows to reconcile per run:
  - status not already 'bounced' or 'complained' (those are terminal)
  - sent_at within the last 36 hours (older sends rarely change state)
  - resend_id is set (skip the legacy '(unknown)' historical rows)

Run:
    py sequences/resend-status-reconcile.py             # default scope
    py sequences/resend-status-reconcile.py --hours 72  # wider scope
    py sequences/resend-status-reconcile.py --dry       # plan only

Scheduled as LES-resend-status-reconcile hourly.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV  = REPO / "sequences" / "supabase.env"
HOST_ENV = REPO / "sequences" / "hostinger.env"

env = {}
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
host = {}
for line in HOST_ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        host[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
RESEND_KEY = host["RESEND_FULL_ACCESS_API_KEY"]
H_R = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
H_W = {**H_R, "Content-Type": "application/json", "Prefer": "return=minimal"}

# Resend's CDN blocks default Python urllib UA with error code 1010.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
RESEND_HEADERS = {
    "Authorization": f"Bearer {RESEND_KEY}",
    "User-Agent":    UA,
    "Accept":        "application/json",
}

# Resend events we mirror into send_log columns.
EVENT_TO_FLAG = {
    "delivered":  ("delivered",  True),
    "bounced":    ("bounced",    True),
    "complained": ("complained", True),
    "opened":     ("opened_at",  "<timestamp>"),
    "clicked":    ("clicked_at", "<timestamp>"),
    # 'sent' is the no-op event (Resend accepted but no MX response yet)
}


def supa_get(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H_R)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def supa_patch(path: str, body: dict) -> None:
    req = urllib.request.Request(
        f"{URL}/rest/v1/{path}", method="PATCH",
        data=json.dumps(body).encode(), headers=H_W,
    )
    urllib.request.urlopen(req, timeout=30)


def resend_get_email(resend_id: str, *, max_retries: int = 3) -> dict | None:
    """Fetch one email by id, with retry-with-backoff on 429 (rate limit).
    Resend caps at 5 req/sec; we self-throttle to 4 req/sec at the call
    site, but transient bursts can still slip through. 3 retries with
    exponential backoff (1s, 2s, 4s) clears them."""
    for attempt in range(1, max_retries + 1):
        try:
            req = urllib.request.Request(
                f"https://api.resend.com/emails/{resend_id}",
                headers=RESEND_HEADERS,
            )
            return json.loads(urllib.request.urlopen(req, timeout=20).read())
        except urllib.error.HTTPError as e:
            if e.code in (404, 410):
                return None
            if e.code == 429 and attempt < max_retries:
                time.sleep(2 ** attempt)
                continue
            # final attempt or non-retriable error
            print(f"    ! resend {e.code} on {resend_id[:12]}: {e.read().decode()[:120]}")
            return None
        except Exception as e:
            print(f"    ! resend exception on {resend_id[:12]}: {str(e)[:80]}")
            return None
    return None


def suppress_repeat_bounce_domains(*, lookback_days: int = 30,
                                   min_bounces: int = 2, min_sent: int = 3,
                                   min_rate: float = 0.50, dry: bool = False) -> int:
    """Auto-suppress a domain ONLY when it bounces at a high RATE — not on a raw
    count. A domain that bounces 2 addresses but delivers the other 6 fine is a
    good domain with a few dead mailboxes (those get caught per-recipient); the
    rest are valid leads worth keeping. Wholesale-suppressing it throws away
    output. So a domain is pulled only when ALL hold:
        bounces >= min_bounces  AND  sent >= min_sent  AND  rate >= min_rate
    e.g. 2/3 (67%) or 3/5 (60%) → toxic, pull it; 2/8 (25%) or 3/9 (33%) → keep.
    Idempotent: only touches verified=true rows."""
    since = (dt.datetime.now(dt.timezone.utc)
             - dt.timedelta(days=lookback_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = supa_get(
        f"send_log?sent_at=gte.{urllib.parse.quote(since)}"
        f"&select=to_addr,bounced&limit=5000"
    )
    sent: Counter = Counter()
    bnc: Counter = Counter()
    for r in rows:
        addr = (r.get("to_addr") or "")
        if "@" not in addr:
            continue
        d = addr.split("@")[-1].lower()
        sent[d] += 1
        if r.get("bounced"):
            bnc[d] += 1
    bad = [d for d in bnc
           if bnc[d] >= min_bounces and sent[d] >= min_sent
           and bnc[d] / sent[d] >= min_rate]
    suppressed = 0
    for d in bad:
        ps = supa_get(
            f"prospects?verified=eq.true&email=ilike.*@{urllib.parse.quote(d)}&select=id"
        )
        for p in ps:
            if not dry:
                supa_patch(f"prospects?id=eq.{p['id']}",
                           {"verified": False,
                            "verification_error": "domain_high_bounce_rate"})
            suppressed += 1
    if bad:
        print()
        print(f"DOMAIN AUTO-SUPPRESS (rate >= {min_rate:.0%}, >= {min_bounces} "
              f"bounces, >= {min_sent} sent / {lookback_days}d): "
              f"{len(bad)} domain(s), {suppressed} prospect(s)"
              + ("  [dry]" if dry else ""))
        for d in bad:
            print(f"  - {d} ({bnc[d]}/{sent[d]} = {100*bnc[d]/sent[d]:.0f}%)")
    return suppressed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=int, default=36)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    since = (dt.datetime.now(dt.timezone.utc)
             - dt.timedelta(hours=args.hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"reconciling send_log rows since {since}")

    # In scope: rows with a resend_id, sent within window, not already
    # terminal-suppressed (bounced=true or complained=true).
    rows = supa_get(
        f"send_log?resend_id=not.is.null&sent_at=gte.{urllib.parse.quote(since)}"
        f"&bounced=eq.false&complained=eq.false"
        f"&select=id,resend_id,to_addr,from_addr,run_id,delivered,opened_at,clicked_at&limit=2000"
    )
    print(f"  in-scope rows: {len(rows)}")

    summary = Counter()
    bounces: list[tuple[str, str]] = []  # (to_addr, resend_id) for reporting

    for r in rows:
        d = resend_get_email(r["resend_id"])
        if not d:
            summary["lookup_failed"] += 1
            continue
        event = d.get("last_event") or "sent"
        summary[event] += 1

        patch: dict = {}
        # Resend returns only the most recent event in last_event, but the
        # event lifecycle is monotonic (sent -> delivered -> opened -> clicked,
        # with bounced/complained as alternate terminals). So when we see a
        # later event, we can safely assert all earlier engagement flags too.
        ts = d.get("created_at") or dt.datetime.now(dt.timezone.utc).isoformat()
        if event == "bounced":
            patch["bounced"] = True
            patch["delivered"] = False
            patch["error"] = d.get("bounce", {}).get("message") or "bounced"
            bounces.append((r["to_addr"], r["resend_id"]))
        elif event == "complained":
            patch["complained"] = True
            # Complaint implies delivery happened first; don't clear delivered.
        else:
            # delivered / opened / clicked / sent — cascade engagement
            # flags so analytics open-rate + click-rate compute correctly.
            if event in ("delivered", "opened", "clicked") and not r.get("delivered"):
                patch["delivered"] = True
            if event in ("opened", "clicked") and not r.get("opened_at"):
                patch["opened_at"] = ts
            if event == "clicked" and not r.get("clicked_at"):
                patch["clicked_at"] = ts

        if patch and not args.dry:
            supa_patch(f"send_log?id=eq.{r['id']}", patch)

        # If bounce/complaint, also suppress the prospect and pause their
        # run so no further steps land on a known-bad address.
        if event in ("bounced", "complained") and not args.dry:
            # Find prospect by email
            ps = supa_get(
                f"prospects?email=eq.{urllib.parse.quote(r['to_addr'])}&select=id"
            )
            if ps:
                supa_patch(
                    f"prospects?id=eq.{ps[0]['id']}",
                    {"verified": False, "unsubscribed": True,
                     "verification_method": f"resend_{event}"},
                )
            # Pause the in-flight run if there is one
            if r.get("run_id"):
                supa_patch(
                    f"runs?id=eq.{r['run_id']}",
                    {"status": "paused_bounced" if event == "bounced"
                                                else "paused_complained"},
                )

        # Resend caps at 5 req/sec. 0.25s sleep = 4 req/sec, safely under.
        time.sleep(0.25)

    print()
    print("=== summary ===")
    for ev, n in summary.most_common():
        print(f"  {ev:18s} {n}")
    if bounces:
        print()
        print(f"NEW BOUNCES ({len(bounces)}):")
        for to, rid in bounces:
            print(f"  - {to:42s} {rid[:12]}..")

    # Domain-level hygiene: pull every prospect on any domain that has
    # hard-bounced repeatedly. Runs every reconcile pass (hourly), idempotent.
    suppress_repeat_bounce_domains(dry=args.dry)

    # Refresh each profile's warmup reputation snapshot from live send_log so the
    # warmup auto-pause (bounce_rate threshold) actually trips. Previously this was
    # only updated by the Resend webhook; if that was not firing, bounce_rate_7d
    # stayed 0.0 and a high-bounce sender (e.g. algoalpha 5.9%) never auto-paused.
    refresh_reputation_snapshots(dry=args.dry)
    return 0


def refresh_reputation_snapshots(dry: bool = False) -> None:
    """Per profile, compute 7d delivered/bounced/complained from send_log (keyed
    by the profile's own sending-domain roots) and write bounce_rate_7d /
    complaint_rate_7d into profiles/<slug>.json warmup.reputation. This is the
    data the warmup auto-pause reads."""
    from pathlib import Path as _P
    import glob as _glob
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = supa_get(
        f"send_log?sent_at=gte.{urllib.parse.quote(since)}"
        f"&select=from_addr,delivered,bounced,complained&limit=20000"
    )
    # Bucket counts by sending-domain root (e.g. tryalgoalpha.com).
    from collections import defaultdict
    by_root = defaultdict(lambda: {"total": 0, "bounced": 0, "complained": 0})
    for r in rows:
        fa = (r.get("from_addr") or "").lower()
        dom = fa.split("@", 1)[1] if "@" in fa else ""
        root = ".".join(dom.split(".")[-2:]) if dom else ""
        if not root:
            continue
        b = by_root[root]
        b["total"] += 1
        if r.get("bounced"):
            b["bounced"] += 1
        if r.get("complained"):
            b["complained"] += 1

    repo = _P(__file__).resolve().parent.parent
    now_iso = dt.datetime.now(dt.timezone.utc).isoformat()
    for pf in _glob.glob(str(repo / "profiles" / "*.json")):
        if pf.endswith(".private.json") or ".bak" in pf:
            continue
        try:
            prof = json.loads(_P(pf).read_text(encoding="utf-8"))
        except Exception:
            continue
        roots = set()
        for d in (prof.get("relay") or {}).get("from_domains", []):
            dom = (d.get("domain") or "").lower()
            if dom:
                roots.add(".".join(dom.split(".")[-2:]))
        if not roots:
            continue
        total = sum(by_root[r]["total"] for r in roots)
        bounced = sum(by_root[r]["bounced"] for r in roots)
        complained = sum(by_root[r]["complained"] for r in roots)
        br = (bounced / total) if total else 0.0
        cr = (complained / total) if total else 0.0
        rep = prof.setdefault("warmup", {}).setdefault("reputation", {})
        old_br = rep.get("bounce_rate_7d", 0.0)
        rep["bounce_rate_7d"] = round(br, 4)
        rep["complaint_rate_7d"] = round(cr, 4)
        rep["delivered_7d"] = total - bounced
        rep["last_check"] = now_iso
        flag = " (AUTO-PAUSE RANGE)" if br > 0.05 else ""
        print(f"  reputation {prof.get('slug','?'):16} bounce_7d={br:.3f} "
              f"complaint_7d={cr:.4f} n={total}{flag}")
        if not dry:
            _P(pf).write_text(json.dumps(prof, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
