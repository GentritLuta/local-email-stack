"""Apply the new standard warmup curve to a profile.

Curve (per subdomain, per day):
    days  1- 7 → 15 sends
    days  8-14 → 25 sends
    days 15-21 → 35 sends
    days 22+   → 50 sends

Also stamps warmup.started_at = today on the profile AND on every
from_domain so the ramp begins from now.

Usage:
    py scripts/set-warmup-curve.py aureon algoalpha lk-advertising
"""
from __future__ import annotations
import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILES = REPO / "profiles"
PUBLIC = REPO / "desktop" / "frontend" / "public" / "profiles"

NEW_CURVE = [
    {"from_day":  1, "daily": 15},
    {"from_day":  8, "daily": 25},
    {"from_day": 15, "daily": 35},
    {"from_day": 22, "daily": 50},
]
FINAL_MAX = 50   # absolute ceiling per subdomain at full ramp
TODAY = dt.date.today().isoformat()


def apply(slug: str) -> None:
    pf = PROFILES / f"{slug}.json"
    if not pf.exists():
        print(f"  ! {slug}: no profile file")
        return
    data = json.loads(pf.read_text(encoding="utf-8"))

    # Profile-level ramp + warmup start
    data["ramp_curve_snowball_v1"] = NEW_CURVE
    data.setdefault("warmup", {})
    data["warmup"]["started_at"] = TODAY
    data["warmup"]["current_day"] = 1
    data["warmup"]["ramp_curve"] = "snowball_v1"

    # Per-subdomain warmup: same curve applies, cap each at FINAL_MAX
    n_domains = 0
    for d in data.get("relay", {}).get("from_domains", []):
        d.setdefault("warmup", {})
        d["warmup"]["started_at"] = TODAY
        d["warmup"]["current_day"] = 1
        d["warmup"]["ramp_curve"] = "snowball_v1"
        d["warmup"]["max_daily_sends"] = FINAL_MAX
        n_domains += 1

    pf.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    pub = PUBLIC / f"{slug}.json"
    if pub.exists():
        pub.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    daily_total = FINAL_MAX * n_domains
    print(f"  + {slug:18s} curve 15>25>35>50  {n_domains} subdomains  "
          f"max daily total {daily_total}  started {TODAY}")


def main() -> int:
    slugs = sys.argv[1:]
    if not slugs:
        sys.exit("usage: set-warmup-curve.py <slug> [slug...]")
    for slug in slugs:
        apply(slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
