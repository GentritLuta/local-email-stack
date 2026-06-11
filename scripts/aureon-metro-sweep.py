# -*- coding: utf-8 -*-
"""aureon-metro-sweep.py — clean, systematic brokerage discovery for Aureon.

The "engine" front-end Aureon was missing. Real estate has no YC-style directory,
so instead of 14 vague queries we sweep tight, indie-focused real-estate queries
across many US metros, gate hard (the bounce-proof filters from the niche YAML),
and append clean brokerage team-page URLs to real_estate_us.yaml for the existing
lead_scrape harvest to mine.

Search backend = seed_discover._search() — tries Google CSE first (once you enable
the Custom Search JSON API), falls back to Brave today. So this same script
auto-upgrades to CSE the moment it's switched on (covers both option 1 and 2).

Usage:
  py scripts/aureon-metro-sweep.py --cap 120          # discover + append seeds
  py scripts/aureon-metro-sweep.py --cap 120 --dry    # discover, validate, no write
"""
from __future__ import annotations
import sys, argparse
from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
import seed_discover as sd  # reuse the battle-tested search + gate + append
sd._STEALTH_DISABLED = True  # bulk run: httpx-only validation so it's thread-safe + fast
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# High-real-estate-activity US metros (matches the niche's TX/FL/AZ/CO/GA/NC/TN/OH
# focus + the big indie-brokerage markets). Kept to ~55 so Brave's free tier
# (1 req/s, ~2k/mo) isn't blown by one run.
METROS = [
    "Austin TX", "Dallas TX", "Houston TX", "San Antonio TX", "Fort Worth TX",
    "Miami FL", "Tampa FL", "Orlando FL", "Jacksonville FL", "Fort Lauderdale FL",
    "Phoenix AZ", "Scottsdale AZ", "Tucson AZ", "Mesa AZ",
    "Denver CO", "Colorado Springs CO", "Boulder CO", "Fort Collins CO",
    "Atlanta GA", "Savannah GA", "Augusta GA",
    "Charlotte NC", "Raleigh NC", "Asheville NC", "Greensboro NC",
    "Nashville TN", "Knoxville TN", "Chattanooga TN", "Memphis TN",
    "Columbus OH", "Cleveland OH", "Cincinnati OH",
    "Detroit MI", "Grand Rapids MI", "Ann Arbor MI",
    "Las Vegas NV", "Reno NV", "Henderson NV",
    "Charleston SC", "Greenville SC", "Columbia SC",
    "Salt Lake City UT", "Boise ID", "Spokane WA", "Tacoma WA",
    "Portland OR", "Sacramento CA", "Fresno CA", "Bakersfield CA",
    "Richmond VA", "Virginia Beach VA", "Indianapolis IN", "Louisville KY",
    "Oklahoma City OK", "Tulsa OK",
]
PATTERNS = [
    "independent real estate brokerage {c} meet our team",
    "boutique real estate brokerage {c} our agents",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cap", type=int, default=120, help="max new seeds to append")
    ap.add_argument("--per-query", type=int, default=8)
    ap.add_argument("--max-queries", type=int, default=0,
                    help="cap total search queries (0=all) — keeps under CSE's 100/day free quota")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    yaml_path, niche = sd._load_niche("real_estate_us")
    existing = sd._existing_seed_urls(niche)
    disc = niche.get("discovery") or {}
    skip = set(disc.get("exclude_domains") or [])
    req_kw = list(disc.get("require_keywords") or [])
    req_mt = bool(disc.get("require_mailto", True))
    queries = [p.format(c=c) for c in METROS for p in PATTERNS]
    if args.max_queries:
        queries = queries[:args.max_queries]
    print(f"metros={len(METROS)}  queries={len(queries)}  existing seeds={len(existing)}")
    print(f"gates: require_mailto={req_mt}  require_kw={req_kw}")

    # 1) discover (Brave/CSE via dispatcher) — sequential (rate-limited)
    seen, by_dom, cand = set(), {}, []
    for i, q in enumerate(queries, 1):
        urls = sd._search(q, args.per_query, "us")
        for u in urls:
            u = u.rstrip("/")
            host = urlparse(u).netloc.lower().lstrip("www.")
            if not host or u in seen or u in existing:
                continue
            if any(host.endswith(b) for b in skip):
                continue
            if host in by_dom:               # one team-page per brokerage domain
                continue
            seen.add(u); by_dom[host] = u; cand.append(u)
        if i % 20 == 0:
            print(f"  ..{i}/{len(queries)} queries, {len(cand)} unique-domain candidates")
    print(f"raw candidates (unique domains): {len(cand)}")

    # 2) validate in parallel (httpx-only: HTTP 200 + mailto + RE keyword)
    validated = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(sd._is_valid_seed, u, req_mt, req_kw): u for u in cand}
        for fut in as_completed(futs):
            try:
                ok, why = fut.result()
            except Exception:
                ok = False
            if ok:
                validated.append(futs[fut])
    validated = validated[:args.cap]
    print(f"validated clean brokerage seeds: {len(validated)}")
    for u in validated[:15]:
        print("   OK", u)

    if args.dry:
        print("[dry] no write."); return 0
    if validated:
        sd._append_seeds_to_yaml(yaml_path, validated)
        print(f"appended {len(validated)} seeds to {yaml_path.name}  "
              f"(was {len(existing)} -> now {len(existing)+len(validated)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
