# -*- coding: utf-8 -*-
"""reverify-unknowns.py - paced re-verification of smtp_unknown prospects.

When the live verifier cannot get a definitive SMTP answer (our IP was momentarily
rate-limited, or the host greylisted us), lead_verify marks the address
verified=True with method='smtp_unknown' so we never drop a valid lead on
uncertainty. THIS pass revisits those addresses slowly, at a rate that keeps the
single sending IP healthy, and flips a prospect to verified=false + unsubscribed
ONLY when the mail server gives a definitive 550 (mailbox does not exist).

This is the free, permanent equivalent of a paid verifier's re-check queue: the
provider format rules + definitive 550s catch dead mailboxes; uncertainty is
retried over time, never guessed.

Run it on a schedule (e.g. every 30 min) with a small batch so probing stays
gentle. Idempotent: an address re-marked smtp_verified or still-unknown is left
send-eligible; only a 550 suppresses it.

Usage:
  py sequences/reverify-unknowns.py            # default batch (25), live
  py sequences/reverify-unknowns.py --limit 10 --dry
"""
import argparse
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
import importlib.util
_spec = importlib.util.spec_from_file_location("lead_verify", REPO / "sequences" / "lead_verify.py")
lead_verify = importlib.util.module_from_spec(_spec)
sys.modules["lead_verify"] = lead_verify
_spec.loader.exec_module(lead_verify)


def load_env(path: Path) -> dict:
    d = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("'")
    return d


SUPA = load_env(REPO / "sequences" / "supabase.env")
URL = SUPA["SUPABASE_URL"].rstrip("/")
KEY = SUPA["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def supa_get(path: str) -> list:
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H), timeout=40).read())


def supa_patch(path: str, body: dict) -> None:
    urllib.request.urlopen(urllib.request.Request(
        f"{URL}/rest/v1/{path}", data=json.dumps(body).encode(),
        headers={**H, "Prefer": "return=minimal"}, method="PATCH"), timeout=30).read()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    # Oldest-checked unknowns first. The verifier paces itself per MX host.
    rows = supa_get(
        "prospects?verification_method=eq.smtp_unknown&unsubscribed=eq.false"
        "&select=id,email,verified_at"
        f"&order=verified_at.asc.nullsfirst&limit={args.limit}"
    )
    print(f"smtp_unknown prospects to re-verify: {len(rows)}")
    stats = {"resolved_valid": 0, "suppressed_dead": 0, "still_unknown": 0}

    for p in rows:
        email = p.get("email") or ""
        v = lead_verify.verify(email)            # paced + retried internally
        if v.method == "smtp_rejected":
            stats["suppressed_dead"] += 1
            print(f"  DEAD  {email}  -> {v.error[:60] if v.error else '550'}")
            if not args.dry:
                supa_patch(f"prospects?id=eq.{p['id']}",
                           {"verified": False, "unsubscribed": True,
                            "verification_method": "smtp_rejected",
                            "verification_error": (v.error or "")[:300]})
        elif v.method == "smtp_verified":
            stats["resolved_valid"] += 1
            print(f"  OK    {email}  -> confirmed deliverable")
            if not args.dry:
                supa_patch(f"prospects?id=eq.{p['id']}",
                           {"verification_method": "smtp_verified"})
        else:
            # still unknown / catch_all / unknown: leave send-eligible, just bump the clock
            stats["still_unknown"] += 1
            if not args.dry:
                import datetime as dt
                supa_patch(f"prospects?id=eq.{p['id']}",
                           {"verified_at": dt.datetime.now(dt.timezone.utc).isoformat()})

    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
