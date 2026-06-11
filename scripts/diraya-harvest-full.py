# -*- coding: utf-8 -*-
"""diraya-harvest-full.py — full YC-universe lead refresh for Diraya (zero-bounce).

Diraya is wired to send 15/domain (150/day) but is lead-supply bound: it can only
mail YC founders who PUBLISH an email on their site (so bounce rate stays ~0). This
widens the funnel to the WHOLE YC directory:

  1. Rebuild the worksheet from every YC company page (~6k), keeping the AI ICP.
  2. Harvest every published founder email across that full set and import to Diraya.

The orchestrator then enrolls them and sends up to the 15/domain warmup cap.

GUARDED: if another diraya site-scrape is already running, this skips immediately —
concurrent large scrapes exhausted sockets before, so we never double-run. Uses 8
workers (proven stable solo). Wired to the weekly LES-diraya-site-scrape task plus a
one-time overnight run for the first full sweep.

  py scripts/diraya-harvest-full.py            # refresh worksheet + harvest all + import
  py scripts/diraya-harvest-full.py --no-refresh   # skip worksheet rebuild, harvest existing
"""
from __future__ import annotations
import argparse, subprocess, sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"
WORKSHEET = REPO / "out" / "diraya_linkedin_targets.csv"
CANDIDATES = REPO / "out" / "_yc_candidates.csv"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def harvest_already_running() -> bool:
    """True if another diraya-site-scrape / harvest-full process is active."""
    try:
        out = subprocess.run(["wmic", "process", "where", "name='python.exe'", "get", "CommandLine"],
                             capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return False
    n = out.count("diraya-site-scrape") + out.count("diraya-harvest-full")
    return n > 1            # >1 because this process counts itself (harvest-full)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-refresh", action="store_true", help="skip worksheet rebuild")
    ap.add_argument("--limit", type=int, default=6000, help="max worksheet rows to harvest")
    args = ap.parse_args()

    if harvest_already_running():
        print("! a Diraya harvest is already running — skipping this full sweep (avoids socket exhaustion).")
        return 0

    if not args.no_refresh:
        print("[1/3] rebuilding worksheet from the full YC directory (AI ICP, all batches)...")
        r = subprocess.run([sys.executable, str(SCRIPTS / "yc-guess-verify.py"),
                            "--no-verify", "--max-pages", "6500", "--min-year", "2023",
                            "--out", str(WORKSHEET), "--dump-candidates", str(CANDIDATES)],
                           cwd=str(REPO))
        if r.returncode != 0:
            print("! worksheet rebuild failed; harvesting the existing worksheet instead.")
        print("[2/3] discovering non-YC AI startups (CSE + accelerators + Product Hunt) + appending...")
        subprocess.run([sys.executable, str(SCRIPTS / "diraya-discover.py"), "--cse-queries", "12"],
                       cwd=str(REPO))

    print(f"[3/3] harvesting published founder emails (limit {args.limit}, 8 workers) + importing...")
    subprocess.run([sys.executable, str(SCRIPTS / "diraya-site-scrape.py"),
                    "--limit", str(args.limit), "--workers", "8", "--import"], cwd=str(REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
