"""verify-atalsolidrocks.py — after DNS records are published, run this to
poll Resend for verification status across all 12 subdomains and stamp
verified_at into profiles/atalsolidrocks.json for any that flipped.

Idempotent — re-run as many times as needed until all 12 are verified.

Run:
    py scripts/verify-atalsolidrocks.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from profile_lib import load_profile, save_profile  # noqa: E402

env = {}
for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
KEY = env["RESEND_FULL_ACCESS_API_KEY"]
API = "https://api.resend.com"


def main() -> int:
    profile = load_profile("atalsolidrocks")
    domains = profile.get("relay", {}).get("from_domains", [])
    print(f"Polling Resend for {len(domains)} subdomains...\n")
    changed = 0
    with httpx.Client(timeout=15) as c:
        for d in domains:
            sub = d["domain"]
            did = d["resend_domain_id"]
            if d.get("verified_at"):
                print(f"  [skip] {sub}  already verified at {d['verified_at']}")
                continue
            # GET first — if already verified, no need to re-trigger
            # (the POST /verify resets status to 'pending' during re-check)
            r = c.get(f"{API}/domains/{did}",
                      headers={"Authorization": f"Bearer {KEY}"})
            if r.status_code != 200:
                print(f"  ! {sub}  HTTP {r.status_code}")
                continue
            data = r.json()
            status = data.get("status") or data.get("verification_status")
            if status == "verified":
                import datetime as dt
                d["verified_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                changed += 1
                print(f"  ✓ {sub}  -> verified ({d['verified_at'][:19]})")
            else:
                # Show which records still fail
                bad = [r for r in (data.get("records") or []) if r.get("status") not in ("verified", "ok")]
                print(f"  … {sub}  status={status}  records-pending={len(bad)}")
            time.sleep(0.3)
    if changed:
        save_profile(profile)
        print(f"\n→ Updated profiles/atalsolidrocks.json — {changed} subdomain(s) flipped to verified.")
    else:
        print("\nNo changes. Re-run after DNS has propagated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
