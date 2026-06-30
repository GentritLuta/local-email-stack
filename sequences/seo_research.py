# -*- coding: utf-8 -*-
"""seo_research.py — free, per-prospect local-SEO research for mark-eting.

For each prospect with a company, a city/state, and a website, this:
  1. infers the trade (plumber, roofer, dentist, ...) from the company name and,
     if needed, the homepage,
  2. runs a KEYLESS Google-style search for "{trade} {city} {state}" via the
     same DDG -> Startpage -> Mojeek scrapers the rest of the stack uses,
  3. names the real businesses showing up ahead of the prospect, and notes
     whether the prospect's own site appears on page one,
  4. writes it all to prospects.enriched_context.seo (merged, never trampling
     other enrichment), so the cold opener (seo_ps) and the reply asset
     (seo_block) can use it.

This is the "Stage 2 + 3" of the lead-magnet playbook done for free: real proof
per prospect, no Ahrefs/Clay/paid SERP API. There is no free source of true
keyword search volume, so we never invent one; the money figure lives in
seo_copy.py and is always framed as an explicit, correct-me assumption.

Honesty guards:
  - We only make the "you do not show up" claim when we got a healthy result set
    and the prospect's own domain was genuinely absent from it.
  - If we cannot confidently infer the trade, or the search comes back thin, we
    store a non-ok status and the copy falls back to its generic, claim-free
    version. Nothing here ever asserts something we did not actually observe.

The SERP scrapers (_kw_ddg/_kw_startpage/_kw_mojeek/_strip) are vendored from
sequences/intent_signals.py to keep this scheduled job self-contained (importing
intent_signals would pull signal_pack_lib + intent_score for three pure helpers).

CLI:
    py sequences/seo_research.py once --slug mark-eting                 # scan eligible
    py sequences/seo_research.py once --slug mark-eting --dry           # show, no DB write
    py sequences/seo_research.py once --slug mark-eting --email X       # one prospect
    py sequences/seo_research.py once --slug mark-eting --force         # re-research all
    py sequences/seo_research.py once --slug mark-eting --limit 20

Schedule (mirrors LES-context-enrich):
    schtasks /Create /TN "LES-seo-research" /SC MINUTE /MO 60 ^
      /TR "py C:\\Users\\bernh\\local-email-stack\\sequences\\seo_research.py once --slug mark-eting --limit 25"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse, unquote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import seo_copy  # noqa: E402  (assumed_searches/value defaults live there)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / "sequences" / "supabase.env"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_KW_HDRS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml"}

FREE_MAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
    "aol.com", "proton.me", "protonmail.com", "web.de", "gmx.de", "gmx.com",
    "mail.com", "live.com", "msn.com", "yandex.com", "zoho.com",
}

# Aggregators / directories / platforms. These genuinely rank, but the playbook
# wants real local rivals named, so they are excluded from the competitor list.
# (They are still counted when locating the prospect's own organic position.)
DIRECTORY_DOMAINS = {
    "yelp.com", "angi.com", "angieslist.com", "thumbtack.com", "bbb.org",
    "homeadvisor.com", "mapquest.com", "yellowpages.com", "facebook.com",
    "instagram.com", "linkedin.com", "nextdoor.com", "reddit.com", "houzz.com",
    "expertise.com", "threebestrated.com", "birdeye.com", "manta.com",
    "chamberofcommerce.com", "indeed.com", "glassdoor.com", "wikipedia.org",
    "google.com", "bing.com", "justia.com", "avvo.com", "findlaw.com",
    "lawyers.com", "healthgrades.com", "zocdoc.com", "webmd.com", "ratemds.com",
    "vitals.com", "trustpilot.com", "porch.com", "buildzoom.com", "nicelocal.com",
    "tripadvisor.com", "foursquare.com", "superpages.com", "citysearch.com",
    "alignable.com", "clutch.co", "yellowbook.com", "local.com", "cylex.us.com",
    # national directories / lead-gen / media roundups seen in live testing
    "usnews.com", "opencare.com", "roofguides.com", "plumbersup.com",
    "networx.com", "modernize.com", "fixr.com", "homeguide.com", "fash.com",
    "qualitysmith.com", "1800dentist.com", "carecredit.com", "bobvila.com",
    "forbes.com", "nerdwallet.com", "consumeraffairs.com", "reddit.com",
    "datanyze.com", "wellness.com", "zippia.com", "yellow.place", "n49.com",
    "topratedlocal.com", "bark.com", "houzz.com", "pinterest.com", "tiktok.com",
    "youtube.com", "x.com", "twitter.com", "mapsconnect.apple.com",
}

# Trade -> the search term a buyer would actually type. First match wins, so list
# the more specific patterns before the generic ones.
TRADE_TERMS: list[tuple[str, str]] = [
    (r"personal injury|injury law|accident law", "personal injury attorney"),
    (r"\blaw\b|attorney|legal|\bllp\b|esq\b", "lawyer"),
    (r"orthodont", "orthodontist"),
    (r"dental|dentist", "dentist"),
    (r"dermatolog", "dermatologist"),
    (r"chiropract", "chiropractor"),
    (r"veterinar|animal hospital|\bvet\b", "veterinarian"),
    (r"med ?spa|medspa|aesthet|botox|filler", "med spa"),
    (r"plumb", "plumber"),
    (r"roof", "roofing contractor"),
    (r"hvac|heating|cooling|air ?condition|furnace", "hvac contractor"),
    (r"electric", "electrician"),
    (r"pest|extermin|termite", "pest control"),
    (r"landscap|lawn care|lawn & ?garden", "landscaper"),
    (r"\bhome remodel|remodeling|renovation|general contractor|construction", "general contractor"),
    (r"garage door", "garage door repair"),
    (r"flooring|hardwood floor|carpet", "flooring contractor"),
    (r"painting|painter", "painting contractor"),
    (r"clean(ing)?|maid|janitor", "cleaning service"),
    (r"insurance", "insurance agency"),
    (r"\bcpa\b|accounting|accountant|bookkeep|tax service", "accountant"),
    (r"\bhvac\b", "hvac contractor"),
    (r"locksmith", "locksmith"),
    (r"\bspa\b|salon|barber", "salon"),
    (r"real estate|realtor|realty", "real estate agent"),
    (r"\bpool\b", "pool service"),
    (r"\bsolar\b", "solar installer"),
    (r"\bdaycare|child care|preschool", "daycare"),
    (r"physical therapy|physiotherap", "physical therapist"),
    (r"\bdoctor|clinic|medical|physician|urgent care", "doctor"),
    (r"\bgym\b|fitness|personal train", "gym"),
    (r"auto repair|mechanic|body shop|collision", "auto repair shop"),
    (r"moving|movers", "moving company"),
    (r"pest|wildlife removal", "pest control"),
]


# ---- env / Supabase ---------------------------------------------------------

def load_supabase() -> tuple[str, str]:
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env["SUPABASE_URL"].rstrip("/"), env["SUPABASE_ANON_KEY"]


# ---- vendored keyless SERP scrapers (source: intent_signals.py) -------------

def _strip(s: str) -> str:
    s = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", s or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _kw_ddg(query: str, num: int) -> list[dict]:
    try:
        r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query},
                       headers=_KW_HDRS, timeout=20, follow_redirects=True)
        if r.status_code != 200:
            return []
    except Exception:
        return []
    titles = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                        r.text, re.S)
    out = []
    for href, title in titles:
        mm = re.search(r"uddg=([^&]+)", href)
        link = unquote(mm.group(1)) if mm else href
        if not link.startswith("http"):
            continue
        out.append({"title": _strip(title), "link": link})
    return out[:num]


def _kw_startpage(query: str, num: int) -> list[dict]:
    try:
        r = httpx.get("https://www.startpage.com/sp/search",
                      params={"query": query, "cat": "web"},
                      headers=_KW_HDRS, timeout=20, follow_redirects=True)
        if r.status_code != 200:
            return []
    except Exception:
        return []
    pairs = re.findall(
        r'<a[^>]+class="[^"]*result-(?:link|title)[^"]*"[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
        r.text, re.S)
    if not pairs:
        pairs = re.findall(
            r'<a[^>]+class="w-gl__result-(?:url|title)[^"]*"[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>',
            r.text, re.S)
    out, seen = [], set()
    for link, title in pairs:
        if link in seen:
            continue
        seen.add(link)
        out.append({"title": _strip(title), "link": link})
    return out[:num]


def _kw_mojeek(query: str, num: int) -> list[dict]:
    try:
        r = httpx.get("https://www.mojeek.com/search", params={"q": query},
                      headers=_KW_HDRS, timeout=20, follow_redirects=True)
        if r.status_code != 200:
            return []
    except Exception:
        return []
    out, seen = [], set()
    for link, title in re.findall(
            r'<a[^>]+class="ob"[^>]+href="(https?://[^"]+)"[^>]*>(.*?)</a>', r.text, re.S):
        if link in seen:
            continue
        seen.add(link)
        out.append({"title": _strip(title), "link": link})
    return out[:num]


def serp(query: str, num: int = 10) -> tuple[list[dict], str]:
    """Try the keyless engines in order; return (results, engine_used). Engines
    are flaky individually, so we fall through until one gives a usable set."""
    for name, fn in (("ddg", _kw_ddg), ("startpage", _kw_startpage), ("mojeek", _kw_mojeek)):
        try:
            res = fn(query, num)
        except Exception:
            res = []
        if len(res) >= 4:
            return res, name
        time.sleep(0.8)
    return [], ""


# ---- domain + trade helpers -------------------------------------------------

def reg_domain(host_or_url: str) -> str:
    """Best-effort registrable domain (last two labels, www stripped). US-focused,
    so multi-part TLDs like .co.uk are out of scope."""
    s = (host_or_url or "").strip().lower()
    if not s:
        return ""
    if "://" not in s:
        s = "https://" + s
    host = (urlparse(s).hostname or "").replace("www.", "")
    parts = host.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def own_domain_of(prospect: dict) -> str:
    site = (prospect.get("website") or "").strip()
    if site:
        d = reg_domain(site)
        if d and d not in FREE_MAIL_DOMAINS:
            return d
    email = (prospect.get("email") or "").lower()
    if "@" in email:
        d = email.split("@", 1)[1]
        if d and d not in FREE_MAIL_DOMAINS:
            return d
    return ""


def fetch_title(url: str) -> str:
    try:
        r = httpx.get(url if "://" in url else "https://" + url,
                      headers=_KW_HDRS, timeout=12, follow_redirects=True)
        if r.status_code != 200:
            return ""
    except Exception:
        return ""
    m = re.search(r"<title[^>]*>(.*?)</title>", r.text, re.S | re.I)
    head = r.text[:6000]
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", head, re.S | re.I)
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\']([^"\']+)', head, re.I)
    return " ".join(_strip(x.group(1)) for x in (m, h1, desc) if x)


def infer_trade(prospect: dict) -> str | None:
    """Pick the buyer search term for this prospect's trade. Try the company name
    first (cheap, no network), then the homepage. Return None if we cannot tell,
    so the copy stays generic rather than guessing wrong."""
    hay = (prospect.get("company") or "").lower()
    for pat, term in TRADE_TERMS:
        if re.search(pat, hay):
            return term
    site = own_domain_of(prospect)
    if site:
        extra = fetch_title(prospect.get("website") or site).lower()
        if extra:
            for pat, term in TRADE_TERMS:
                if re.search(pat, extra):
                    return term
    return None


def geo_of(prospect: dict) -> str:
    city = (prospect.get("city") or "").strip()
    state = (prospect.get("state") or "").strip()
    if city and state:
        return f"{city}, {state}"
    return city or state or ""


# Listicle / media / directory title markers. A result whose title leads with
# any of these is a "best X in Y" roundup or an aggregator, not the prospect's
# local rival, so we never name it as a competitor.
_NAME_BANNED = (
    "best ", " best", "top ", "top-", "near me", "near you", " reviews",
    "review", " in ", "cheap", "affordable", "list of", "directory", "find a",
    "compare", " vs ", "ratings", "rated", "guide", "guides", "expert", "near",
    "recommend", "trusted", "leading", "cost", "prices", "pricing", "how to",
    "things to", "questions",
)
_YEAR_RE = re.compile(r"\b20\d\d\b")


def extract_brand(title: str, trade: str, city: str) -> str | None:
    """A real business NAME from the result title, or None if the title is a
    listicle/media/generic descriptor. Returning None means we will NOT name this
    result as a competitor (precision over recall: better to fall back to generic
    copy than to call a newspaper or a directory the prospect's rival)."""
    first = re.split(r"\s*[|\-–—:•·]\s*", title or "", maxsplit=1)[0].strip()
    if not first or not (2 <= len(first) <= 40):
        return None
    low = first.lower()
    if first[0].isdigit() or _YEAR_RE.search(low):
        return None
    if any(b in low for b in _NAME_BANNED):
        return None
    # Reject generic descriptors like "Plumber Austin" / "Denver Dentist" that
    # are the search term, not a brand.
    trade_head = trade.lower().split()[0]
    if low.startswith(trade_head) or low.endswith(trade_head):
        return None
    if city and city.lower() in low and len(first.split()) <= 3:
        return None
    return first


def research_one(prospect: dict) -> dict:
    """Return the enriched_context.seo dict for this prospect (always has status
    + researched_at)."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    base = {"researched_at": now,
            "assumed_searches": seo_copy.ASSUMED_SEARCHES,
            "assumed_value_usd": seo_copy.ASSUMED_VALUE_USD}

    geo = geo_of(prospect)
    if not (prospect.get("company") or "").strip():
        return {**base, "status": "no_company"}
    if not geo:
        return {**base, "status": "no_geo"}
    own = own_domain_of(prospect)
    if not own:
        return {**base, "status": "no_site"}
    trade = infer_trade(prospect)
    if not trade:
        return {**base, "status": "unknown_service"}

    money_search = f"{trade} {geo}".strip()
    second = f"best {trade} {(prospect.get('city') or geo).strip()}".strip()
    results, engine = serp(money_search, num=10)
    if len(results) < 4:
        return {**base, "status": "no_results", "service": trade, "geo": geo,
                "money_search": money_search}

    competitors: list[dict] = []
    own_rank = None
    seen_domains: set[str] = set()
    city = (prospect.get("city") or "").strip()
    for i, r in enumerate(results, start=1):
        d = reg_domain(r.get("link", ""))
        if not d:
            continue
        if d == own:
            if own_rank is None:
                own_rank = i
            continue
        if d in DIRECTORY_DOMAINS or d in seen_domains:
            continue
        seen_domains.add(d)
        if len(competitors) >= 3:
            continue
        # Only name it when the title yields a real business brand. A generic or
        # listicle title means it is a directory/roundup, not a local rival.
        brand = extract_brand(r.get("title", ""), trade, city)
        if brand:
            competitors.append({"name": brand, "domain": d})

    if not competitors:
        return {**base, "status": "thin_data", "service": trade, "geo": geo,
                "money_search": money_search, "results_seen": len(results)}

    return {
        **base,
        "status": "ok",
        "service": trade,
        "geo": geo,
        "money_search": money_search,
        "queries": [money_search, second],
        "competitors": competitors,
        "own_domain": own,
        "own_rank": own_rank,
        "found_on_page1": own_rank is not None and own_rank <= 10,
        "results_seen": len(results),
        "engine": engine,
    }


# ---- eligibility + main loop ------------------------------------------------

def _eligible(prospect: dict, refresh_after: dt.datetime, force: bool) -> tuple[bool, str]:
    seo = (prospect.get("enriched_context") or {}).get("seo")
    if force or not isinstance(seo, dict) or not seo.get("researched_at"):
        return True, "fresh"
    try:
        when = dt.datetime.fromisoformat(str(seo["researched_at"]).replace("Z", "+00:00"))
        return (when < refresh_after), ("stale" if when < refresh_after else "fresh enough")
    except Exception:
        return True, "unparseable timestamp"


def run_once(slug: str | None, email: str | None, force: bool, limit: int,
             refresh_days: int, dry: bool, sleep_between: float = 1.5) -> int:
    url, key = load_supabase()
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

            seo = research_one(p)
            tag = seo["status"]
            if tag == "ok":
                comp = ", ".join(seo_copy.competitor_names(seo))
                rank = seo.get("own_rank")
                ranks = f"rank {rank}" if rank else "not on page 1"
                print(f"  > {(p.get('email') or '')[:40]:40} OK  [{seo['money_search']}] "
                      f"vs {comp} ({ranks}, {seo['engine']})")
                ok += 1
            else:
                print(f"  > {(p.get('email') or '')[:40]:40} {tag}")
                nonok += 1

            if dry:
                continue

            merged = dict(p.get("enriched_context") or {})
            merged["seo"] = seo
            up = c.patch(f"/prospects?id=eq.{p['id']}", json={"enriched_context": merged})
            if up.status_code not in (200, 204):
                print(f"    ! patch {up.status_code}: {up.text[:200]}")
                failed += 1
                continue
            time.sleep(sleep_between)

        print(f"\n=== seo_research === examined={examined} ok={ok} "
              f"other={nonok} skipped={skipped} failed={failed}"
              f"{' [DRY]' if dry else ''}")
        # Only flag the scheduled job on a systemic failure: attempts were made
        # and every DB write failed. Per-prospect non-ok statuses are normal.
        return 0 if (ok > 0 or nonok > 0 or failed == 0) else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("once")
    p.add_argument("--slug", default="mark-eting", help="profile_slug to scan")
    p.add_argument("--email", default=None, help="only one prospect by email")
    p.add_argument("--force", action="store_true", help="re-research even if already done")
    p.add_argument("--limit", type=int, default=50, help="max prospects per tick")
    p.add_argument("--refresh-days", type=int, default=21,
                   help="re-research rows whose seo.researched_at is older than N days")
    p.add_argument("--dry", action="store_true", help="show what it would do, no DB write")
    a = ap.parse_args()
    if a.cmd == "once":
        return run_once(a.slug, a.email, a.force, a.limit, a.refresh_days, a.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
