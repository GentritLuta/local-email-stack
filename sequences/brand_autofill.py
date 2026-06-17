"""brand_autofill.py — autonomous brand extraction for every client profile.

Looks at every profiles row in Supabase. For each profile where:
  * config.company.site is set AND
  * config.brand is missing OR config.brand.extracted_from doesn't match the site,

we run brand_extract against the site and write the new brand back. This means
when an operator creates a new client profile through the desktop app with just
a website URL, the email styling (colors, font, wordmark, tagline) auto-fills
within one scheduler tick — no manual step.

CLI:
    py sequences/brand_autofill.py once          # scan all profiles, fill missing brand
    py sequences/brand_autofill.py once --slug X # only one profile
    py sequences/brand_autofill.py once --force  # re-extract even if already set

Schedule (every 15 min):
    schtasks /Create /TN "LES-brand-autofill" /SC MINUTE /MO 15 ^
      /TR "py C:\\Users\\bernh\\local-email-stack\\sequences\\brand_autofill.py once"
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from brand_extract import extract_brand  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE  = REPO_ROOT / "sequences" / "supabase.env"


def load_supabase() -> tuple[str, str]:
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env["SUPABASE_URL"].rstrip("/"), env["SUPABASE_ANON_KEY"]


def _site_url(site: str) -> str:
    site = (site or "").strip()
    if not site: return ""
    if not site.startswith(("http://", "https://")):
        site = "https://" + site
    return site


def autofill_once(slug_filter: str | None = None, force: bool = False) -> int:
    url, key = load_supabase()
    with httpx.Client(base_url=f"{url}/rest/v1",
                      headers={"apikey": key, "Authorization": f"Bearer {key}",
                               "Content-Type": "application/json",
                               "Prefer": "return=representation"},
                      timeout=30) as c:
        q = "/profiles?select=slug,config"
        if slug_filter:
            q += f"&slug=eq.{slug_filter}"
        r = c.get(q)
        r.raise_for_status()
        profiles = r.json()

        examined = filled = skipped = failed = 0
        for prof in profiles:
            examined += 1
            cfg = prof.get("config") or {}
            company = cfg.get("company") or {}
            site = _site_url(company.get("site", ""))
            if not site:
                print(f"  - {prof['slug']:20} skip: no company.site")
                skipped += 1; continue

            # Skip placeholder/draft URLs (reserved TLDs never resolve, so a
            # fetch always fails and would trip the task's non-zero exit).
            host = site.split("://", 1)[-1].split("/", 1)[0].lower()
            if host.rsplit(".", 1)[-1] in ("example", "invalid", "test", "localhost"):
                print(f"  - {prof['slug']:20} skip: placeholder site {site}")
                skipped += 1; continue

            existing_brand = cfg.get("brand")
            if existing_brand and not force:
                ef = (existing_brand or {}).get("extracted_from", "")
                if ef.rstrip("/") == site.rstrip("/"):
                    print(f"  - {prof['slug']:20} skip: brand already extracted from {site}")
                    skipped += 1; continue

            print(f"  > {prof['slug']:20} extracting brand from {site} ...")
            brand = extract_brand(site)
            if brand is None:
                print(f"    ! extract failed (fetch error)")
                failed += 1; continue
            # MERGE the auto-extracted brand INTO the existing brand instead of
            # replacing it. A bare replace silently dropped manually-set fields,
            # most critically `template` (the custom-HTML dispatcher key) and any
            # hand-tuned colors/legal/tagline. That clobbered aureon + algoalpha's
            # custom templates back to "default" every 15 min (2026-06-12 fix).
            # Never overwrite these operator-owned keys from a site scrape:
            PRESERVE = ("template", "legal", "tagline", "reply_tone",
                        "unsubscribe_url_template", "cta_url")
            merged = dict(existing_brand or {})
            for k, v in asdict(brand).items():
                if k in PRESERVE and merged.get(k) not in (None, "", {}, []):
                    continue  # keep the operator's value
                merged[k] = v
            for k in PRESERVE:
                if existing_brand and existing_brand.get(k) not in (None, "", {}, []):
                    merged[k] = existing_brand[k]
            cfg["brand"] = merged

            up = c.patch(f"/profiles?slug=eq.{prof['slug']}", json={"config": cfg})
            if up.status_code not in (200, 204):
                print(f"    ! supabase patch {up.status_code}: {up.text[:200]}")
                failed += 1; continue
            filled += 1
            print(f"    ok: accent={brand.colors['accent']} font={brand.font_stack.split(',')[0]}")

        print(f"\n=== summary === examined={examined} filled={filled} skipped={skipped} failed={failed}")
        return 0 if failed == 0 else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_once = sub.add_parser("once")
    p_once.add_argument("--slug", default=None, help="only one profile slug")
    p_once.add_argument("--force", action="store_true",
                        help="re-extract even if brand was already set")
    args = ap.parse_args()
    if args.cmd == "once":
        return autofill_once(args.slug, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
