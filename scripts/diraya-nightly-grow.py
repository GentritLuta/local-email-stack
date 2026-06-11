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
    ap.add_argument("--target", type=int, default=40,
                    help="verified new founders to aim for this run")
    ap.add_argument("--max-pages", type=int, default=1200)
    a = ap.parse_args()

    # 1. harvest + verify a bounded slice of fresh YC AI founders
    rc = run([PY, "scripts/yc-guess-verify.py",
              "--target-leads", str(a.target),
              "--max-pages", str(a.max_pages),
              "--out", str(OUT)])
    if rc != 0 or not OUT.exists():
        print(f"harvest step rc={rc}, out exists={OUT.exists()} — nothing to import")
        return rc or 1

    # 2. import the verified founders into diraya (dedup on write)
    rc = run([PY, "scripts/import-prospects-csv.py", "diraya", str(OUT),
              "--niche", "yc_ai"])
    print(f"nightly grow done (import rc={rc})")
    return rc


if __name__ == "__main__":
    sys.exit(main())
