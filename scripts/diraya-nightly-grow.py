# -*- coding: utf-8 -*-
"""diraya-nightly-grow.py — one nightly batch that grows the Diraya prospect pool.

Diraya is import-only and its YC published-email pool tops out ~100-150 in a
single pass, so instead of one huge run we chip away nightly: each run harvests a
bounded slice of fresh YC AI founders (guess+verify real emails), then imports the
verified ones into the diraya pool (deduped). Over days this lifts Diraya past the
single-pass ceiling without a multi-hour job.

Chains the two existing tools:
  1. scripts/yc-guess-verify.py  --target-leads N  --out out/diraya_nightly.csv
  2. scripts/import-prospects-csv.py diraya out/diraya_nightly.csv --niche yc_ai

Scheduled as LES-diraya-nightly-grow (nightly). Bounded target so it finishes in
well under an hour. Idempotent: import dedupes by (profile_slug, email), so
re-finding the same founders is harmless.

USAGE:
    py scripts/diraya-nightly-grow.py                 # default target 40
    py scripts/diraya-nightly-grow.py --target 60
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
OUT = REPO / "out" / "diraya_nightly.csv"


def run(cmd: list[str]) -> int:
    print(">>", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, cwd=str(REPO), text=True)
    return p.returncode


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", "--target", type=int, default=250, dest="limit",
                    help="YC target domains per nightly run; with --rotate the cursor advances "
                         "this many each night so the full ~1382-domain set is covered over ~6 nights. "
                         "--target is an accepted alias (the LES-diraya-nightly-grow task passes --target).")
    ap.add_argument("--workers", type=int, default=16)
    a = ap.parse_args()

    # PUBLISHED-EMAIL harvest (replaces the old yc-guess-verify path, which
    # verified ~0/night because guess+verify needs port 25 and most startup
    # domains are catch-all or time out — pool sat frozen at 99). diraya-site-scrape
    # harvests the founder emails the YC startups PUBLISH on their own /team,
    # /about, /leadership etc. pages, MX-verifies (no port 25), name-matches, and
    # imports the named ones (dedup on write). Published == real == ~0% bounce.
    # 2026-06-13: switched here after the harvester's page coverage was widened
    # (5 -> 16 paths + de-obfuscation) so it finds founder emails the narrow scan missed.
    rc = run([PY, "scripts/diraya-site-scrape.py",
              "--limit", str(a.limit),
              "--workers", str(a.workers),
              "--rotate",          # walk the cursor through the whole target set over nights
              "--import"])
    print(f"nightly grow done (published-email harvest rc={rc})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
