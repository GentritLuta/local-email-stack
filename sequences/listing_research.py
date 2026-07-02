# -*- coding: utf-8 -*-
"""listing_research.py — free, per-prospect listing research for LK Advertising.

LK's prospects are US real estate agents. To make the give-first offer (a content
plan) personal, this finds ONE of the agent's REAL active listings and stores it
so listing_copy can name it in the opener and build a plan around it.

For each prospect with a company and a city/state it:
  1. tries the agent's OWN website first (highest confidence it is really theirs),
  2. then a KEYLESS SERP for "{company} {city} homes for sale" scoped to the big
     listing portals (zillow/realtor/redfin/...),
  3. extracts a real street address (and price/type when the title gives them),
  4. writes it to prospects.enriched_context.listing (merged, never trampling
     other enrichment).

Precision over recall, exactly like seo_research: we only set status "ok" when we
pin a real street address. Otherwise we store a non-ok status and listing_copy
falls back to a generic (still give-first) content-plan offer. Nothing here ever
claims a listing we did not actually see. The scraped url is stored so the
operator can eyeball it.

All plumbing (keyless SERP, domain helpers, Supabase env) is imported from
seo_research so this stays a thin, self-contained scheduled job.

CLI:
    py sequences/listing_research.py once --slug lk-advertising
    py sequences/listing_research.py once --slug lk-advertising --dry
    py sequences/listing_research.py once --slug lk-advertising --email X
    py sequences/listing_research.py once --slug lk-advertising --force
    py sequences/listing_research.py once --slug lk-advertising --limit 25

Schedule (mirrors LES-seo-research):
    schtasks /Create /TN "LES-listing-research" /SC MINUTE /MO 60 ^
      /TR "py C:\\Users\\bernh\\local-email-stack\\sequences\\listing_research.py once --slug lk-advertising --limit 25"
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seo_research as sr  # reuse serp/reg_domain/own_domain_of/geo_of/fetch_title/load_supabase

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Big listing portals. A result on one of these whose title carries a street
# address is a real property page (not this agent's site, but a real listing).
LISTING_PORTALS = {
    "zillow.com", "realtor.com", "redfin.com", "trulia.com", "homes.com",
    "compass.com", "movoto.com", "coldwellbankerhomes.com", "century21.com",
    "remax.com", "kw.com", "sothebysrealty.com", "har.com", "onehome.com",
    "point2homes.com", "landwatch.com", "homefinder.com",
}

# US street-address core: a number, some words, then a street-type suffix.
_STREET = (r"\d{1,6}\s+[A-Za-z0-9.'\- ]{2,40}?\s"
           r"(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Blvd|Boulevard|"
           r"Ct|Court|Way|Pl|Place|Ter|Terrace|Cir|Circle|Hwy|Highway|Pkwy|"
           r"Parkway|Trl|Trail|Loop|Cove|Cv|Run|Pass|Bend|Bnd|Sq|Square|Row|Walk)\b")
_ADDR_RE = re.compile(_STREET, re.I)
# Optional ", City, ST" tail right after the street.
_TAIL_RE = re.compile(r"^\s*,?\s*([A-Za-z .'\-]{2,30}),?\s+([A-Z]{2})\b")
_PRICE_RE = re.compile(r"\$\s?\d{2,3}(?:,\d{3})+")
_BEDS_RE = re.compile(r"(\d+)\s*(?:bed|beds|bd|br)\b", re.I)
_TYPE_RE = re.compile(r"single[\s-]?family|town\s?house|townhome|condo|duplex|"
                      r"multi[\s-]?family|ranch|bungalow|cottage|land|lot", re.I)


def extract_address(text: str) -> str:
    """Return a clean short address from a title/snippet, or '' if none. Includes
    the ', City, ST' tail when it directly follows the street."""
    if not text:
        return ""
    # Strip a leading "5 Bedroom House" / "3 Bed 2 Bath" descriptor so it does not
    # get swallowed into the address (the bed count reads as a fake house number).
    text = re.sub(r"^\s*(?:\d+\s*(?:bed(?:room)?s?|bath(?:room)?s?|br|ba)\b[^0-9]*)+",
                  "", text, flags=re.I)
    # Portals lead the title with the address; cut trailing site/MLS parts.
    head = re.split(r"\s*[|•]\s*|\s{2,}", text)[0]
    m = _ADDR_RE.search(head) or _ADDR_RE.search(text)
    if not m:
        return ""
    start = m.start()
    end = m.end()
    addr = text[start:end].strip(" ,")
    tail = _TAIL_RE.match(text[end:])
    if tail:
        addr = f"{addr}, {tail.group(1).strip()}, {tail.group(2)}"
    # sanity: must start with a digit and be a reasonable length
    if not addr[:1].isdigit() or not (6 <= len(addr) <= 80):
        return ""
    return addr


def _desc_from(text: str) -> str:
    beds = _BEDS_RE.search(text or "")
    typ = _TYPE_RE.search(text or "")
    parts = []
    if beds:
        parts.append(f"{beds.group(1)} bed")
    if typ:
        parts.append(re.sub(r"\s+", " ", typ.group(0).lower()).replace("family", "family"))
    return " ".join(parts).strip()


def _price_from(text: str) -> str:
    m = _PRICE_RE.search(text or "")
    return m.group(0).replace(" ", "") if m else ""


# A homepage address is only a LISTING if listing signals sit right next to it.
# Without this guard we would grab the brokerage's OFFICE address (same for every
# agent at the firm) and claim it is the prospect's listing. Precision over recall.
_LISTING_SIGNALS = ("for sale", "just listed", "new listing", "open house", "mls",
                    "listed at", "offered at", "bed", "bath", " bd", " ba", "sq ft",
                    "sqft", "$")
_OFFICE_SIGNALS = ("office", "suite", "ste ", "headquarter", "contact us",
                   "located at", "mailing", "po box", "our address", "visit us",
                   "hours:", "get directions")


def _listing_from_own_site(prospect: dict, own: str) -> dict | None:
    """Fetch the agent's homepage and return a featured LISTING address, but only
    when listing signals (price/beds/for sale/MLS) sit next to it and office
    signals do not. Otherwise return None (we would rather send the generic offer
    than call the firm's office address the prospect's listing)."""
    site = (prospect.get("website") or own or "").strip()
    if not site:
        return None
    url = site if "://" in site else "https://" + site
    try:
        r = httpx.get(url, headers=sr._KW_HDRS, timeout=12, follow_redirects=True)
        if r.status_code != 200:
            return None
    except Exception:
        return None
    text = sr._strip(r.text[:150000])
    for m in _ADDR_RE.finditer(text):
        window = text[max(0, m.start() - 140): m.end() + 200]
        low = window.lower()
        if any(o in low for o in _OFFICE_SIGNALS):
            continue                       # office / contact block, not a listing
        if not any(s in low for s in _LISTING_SIGNALS):
            continue                       # a bare address with no listing context
        addr = extract_address(window)
        if not addr:
            continue
        return {"address": addr, "listing_desc": _desc_from(window),
                "price": _price_from(window), "source": own, "url": url}
    return None


def _listing_from_portals(prospect: dict, geo: str) -> dict | None:
    """SERP the agent + city on the portals; take the first result whose title is
    a real property page with a street address."""
    company = (prospect.get("company") or "").strip()
    city = (prospect.get("city") or geo).strip()
    queries = [f'{company} {city} homes for sale', f'{company} {city} listings']
    for q in queries:
        results, engine = sr.serp(q, num=10)
        for res in results:
            dmn = sr.reg_domain(res.get("link", ""))
            if dmn not in LISTING_PORTALS:
                continue
            title = res.get("title", "")
            addr = extract_address(title)
            if addr:
                return {"address": addr, "listing_desc": _desc_from(title),
                        "price": _price_from(title), "source": dmn,
                        "url": res.get("link", ""), "engine": engine, "query": q}
        time.sleep(0.6)
    return None


def research_one(prospect: dict) -> dict:
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    base = {"researched_at": now}
    company = (prospect.get("company") or "").strip()
    geo = sr.geo_of(prospect)          # "" when city/state are missing
    own = sr.own_domain_of(prospect)   # from website or email domain
    if not own and not company:
        return {**base, "status": "no_inputs"}

    # The agent's own site works with no geo (if it is on their site, it is theirs);
    # the portal search needs a city to be specific enough to trust.
    hit = None
    if own:
        hit = _listing_from_own_site(prospect, own)
    if not hit and company and geo:
        hit = _listing_from_portals(prospect, geo)
    if not hit or not hit.get("address"):
        st = "thin_data" if (own or (company and geo)) else "no_geo"
        return {**base, "status": st, "city": prospect.get("city") or geo}

    return {
        **base,
        "status": "ok",
        "address": hit["address"],
        "listing_desc": hit.get("listing_desc", ""),
        "price": hit.get("price", ""),
        "source": hit.get("source", ""),
        "url": hit.get("url", ""),
        "city": (prospect.get("city") or geo),
        "queries": [hit["query"]] if hit.get("query") else [],
        "engine": hit.get("engine", "own_site"),
    }


def _eligible(prospect: dict, refresh_after: dt.datetime, force: bool) -> tuple[bool, str]:
    lst = (prospect.get("enriched_context") or {}).get("listing")
    if force or not isinstance(lst, dict) or not lst.get("researched_at"):
        return True, "fresh"
    try:
        when = dt.datetime.fromisoformat(str(lst["researched_at"]).replace("Z", "+00:00"))
        return (when < refresh_after), ("stale" if when < refresh_after else "fresh enough")
    except Exception:
        return True, "unparseable timestamp"


def run_once(slug: str, email: str | None, force: bool, limit: int,
             refresh_days: int, dry: bool, sleep_between: float = 1.5) -> int:
    url, key = sr.load_supabase()
    refresh_after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=refresh_days)

    with httpx.Client(base_url=f"{url}/rest/v1",
                      headers={"apikey": key, "Authorization": f"Bearer {key}",
                               "Content-Type": "application/json",
                               "Prefer": "return=representation"},
                      timeout=40) as c:
        q = ("/prospects?select=id,email,company,city,state,website,"
             "enriched_context,unsubscribed&order=created_at.desc")
        if slug:
            q += f"&profile_slug=eq.{slug}"
        if email:
            q += f"&email=eq.{email}"
        r = c.get(q)
        r.raise_for_status()
        prospects = r.json()

        examined = ok = skipped = nonok = failed = 0
        for p in prospects[:limit]:
            examined += 1
            if p.get("unsubscribed"):
                skipped += 1
                continue
            elig, why = _eligible(p, refresh_after, force)
            if not elig:
                print(f"  - {(p.get('email') or '')[:40]:40} skip: {why}")
                skipped += 1
                continue

            lst = research_one(p)
            tag = lst["status"]
            if tag == "ok":
                print(f"  > {(p.get('email') or '')[:40]:40} OK  [{lst['address']}] "
                      f"({lst.get('source') or '?'}, {lst.get('engine') or '?'})")
                ok += 1
            else:
                print(f"  > {(p.get('email') or '')[:40]:40} {tag}")
                nonok += 1

            if dry:
                continue

            merged = dict(p.get("enriched_context") or {})
            merged["listing"] = lst
            up = c.patch(f"/prospects?id=eq.{p['id']}", json={"enriched_context": merged})
            if up.status_code not in (200, 204):
                print(f"    ! patch {up.status_code}: {up.text[:200]}")
                failed += 1
                continue
            time.sleep(sleep_between)

        print(f"\n=== listing_research === examined={examined} ok={ok} "
              f"other={nonok} skipped={skipped} failed={failed}"
              f"{' [DRY]' if dry else ''}")
        return 0 if (ok > 0 or nonok > 0 or failed == 0) else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("once")
    p.add_argument("--slug", default="lk-advertising", help="profile_slug to scan")
    p.add_argument("--email", default=None, help="only one prospect by email")
    p.add_argument("--force", action="store_true", help="re-research even if already done")
    p.add_argument("--limit", type=int, default=50, help="max prospects per tick")
    p.add_argument("--refresh-days", type=int, default=30,
                   help="re-research rows whose listing.researched_at is older than N days")
    p.add_argument("--dry", action="store_true", help="show what it would do, no DB write")
    a = ap.parse_args()
    if a.cmd == "once":
        return run_once(a.slug, a.email, a.force, a.limit, a.refresh_days, a.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
