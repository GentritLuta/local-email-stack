"""scaffold-niche.py — MODULAR onboarding block: turn a client's ICP into a ready
lead-sourcing niche, so per-client scraping is one command instead of hand-editing.

Writes niches/<slug>.yaml from the shared template and prints the PROFILE_CFG entry
to paste into sequences/daily-fill-and-enroll.py. After that, the existing
LES-seed-discover + LES-lead-scrape + LES-daily-fill-and-enroll tasks source and
enroll leads for the new client with no further custom code.

    py scripts/scaffold-niche.py --profile acme --engine team_pages \
        --icp "independent US insurance brokerages" \
        --queries "insurance brokerage team page Texas" "independent insurance agency our team California"

    py scripts/scaffold-niche.py --profile mueller --engine impressum \
        --icp "DACH Maschinenbau KMU" --country de
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
NICHES = REPO / "niches"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="profile slug this niche feeds")
    ap.add_argument("--engine", default="team_pages", choices=["team_pages", "social", "impressum"])
    ap.add_argument("--icp", required=True, help="one-line ICP description")
    ap.add_argument("--queries", nargs="*", default=[], help="discovery search queries (team_pages/impressum)")
    ap.add_argument("--keywords", nargs="*", default=None, help="seed_require_keywords (page must contain one)")
    ap.add_argument("--country", default="us", help="discovery search_country (us, de, ch, ...)")
    ap.add_argument("--require-first-name", action="store_true")
    ap.add_argument("--slug", default=None, help="niche slug (default: <profile>_icp)")
    args = ap.parse_args()

    slug = args.slug or f"{args.profile}_icp"
    out = NICHES / f"{slug}.yaml"
    if out.exists():
        print(f"refusing to overwrite existing niche: {out}")
        return 1

    kw = args.keywords or (["impressum", "kontakt", "geschäftsführer"] if args.engine == "impressum"
                            else ["team", "about", "contact", "our"])
    queries = args.queries or [f"{args.icp} team page", f"{args.icp} our team", f"{args.icp} contact"]

    lines = [
        f"slug: {slug}",
        f'name: "{args.profile} — {args.icp}"',
        f"profile_slug: {args.profile}",
        f"engine: {args.engine}",
        "",
        f"# ICP: {args.icp}",
        f"require_first_name: {str(args.require_first_name).lower()}",
        "",
        "seeds:   # seed_discover.py appends discovered URLs here (block style; do NOT use [])",
        "",
        "search_queries:",
    ]
    lines += [f'  - "{q}"' for q in queries]
    lines += [
        "",
        "seed_require_keywords: [" + ", ".join(f'"{k}"' for k in kw) + "]",
        "",
        "discovery:",
        "  max_seeds_per_run: 20",
        f"  search_country:    {args.country}",
        "  require_mailto:    true",
        "",
        "sequence:",
        f"  variants_file: sequences/{args.profile}-default/variants.json",
    ]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {out}")

    # PROFILE_CFG snippet (paste into sequences/daily-fill-and-enroll.py PROFILE_CFG)
    cfg = {
        "niche_slug": slug if args.engine != "social" else None,
        "backfill_script": None,
        "creator_scrapers": [],
        "requires_city": False,
        "requires_first_name": args.require_first_name,
    }
    print("\n--- paste into PROFILE_CFG in sequences/daily-fill-and-enroll.py ---")
    print(f'    "{args.profile}": {json.dumps(cfg, indent=8)[:-1]}    }},')
    print("\nThen: enable LES-lead-scrape + confirm LES-seed-discover covers this niche.")
    return 0


if __name__ == "__main__":
    main()
