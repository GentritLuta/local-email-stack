"""places_scrape.py — Google Maps / Places lead source via Serper /places.

For LOCAL-business niches (real estate, trades, US service businesses, property
managers, industrial KMU) generic team-page SERP scraping is low-yield: a plumber
or a broker rarely publishes a "team page" with a mailto. But they all have a
Google Business Profile with a website, and the website has a contact email.

This source:
  1. Queries Serper's /places endpoint by "<category> in <city>".
  2. For each result with a website, visits the site (home + /contact + /about).
  3. Extracts + verifies the email (reusing lead_scrape + lead_verify).
  4. Upserts with company = the business name and city = the queried city.

Uses the EXISTING Serper key (no new spend) and ~80% of the existing pipeline.
Because Places returns company + city directly, it also fixes the city-required
brands (atalsolidrocks) that team-page scraping leaves cityless.

Niche YAML adds an optional `places:` block:
  places:
    categories: ["plumber", "HVAC contractor", "roofing company"]
    cities:     ["Austin TX", "Dallas TX", "Houston TX"]
    queries:    ["personal injury lawyer in Phoenix AZ"]   # explicit; optional
    country:    us
    max_per_query: 20
    contact_paths: ["", "contact", "contact-us", "about", "about-us"]

CLI:
  py places_scrape.py run <niche> [--limit N] [--max-per-query N] [--dry] [--smtp]
  py places_scrape.py probe "plumber in Austin TX"        # show raw Serper places
  py places_scrape.py list                                # niches with a places block
"""
from __future__ import annotations
import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lead_scrape import (  # noqa: E402
    ScrapedLead, fetch_html, extract_leads_from_page,
    supa_upsert_prospect, load_supabase, load_niche, NICHES_DIR,
)
from lead_verify import verify, JUNK_LOCAL_PARTS  # noqa: E402
from name_derive import derive_first_name, derive_company, is_free_or_isp_domain  # noqa: E402

SEARCH_ENV = HERE / "search.env"
DEFAULT_CONTACT_PATHS = ["", "contact", "contact-us", "about", "about-us", "kontakt", "impressum"]
TIME_BUDGET_SEC = 480  # leave headroom under the 600s orchestrator kill


# ─── Serper /places ─────────────────────────────────────────────────────────

def serper_key() -> str | None:
    k = os.environ.get("SERPER_API_KEY")
    if k and not k.startswith("<"):
        return k
    if SEARCH_ENV.exists():
        for line in SEARCH_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SERPER_API_KEY") and "=" in line:
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v and not v.startswith("<"):
                    return v
    return None


def serper_places(query: str, country: str, api_key: str, num: int = 20) -> list[dict]:
    """Call Serper's Places endpoint. Returns the `places` list (title, address,
    website, phoneNumber, ...)."""
    r = httpx.post(
        "https://google.serper.dev/places",
        json={"q": query, "gl": (country or "us"), "num": num},
        headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    return r.json().get("places", []) or []


# ─── Query generation + cursor ──────────────────────────────────────────────

def build_queries(places_cfg: dict) -> list[tuple[str, str | None]]:
    """Return (query, city_label) pairs. Explicit `queries` win; otherwise the
    cartesian of categories x cities."""
    out: list[tuple[str, str | None]] = []
    for q in places_cfg.get("queries") or []:
        m = re.search(r"\bin\s+(.+)$", q, re.I)
        out.append((q, m.group(1).strip() if m else None))
    cats = places_cfg.get("categories") or []
    cities = places_cfg.get("cities") or []
    for city in cities:
        for cat in cats:
            out.append((f"{cat} in {city}", city))
    # De-dup, preserve order.
    seen, uniq = set(), []
    for q, c in out:
        if q.lower() in seen:
            continue
        seen.add(q.lower())
        uniq.append((q, c))
    return uniq


def _done_path(slug: str) -> Path:
    return NICHES_DIR / f"{slug}.places.done"


def load_done(slug: str) -> set[str]:
    p = _done_path(slug)
    if not p.exists():
        return set()
    return {l.strip() for l in p.read_text(encoding="utf-8").splitlines() if l.strip()}


def mark_done(slug: str, query: str) -> None:
    with _done_path(slug).open("a", encoding="utf-8") as f:
        f.write(query + "\n")


def _reg_domain(host: str) -> str:
    host = (host or "").lower().lstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


# ─── Lead picking ───────────────────────────────────────────────────────────

def best_lead_for_site(website: str, leads: list[ScrapedLead]) -> ScrapedLead | None:
    """Prefer an email on the business's OWN domain, non-junk local-part. Fall
    back to any non-free, non-junk email found on the page."""
    site_dom = _reg_domain(urlparse(website).netloc)

    def local(e: str) -> str:
        return e.split("@", 1)[0].lower()

    def dom(e: str) -> str:
        return _reg_domain(e.split("@", 1)[1]) if "@" in e else ""

    candidates = [l for l in leads if l.email and "@" in l.email
                  and local(l.email) not in JUNK_LOCAL_PARTS]
    # Same registrable domain as the business website ONLY. A local business's
    # contact email is virtually always @theirdomain; accepting any other
    # business domain found on the page lets through third-party/spam addresses
    # (a vendor widget, a stray mailto), e.g. lemonad@jovanny.ru on a realtor site.
    same = [l for l in candidates if site_dom and dom(l.email) == site_dom]
    return _prefer_named(same) if same else None


def _prefer_named(leads: list[ScrapedLead]) -> ScrapedLead:
    """Among equally-valid leads, prefer one that already has a human name."""
    named = [l for l in leads if l.first_name]
    return named[0] if named else leads[0]


# ─── Run ────────────────────────────────────────────────────────────────────

def run(niche_slug: str, *, dry: bool = False, smtp: bool = False,
        limit: int | None = None, max_per_query: int | None = None) -> int:
    niche = load_niche(niche_slug)
    places_cfg = niche.get("places") or {}
    if not places_cfg:
        print(f"! niche '{niche_slug}' has no `places:` block. Nothing to do.")
        return 1
    profile_slug = niche.get("profile_slug") or niche_slug
    # Let the places block override require_first_name (some brands enroll only
    # named contacts, e.g. f2/atal which also require a city), falling back to the
    # niche-level flag then False.
    require_name = bool(places_cfg.get("require_first_name",
                                       niche.get("require_first_name", False)))
    country = places_cfg.get("country") or "us"
    mpq = max_per_query or int(places_cfg.get("max_per_query", 20))
    contact_paths = places_cfg.get("contact_paths") or DEFAULT_CONTACT_PATHS
    filt = niche.get("filter") or {}
    exclude_locals = {x.lower() for x in (filt.get("exclude_locals") or [])}
    exclude_domains = {x.lower() for x in (filt.get("exclude_domains") or [])}

    api_key = serper_key()
    if not api_key:
        print("! no SERPER_API_KEY in env or search.env"); return 1

    queries = build_queries(places_cfg)
    done = load_done(niche_slug)
    pending = [(q, c) for (q, c) in queries if q not in done]
    if not pending:  # wrap the cursor
        print(f"  all {len(queries)} place-queries walked; wrapping cursor.")
        _done_path(niche_slug).unlink(missing_ok=True)
        pending = queries

    url = key = None
    if not dry:
        url, key = load_supabase()

    summary = {"queries": 0, "places": 0, "candidates": 0,
               "verified": 0, "rejected": 0, "upserted": 0, "skipped": 0}
    seen_domains: set[str] = set()
    t0 = time.monotonic()
    enrolled = 0

    print(f"places-scrape '{niche_slug}' (profile={profile_slug}) "
          f"{len(pending)} pending queries, max {mpq}/query"
          f"{' [DRY]' if dry else ''}{' [MX-only]' if not smtp else ''}")

    for query, city in pending:
        if time.monotonic() - t0 > TIME_BUDGET_SEC:
            print("  time budget hit; stopping (cursor preserved)."); break
        if limit and enrolled >= limit:
            print(f"  reached --limit {limit}; stopping."); break
        try:
            places = serper_places(query, country, api_key, num=mpq)
        except Exception as e:
            print(f"  ! serper places failed for '{query}': {e}"); continue
        summary["queries"] += 1
        print(f"\n  [{query}] -> {len(places)} places")

        for pl in places[:mpq]:
            if limit and enrolled >= limit:
                break
            summary["places"] += 1
            website = (pl.get("website") or "").strip()
            if not website or not website.startswith("http"):
                continue
            dom = _reg_domain(urlparse(website).netloc)
            if not dom or dom in seen_domains or dom in exclude_domains:
                continue
            seen_domains.add(dom)
            title = (pl.get("title") or "").strip()
            place_city = city or _city_from_address(pl.get("address") or "")

            # Visit home + contact pages until we find the business's own email.
            leads: list[ScrapedLead] = []
            for path in contact_paths:
                target = urljoin(website if website.endswith("/") else website + "/", path)
                html = fetch_html(target)
                if not html:
                    continue
                leads += extract_leads_from_page(target, html)
                if any(_reg_domain(l.email.split("@", 1)[1]) == dom
                       for l in leads if "@" in (l.email or "")):
                    break  # found an on-domain email; stop crawling this site

            lead = best_lead_for_site(website, leads)
            if not lead:
                continue
            if lead.email.split("@", 1)[0].lower() in exclude_locals:
                continue
            summary["candidates"] += 1

            # Places gives us the authoritative company + city. Trust them.
            lead.company = title or lead.company or derive_company(lead.email)
            lead.city = lead.city or place_city
            lead.website = website
            lead.source_url = website
            if not lead.first_name:
                lead.first_name = derive_first_name(lead.email, lead.company)
            if (require_name and not lead.first_name) or not lead.company:
                summary["skipped"] += 1
                continue

            v = verify(lead.email, do_smtp_probe=smtp, do_catchall_probe=smtp)
            tag = "OK " if v.verified else "BAD"
            print(f"     [{tag}] {v.method:14} {lead.email:42} "
                  f"{(lead.company or '')[:28]:28} {(lead.city or '')[:16]}")
            if v.verified:
                summary["verified"] += 1
            else:
                summary["rejected"] += 1
                continue
            if dry:
                enrolled += 1
                continue
            try:
                supa_upsert_prospect(url, key, profile_slug, lead, v, niche_slug)
                summary["upserted"] += 1
                enrolled += 1
            except Exception as e:
                print(f"     ! upsert failed: {e}")

        if not (limit and enrolled >= limit) and time.monotonic() - t0 <= TIME_BUDGET_SEC:
            mark_done(niche_slug, query)

    print("\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k:12} {v}")
    return 0


def _city_from_address(addr: str) -> str | None:
    """Best-effort city from a Serper place address like
    '123 Main St, Austin, TX 78701'."""
    parts = [p.strip() for p in addr.split(",") if p.strip()]
    if len(parts) >= 2:
        return parts[-2] if re.search(r"\b[A-Z]{2}\b|\d", parts[-1]) else parts[-1]
    return None


def list_niches() -> None:
    for p in sorted(NICHES_DIR.glob("*.yaml")):
        try:
            import yaml
            d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if d.get("places"):
            pc = d["places"]
            n = len(build_queries(pc))
            print(f"  {p.stem:28} {n} place-queries  (profile={d.get('profile_slug')})")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("niche")
    r.add_argument("--dry", action="store_true")
    r.add_argument("--smtp", action="store_true", help="SMTP RCPT probe (port 25; usually blocked, MX-only by default)")
    r.add_argument("--limit", type=int, default=None)
    r.add_argument("--max-per-query", type=int, default=None)
    p = sub.add_parser("probe")
    p.add_argument("query")
    sub.add_parser("list")
    args = ap.parse_args()

    if args.cmd == "list":
        list_niches(); return 0
    if args.cmd == "probe":
        key = serper_key()
        if not key:
            print("! no SERPER_API_KEY"); return 1
        for pl in serper_places(args.query, "us", key):
            print(f"  {pl.get('title','?')[:40]:40} {pl.get('website','(no site)')}")
        return 0
    return run(args.niche, dry=args.dry, smtp=args.smtp,
               limit=args.limit, max_per_query=args.max_per_query)


if __name__ == "__main__":
    raise SystemExit(main())
