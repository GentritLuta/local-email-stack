# -*- coding: utf-8 -*-
"""seo-autodeploy-when-ready.py — fire the mark-eting SEO-magnet deploy the moment
Supabase is reachable again, with no human in the loop.

Background: on 2026-06-29 the Supabase free-tier project hit its monthly egress
cap (HTTP 402 exceed_egress_quota), which pauses the whole stack. Free-tier egress
resets at the start of the month, so the DB self-heals around 2026-07-01 at no
cost (upgrading or removing the spend cap would cost money, which the free-only
rule forbids). This task watches for that recovery and then runs the one-time
deploy + research prime so the email-1/email-5 personalization goes live by itself.

Logic (egress-friendly: zero DB calls once it has run):
  1. If the sentinel exists, exit immediately. Nothing to do, no DB hit.
  2. Otherwise ping the DB once. If still blocked, exit quietly and retry next tick.
  3. If reachable, run deploy-mark-eting-seo.py. On success, write the sentinel
     and best-effort prime research (seo_research.py --force). Then disable this
     task so it stops pinging.

Schedule (every 30 min):
    schtasks /Create /TN "LES-seo-autodeploy" /SC MINUTE /MO 30 ^
      /TR "pyw C:\\Users\\bernh\\local-email-stack\\scripts\\seo-autodeploy-when-ready.py" /F
"""
from __future__ import annotations

import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SENTINEL = REPO / "out" / ".seo_autodeploy_done"
ENV_FILE = REPO / "sequences" / "supabase.env"
PY = sys.executable or "py"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def db_reachable() -> bool:
    env = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    url = env["SUPABASE_URL"].rstrip("/")
    key = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
    req = urllib.request.Request(
        f"{url}/rest/v1/prospects?select=id&limit=1",
        headers={"apikey": key, "Authorization": "Bearer " + key, "User-Agent": "seo-autodeploy"})
    try:
        urllib.request.urlopen(req, timeout=20).read()
        return True
    except Exception as e:
        print(f"db not ready: {str(e)[:120]}")
        return False


def run(args: list[str]) -> int:
    print("  $ " + " ".join(Path(a).name if a.endswith(".py") else a for a in args))
    p = subprocess.run([PY, *args], cwd=str(REPO))
    return p.returncode


def main() -> int:
    if SENTINEL.exists():
        print("already deployed (sentinel present) — nothing to do")
        return 0
    if not db_reachable():
        return 0  # retry next tick; the monthly egress reset will restore service

    print("Supabase reachable — running mark-eting SEO deploy")
    rc = run([str(REPO / "scripts" / "deploy-mark-eting-seo.py")])
    if rc != 0:
        print(f"deploy failed (rc={rc}); will retry next tick, NOT disarming")
        return rc

    SENTINEL.parent.mkdir(parents=True, exist_ok=True)
    SENTINEL.write_text("deployed\n", encoding="utf-8")
    print("deploy ok — sentinel written")

    # Best-effort: prime research now so the first sends already carry proof.
    rc2 = run([str(REPO / "sequences" / "seo_research.py"),
               "once", "--slug", "mark-eting", "--force", "--limit", "200"])
    print(f"research prime rc={rc2} (best-effort; hourly LES-seo-research continues either way)")

    # Disarm: stop this task from pinging the DB forever.
    try:
        subprocess.run(["schtasks", "/Change", "/TN", "LES-seo-autodeploy", "/DISABLE"],
                       capture_output=True)
        print("disabled LES-seo-autodeploy")
    except Exception as e:
        print(f"could not disable task (harmless, sentinel still no-ops): {str(e)[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
