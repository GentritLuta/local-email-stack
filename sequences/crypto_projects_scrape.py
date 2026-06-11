"""crypto_projects_scrape.py — scrape emails from crypto project team pages.

Two free sources:
  - DefiLlama: api.llama.fi/protocols (no key, 3000+ DeFi protocols with `url`)
  - CoinMarketCap: pro-api.coinmarketcap.com (free key, 333 calls/day, 5000+ tokens)

For each project we get a homepage URL. We then crawl the homepage + likely
contact/about/team pages with the same playwright+regex extractor used by
lead_scrape, and upsert verified emails into prospects with the same
profile_slug isolation guarantee.

CLI:
    py crypto_projects_scrape.py defillama <niche> [--limit N] [--offset M]
    py crypto_projects_scrape.py cmc       <niche> [--limit N] [--page P]

The DefiLlama path is fully free and runs without any signup. CMC requires
free API key in `cmc.env` (CMC_API_KEY=...).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lead_verify import verify, GENERIC_LOCAL_PARTS  # noqa: E402
from lead_scrape import (  # noqa: E402
    ScrapedLead, load_supabase, supa_upsert_prospect, load_niche,
    fetch_html, fetch_html_playwright, extract_leads_from_page,
    start_playwright_pool, stop_playwright_pool,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CMC_ENV   = REPO_ROOT / "sequences" / "cmc.env"

DEFILLAMA_PROTOCOLS_URL = "https://api.llama.fi/protocols"
CMC_LISTING_URL = "https://pro-api.coinmarketcap.com/v1/cryptocurrency/listings/latest"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/121.0 Safari/537.36")

# Pages most likely to expose actual people-emails. The homepage footer is
# almost always role mailboxes (contact@/support@) which we filter out, so
# we skip "" and prioritize team/about pages. Order matters: stop as soon
# as one returns a verified individual email.
CONTACT_PATHS = ["/team", "/about", "/about-us", "/contact", ""]

# Per-page timeouts. Aggressive because at 5k+ project scale we can't wait
# minutes per protocol. Fail fast and move on — slow sites have <2% yield anyway.
STATIC_TIMEOUT_SEC     = 8
PLAYWRIGHT_TIMEOUT_SEC = 12

# Patterns that mark an "email" as actually a tracker/monitoring artifact
# (Sentry DSN, Datadog ingest, AWS internal, etc.) rather than a real contact.
JUNK_DOMAIN_SUBSTRINGS = ("sentry.", "datadoghq", "newrelic", "rollbar",
                          "bugsnag", "ingest.", "amazonaws.com",
                          "googleusercontent", "cloudfront.net",
                          "supabase.co", "wixsite", "pages.dev",
                          "vercel.app", "netlify.app", "herokuapp.com",
                          "googleapis.com",
                          # SDK / docs placeholder domains
                          "example.com", "example.org", "example.net",
                          "test.com", "domain.com", "yourdomain.com",
                          "email.com", "yourcompany.com", "company.com",
                          "yoursite.com", "mysite.com")
# Standard placeholder local-parts SDK/docs use
JUNK_LOCAL_PARTS = {
    "user", "email", "test", "foo", "bar", "baz", "demo", "example",
    "yourname", "yourname", "name", "firstname", "lastname",
    "john", "johndoe", "john.doe", "johnappleseed", "appleseed",
    "jane", "janedoe", "jane.doe", "alice", "bob", "charlie",
    "noreply", "no-reply", "donotreply", "do-not-reply",
}
HEX_LOCAL_RX = re.compile(r"^[a-f0-9]{24,}$")
# When the regex catches "loader@0.1.15.js" the "TLD" is a file extension.
# Real TLDs are never these.
FILE_TLDS = {"js","css","png","jpg","jpeg","gif","svg","webp","ico",
             "html","htm","json","xml","map","mp4","webm","woff","woff2"}

def _is_junk_email(email: str) -> bool:
    local, _, domain = email.lower().partition("@")
    if not domain:
        return True
    if any(s in domain for s in JUNK_DOMAIN_SUBSTRINGS):
        return True
    if local in JUNK_LOCAL_PARTS:
        return True
    if HEX_LOCAL_RX.match(local):
        return True
    # "loader@0.1.15.js" pattern — domain looks like a path with file ext
    last = domain.rsplit(".", 1)[-1]
    if last in FILE_TLDS:
        return True
    if re.match(r"^\d", domain):  # domain starting with a digit is rarely real
        # but allow some legitimate ones (1inch.io, 0x.org)
        if not re.match(r"^[01-9](?:inch|x)\.", domain):
            return True
    # Random-looking local-parts longer than 30 chars are almost never real
    if len(local) > 30 and not re.search(r"[._\-]", local):
        return True
    return False


def load_cmc_key() -> Optional[str]:
    if not CMC_ENV.exists():
        return None
    for line in CMC_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("CMC_API_KEY="):
            k = line.split("=", 1)[1].strip().strip('"').strip("'")
            return k or None
    return None


def _domain_root(url: str) -> Optional[str]:
    try:
        p = urlparse(url if "://" in url else "https://" + url)
        if not p.netloc:
            return None
        return f"{p.scheme}://{p.netloc}"
    except Exception:
        return None


def fetch_defillama_protocols() -> list[dict]:
    """Returns [{name, url, category, twitter, ...}, ...] — no API key needed."""
    with httpx.Client(timeout=30, headers={"User-Agent": USER_AGENT}) as c:
        r = c.get(DEFILLAMA_PROTOCOLS_URL)
        r.raise_for_status()
        return r.json()


def fetch_cmc_listings(api_key: str, start: int = 1, limit: int = 500) -> list[dict]:
    with httpx.Client(timeout=30, headers={
            "User-Agent": USER_AGENT,
            "X-CMC_PRO_API_KEY": api_key,
            "Accept": "application/json"}) as c:
        r = c.get(CMC_LISTING_URL, params={"start": start, "limit": limit})
        r.raise_for_status()
        data = r.json().get("data") or []
        # We need each token's URLs — comes from /cryptocurrency/info, not listings
        # but listings gives us the IDs cheaply. Caller can hydrate later.
        return data


def fetch_cmc_metadata(api_key: str, ids: list[int]) -> dict[int, dict]:
    """Returns {id: {name, urls: {website, ...}, ...}} for up to 100 ids."""
    if not ids:
        return {}
    url = "https://pro-api.coinmarketcap.com/v2/cryptocurrency/info"
    with httpx.Client(timeout=30, headers={
            "User-Agent": USER_AGENT,
            "X-CMC_PRO_API_KEY": api_key,
            "Accept": "application/json"}) as c:
        r = c.get(url, params={"id": ",".join(str(i) for i in ids[:100])})
        if r.status_code != 200:
            print(f"   ! cmc info {r.status_code}: {r.text[:200]}")
            return {}
        return {int(k): v for k, v in (r.json().get("data") or {}).items()}


def _try_pages(root: str, max_pages: int = 3) -> list[tuple[str, str]]:
    """Fetch up to `max_pages` candidate pages under `root`. Returns list of
    (url, html) for ones that returned content with at least one email
    marker. Stops as soon as we have enough; never spends >~25s/site total."""
    pairs: list[tuple[str, str]] = []
    seen_urls: set[str] = set()
    for path in CONTACT_PATHS:
        if len(pairs) >= max_pages:
            break
        url = root.rstrip("/") + path
        if url in seen_urls:
            continue
        seen_urls.add(url)
        html = fetch_html(url, timeout=STATIC_TIMEOUT_SEC)
        if html and re.search(r"@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", html):
            pairs.append((url, html))
            continue
        # Static found nothing — try playwright ONLY for /about, /team
        # (other paths are too low-yield to spend 12s on)
        if path in ("/about", "/team", "/about-us"):
            pw_html = fetch_html_playwright(url, timeout=PLAYWRIGHT_TIMEOUT_SEC)
            if pw_html and re.search(r"@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", pw_html):
                pairs.append((url, pw_html))
    return pairs


def _scrape_project(name: str, website: str, profile_slug: str,
                    niche_slug: str, exclude_locals: set[str],
                    exclude_domains: set[str], supa: tuple[str, str],
                    smtp: bool, dry: bool, summary: dict) -> None:
    root = _domain_root(website)
    if not root:
        return
    pairs = _try_pages(root)
    if not pairs:
        return
    summary["sites_fetched"] += 1
    emails_seen: set[str] = set()
    for page_url, html in pairs:
        leads = extract_leads_from_page(page_url, html)
        for lead in leads:
            if lead.email in emails_seen:
                continue
            emails_seen.add(lead.email)
            if _is_junk_email(lead.email):
                summary["skipped_generic"] += 1
                continue
            local, _, domain = lead.email.partition("@")
            if local in exclude_locals or domain in exclude_domains:
                summary["skipped_generic"] += 1
                continue
            v = verify(lead.email, do_smtp_probe=smtp, do_catchall_probe=smtp)
            tag = "OK " if v.verified else "BAD"
            print(f"     [{tag}] {v.method:16} {lead.email:40}  ({name[:30]})")
            if v.verified:
                summary["verified"] += 1
            else:
                summary["rejected"] += 1
                continue
            if not lead.company:
                lead.company = name
            if not lead.website:
                lead.website = root
            if dry:
                continue
            try:
                supa_upsert_prospect(supa[0], supa[1], profile_slug, lead, v, niche_slug)
                summary["upserted"] += 1
            except Exception as e:
                print(f"     ! upsert failed: {e}")


def run_defillama(niche_slug: str, *, limit: int, offset: int,
                  dry: bool, smtp: bool) -> int:
    niche = load_niche(niche_slug)
    profile_slug = niche.get("profile_slug") or "aureon"
    exclude_locals = set(niche.get("filter", {}).get("exclude_local_parts", [])) | GENERIC_LOCAL_PARTS
    exclude_domains = set(niche.get("filter", {}).get("exclude_domains", []))
    supa = ("", "") if dry else load_supabase()

    print(f"=== defillama -> {niche_slug} ===")
    print(f"  profile_slug = {profile_slug}")
    print(f"  smtp probe   = {smtp}")
    print(f"  dry          = {dry}\n")

    protocols = fetch_defillama_protocols()
    print(f"got {len(protocols)} protocols from DefiLlama")
    protocols = [p for p in protocols if p.get("url")]
    print(f"  with website: {len(protocols)}")

    sub = protocols[offset:offset + limit] if limit else protocols[offset:]
    print(f"processing {len(sub)} (offset={offset}, limit={limit or 'all'})\n")

    summary = {"protocols": 0, "sites_fetched": 0, "verified": 0,
               "rejected": 0, "skipped_generic": 0, "upserted": 0}

    start_playwright_pool()
    try:
        for proto in sub:
            summary["protocols"] += 1
            name = proto.get("name") or "?"
            url = proto.get("url") or ""
            print(f"-- {name[:40]:40} {url[:60]}", flush=True)
            _scrape_project(name, url, profile_slug, niche_slug,
                            exclude_locals, exclude_domains, supa,
                            smtp, dry, summary)
    finally:
        stop_playwright_pool()

    print("\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k:18} {v}")
    return 0


def run_cmc(niche_slug: str, *, limit: int, page: int, dry: bool, smtp: bool) -> int:
    api_key = load_cmc_key()
    if not api_key:
        sys.exit(f"missing CMC_API_KEY in {CMC_ENV}\n"
                 f"  get a free key at https://coinmarketcap.com/api/")
    niche = load_niche(niche_slug)
    profile_slug = niche.get("profile_slug") or "aureon"
    exclude_locals = set(niche.get("filter", {}).get("exclude_local_parts", [])) | GENERIC_LOCAL_PARTS
    exclude_domains = set(niche.get("filter", {}).get("exclude_domains", []))
    supa = ("", "") if dry else load_supabase()

    start = 1 + (page - 1) * limit
    print(f"=== cmc -> {niche_slug}  start={start} limit={limit} ===\n")

    listings = fetch_cmc_listings(api_key, start=start, limit=limit)
    print(f"got {len(listings)} CMC tokens")
    ids = [int(c["id"]) for c in listings if c.get("id")]

    meta: dict[int, dict] = {}
    for i in range(0, len(ids), 100):
        meta.update(fetch_cmc_metadata(api_key, ids[i:i+100]))
        time.sleep(1)  # polite

    summary = {"tokens": 0, "with_website": 0, "sites_fetched": 0,
               "verified": 0, "rejected": 0, "skipped_generic": 0, "upserted": 0}

    for cid in ids:
        summary["tokens"] += 1
        m = meta.get(cid)
        if not m:
            continue
        websites = (m.get("urls") or {}).get("website") or []
        if not websites:
            continue
        summary["with_website"] += 1
        name = m.get("name") or "?"
        website = websites[0]
        print(f"-- {name[:40]:40} {website[:60]}")
        _scrape_project(name, website, profile_slug, niche_slug,
                        exclude_locals, exclude_domains, supa,
                        smtp, dry, summary)

    print("\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k:18} {v}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_dl = sub.add_parser("defillama")
    p_dl.add_argument("niche_slug")
    p_dl.add_argument("--limit", type=int, default=0,
                      help="max projects to process this run (0 = all)")
    p_dl.add_argument("--offset", type=int, default=0,
                      help="skip the first N projects (use for resuming)")
    p_dl.add_argument("--dry", action="store_true")
    p_dl.add_argument("--no-smtp", action="store_true")

    p_cm = sub.add_parser("cmc")
    p_cm.add_argument("niche_slug")
    p_cm.add_argument("--limit", type=int, default=200)
    p_cm.add_argument("--page", type=int, default=1)
    p_cm.add_argument("--dry", action="store_true")
    p_cm.add_argument("--no-smtp", action="store_true")

    args = ap.parse_args()
    if args.cmd == "defillama":
        return run_defillama(args.niche_slug, limit=args.limit, offset=args.offset,
                              dry=args.dry, smtp=not args.no_smtp)
    if args.cmd == "cmc":
        return run_cmc(args.niche_slug, limit=args.limit, page=args.page,
                       dry=args.dry, smtp=not args.no_smtp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
