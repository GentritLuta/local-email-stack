# -*- coding: utf-8 -*-
"""Auto-flip ENER-G to live IFF its .de subdomains are verified on Resend.

Idempotent: safe to run repeatedly. Checks Resend status for the two .de
subdomains using ENER-G's own management key; only when BOTH are verified does
it stamp verified_at, set send_ramp.started_at=today, enable warmup, and enable
the LES-warmup-energ scheduled task. Otherwise it reports 'still pending' and
exits 0 so a re-poll can try again later.

Usage:  py scripts/_flip-energ-when-verified.py [--force-date YYYY-MM-DD]
"""
import json
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

REPO = Path(__file__).resolve().parent.parent
PROFILE = REPO / "profiles" / "energ.json"
PRIVATE = REPO / "profiles" / "energ.private.json"
DE_SUBS = {"hello.ener-g-beratung.de", "team.ener-g-beratung.de"}


def mgmt_key() -> str:
    p = json.loads(PRIVATE.read_text(encoding="utf-8"))
    return (p.get("relay") or {}).get("resend_api_key", "") or p.get("resend_api_key", "")


def main() -> int:
    date = "2026-06-11"
    if "--force-date" in sys.argv:
        date = sys.argv[sys.argv.index("--force-date") + 1]
    key = mgmt_key()
    prof = json.loads(PROFILE.read_text(encoding="utf-8"))
    doms = (prof.get("relay") or {}).get("from_domains", [])
    status = {}
    for d in doms:
        if d["domain"] in DE_SUBS and d.get("resend_domain_id"):
            r = httpx.get(f"https://api.resend.com/domains/{d['resend_domain_id']}",
                          headers={"Authorization": f"Bearer {key}"}, timeout=20)
            status[d["domain"]] = r.json().get("status") if r.status_code == 200 else f"http{r.status_code}"
    print("ENER-G .de status:", status)
    if not (status and all(v == "verified" for v in status.values())):
        print("not all verified yet -> holding flip")
        return 0

    # Flip live
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for d in doms:
        if d["domain"] in DE_SUBS:
            d["verified_at"] = now
    prof.setdefault("send_ramp", {})["started_at"] = date
    prof.setdefault("warmup", {})["enabled"] = True
    PROFILE.write_text(json.dumps(prof, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"ENER-G flipped live: started_at={date}, warmup.enabled=True, .de verified_at stamped")

    # Enable the warmup task
    ps = ("Enable-ScheduledTask -TaskName 'LES-warmup-energ' | Out-Null; "
          "(Get-ScheduledTask -TaskName 'LES-warmup-energ').State")
    out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                         capture_output=True, text=True)
    print("LES-warmup-energ ->", (out.stdout or out.stderr).strip())
    # First warmup tick (init day)
    tick = subprocess.run(["py", str(REPO / "sequences" / "warmup-scheduler.py"),
                           "tick", "--profile", "energ"],
                          capture_output=True, text=True, cwd=str(REPO))
    print((tick.stdout or "")[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
