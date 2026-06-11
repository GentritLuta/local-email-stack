"""seed_discover.py — auto-discover new seed URLs for team-page niches.

Runs DuckDuckGo HTML search for each niche's `search_queries` (added in
the YAML), validates each result (HTTP 200 + contains a mailto: link),
and appends new seed URLs to the YAML under the existing `seeds:` list.

Daily flow:
  1. LES-seed-discover (09:00) runs this script -> grows niche YAMLs
  2. LES-lead-scrape-* (08:30 already, but tomorrow will catch new seeds
     on subsequent run after orchestrator's pass)
  3. LES-daily-fill-and-enroll (09:30) runs lead_scrape on the grown YAML
  4. New verified prospects appear, get enrolled

USAGE
    py sequences/seed_discover.py                     # all niches with queries
    py sequences/seed_discover.py --niche real_estate_us
    py sequences/seed_discover.py --max-per-query 5   # ddg result cap per query
    py sequences/seed_discover.py --dry               # find, validate, but do not write YAML

YAML extension (added per niche):
    search_queries:
      - "small real estate brokerage agents indianapolis"
      - "boutique real estate brokerage team page texas"
      ...
    discovery:
      max_seeds_per_run: 20      # safety cap
      require_mailto:    true    # validate that page actually has mailto:
      require_keywords:  ["agent","realtor","broker"]  # at least one must appear

Captcha-resistance: uses duckduckgo_search (HTML scrape, no captcha
required); falls back to playwright_stealth render only when the
target page hard-blocks httpx. Open-source path end to end.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx
import yaml
# `ddgs` is the maintained successor to `duckduckgo_search` and supports
# multi-engine fallback (DDG/Bing/Brave) under the hood.
from ddgs import DDGS

REPO = Path(__file__).resolve().parent.parent
NICHES = REPO / "niches"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")
HTTP_HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}

MAILTO_RX = re.compile(r"mailto:[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}", re.I)


def _load_niche(slug: str) -> tuple[Path, dict]:
    p = NICHES / f"{slug}.yaml"
    if not p.exists():
        sys.exit(f"niche not found: {p}")
    return p, yaml.safe_load(p.read_text(encoding="utf-8"))


def _existing_seed_urls(niche: dict) -> set[str]:
    out = set()
    for s in (niche.get("seeds") or []):
        if isinstance(s, str): out.add(s.rstrip("/"))
        elif isinstance(s, dict) and s.get("url"): out.add(s["url"].rstrip("/"))
    return out


def _is_valid_seed(url: str, require_mailto: bool,
                   require_keywords: list[str]) -> tuple[bool, str]:
    """Fetch url; check status + content signals. Use httpx first; fall
    back to a stealth playwright render for hard 403/captcha cases."""
    try:
        with httpx.Client(timeout=12, follow_redirects=True,
                          headers=HTTP_HEADERS) as c:
            r = c.get(url)
        if r.status_code >= 400:
            return _validate_via_stealth(url, require_mailto, require_keywords)
        html = r.text
    except Exception as e:
        return _validate_via_stealth(url, require_mailto, require_keywords)
    if require_mailto and not MAILTO_RX.search(html):
        return False, "no mailto on page"
    if require_keywords:
        low = html.lower()
        if not any(k.lower() in low for k in require_keywords):
            return False, "no niche keywords on page"
    return True, "ok"


# Module-level singletons so we don't spin up a new playwright/browser per
# URL. The per-URL launch path (now removed) was the source of EPIPE
# crashes when discovery had to validate >5 sites that failed httpx.
_PW_CTX = None  # (sync_playwright cm, browser, context) tuple once initialized
_STEALTH_DISABLED = False
_STEALTH_FAIL_LIMIT = 5  # after this many in-a-row stealth errors, give up
_stealth_consecutive_fails = 0


def _ensure_stealth_browser():
    """Lazy-launch playwright + Stealth context once. Returns the context
    object, or None if stealth is unavailable / disabled."""
    global _PW_CTX, _STEALTH_DISABLED
    if _STEALTH_DISABLED: return None
    if _PW_CTX is not None: return _PW_CTX[2]
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import Stealth
    except Exception:
        _STEALTH_DISABLED = True
        return None
    try:
        pw_cm = sync_playwright().start()
        browser = pw_cm.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="en-US")
        Stealth().apply_stealth_sync(ctx)
        _PW_CTX = (pw_cm, browser, ctx)
        return ctx
    except Exception as e:
        print(f"    ! stealth init failed: {str(e)[:100]}")
        _STEALTH_DISABLED = True
        return None


def _shutdown_stealth_browser() -> None:
    """Tear down the shared playwright context (call at end of run)."""
    global _PW_CTX
    if _PW_CTX is None: return
    pw_cm, browser, ctx = _PW_CTX
    try: browser.close()
    except Exception: pass
    try: pw_cm.stop()
    except Exception: pass
    _PW_CTX = None


def _validate_via_stealth(url: str, require_mailto: bool,
                          require_keywords: list[str]) -> tuple[bool, str]:
    """Stealth-render `url` and run the same content checks as the httpx
    path. Reuses one shared browser context across all calls in this run.
    Auto-disables itself after _STEALTH_FAIL_LIMIT consecutive failures
    so a wedged browser doesn't poison the whole pass."""
    global _stealth_consecutive_fails, _STEALTH_DISABLED
    ctx = _ensure_stealth_browser()
    if ctx is None:
        return False, "stealth unavailable"
    page = None
    try:
        page = ctx.new_page()
        page.set_default_timeout(15000)
        page.goto(url, wait_until="domcontentloaded")
        html = page.content()
        _stealth_consecutive_fails = 0
        if require_mailto and not MAILTO_RX.search(html):
            return False, "stealth: no mailto"
        if require_keywords and not any(k.lower() in html.lower()
                                        for k in require_keywords):
            return False, "stealth: no niche keywords"
        return True, "stealth_ok"
    except Exception as e:
        _stealth_consecutive_fails += 1
        if _stealth_consecutive_fails >= _STEALTH_FAIL_LIMIT:
            print(f"    ! stealth wedged after {_STEALTH_FAIL_LIMIT} fails - "
                  f"disabling for this run")
            _shutdown_stealth_browser()
            _STEALTH_DISABLED = True
        return False, f"stealth error: {str(e)[:80]}"
    finally:
        if page is not None:
            try: page.close()
            except Exception: pass


def _env_val(key: str) -> Optional[str]:
    """Read a value from os.environ or sequences/search.env. Ignores the
    <paste-...> placeholders so an un-filled key reads as unset."""
    v = os.environ.get(key)
    if v and v.strip() and not v.strip().startswith("<"):
        return v.strip()
    envf = Path(__file__).resolve().parent / "search.env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith(key) and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and not val.startswith("<"):
                    return val
    return None


# Set once per run if the CSE project returns PERMISSION_DENIED (API disabled), so we
# stop paying a dead first call + log line on every single query. Resets each process,
# so the moment the Custom Search JSON API is re-enabled, the next run uses CSE again.
_CSE_DOWN = False


def _search_google_cse(query: str, max_results: int, country: str,
                       key: str, cx: str) -> list[str]:
    """Google Programmable Search (Custom Search JSON API). DEAD for this
    account: Google closed the API to new customers (~Jan 2026) and every
    key/project gets 403 PERMISSION_DENIED. Kept only in case the account is
    ever grandfathered — use Serper/Brave instead."""
    try:
        r = httpx.get(
            "https://www.googleapis.com/customsearch/v1",
            params={"key": key, "cx": cx, "q": query,
                    "num": str(min(max_results, 10)), "gl": country or "us"},
            timeout=20,
        )
        if r.status_code != 200:
            global _CSE_DOWN
            if r.status_code == 403 and "Custom Search" in r.text:
                _CSE_DOWN = True
                print("    ! Google CSE denied (Google closed the Custom Search JSON API "
                      "to new customers ~Jan 2026 — no console fix exists), skipping CSE "
                      "for the rest of this run. Set SERPER_API_KEY or "
                      "BRAVE_SEARCH_API_KEY in search.env instead.")
            else:
                print(f"    ! Google CSE {r.status_code} for {query!r}: {r.text[:120]}")
            return []
        items = r.json().get("items") or []
    except Exception as e:
        print(f"    ! Google CSE error for {query!r}: {str(e)[:100]}")
        return []
    return [it["link"] for it in items if it.get("link")][:max_results]


def _brave_api_key() -> Optional[str]:
    """Brave Search API key from env var BRAVE_SEARCH_API_KEY or
    sequences/search.env. Returns None if unset/placeholder."""
    key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if key and key.strip():
        return key.strip()
    envf = Path(__file__).resolve().parent / "search.env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("BRAVE_SEARCH_API_KEY") and "=" in line:
                v = line.split("=", 1)[1].strip().strip('"').strip("'")
                if v and not v.startswith("<"):   # ignore the <paste-key> placeholder
                    return v
    return None


def _search_brave_api(query: str, max_results: int, country: str, api_key: str) -> list[str]:
    """Brave Search API — reliable real results (free tier ~2k/mo, 1 req/s).
    Replaces the ddgs/DuckDuckGo HTML scrape, which degrades to garbage
    (dictionaries / tourism / unrelated retail) once DDG rate-limits."""
    try:
        r = httpx.get(
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": str(min(max_results, 20)), "country": country},
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            timeout=20,
        )
        if r.status_code != 200:
            print(f"    ! Brave API {r.status_code} for {query!r}: {r.text[:120]}")
            return []
        results = (r.json().get("web") or {}).get("results") or []
    except Exception as e:
        print(f"    ! Brave API error for {query!r}: {str(e)[:100]}")
        return []
    return [x["url"] for x in results if x.get("url")][:max_results]


def _search_serper(query: str, max_results: int, country: str, api_key: str) -> list[str]:
    """Serper.dev Google SERP API — real Google results. 2,500 free one-time
    queries on signup, then paid. Replaces Google CSE, which Google closed to
    new customers (~Jan 2026): every key/project on this account now gets
    403 "does not have the access" permanently."""
    try:
        r = httpx.post(
            "https://google.serper.dev/search",
            json={"q": query, "num": min(max_results, 10), "gl": country or "us"},
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            timeout=20,
        )
        if r.status_code != 200:
            print(f"    ! Serper {r.status_code} for {query!r}: {r.text[:120]}")
            return []
        organic = r.json().get("organic") or []
    except Exception as e:
        print(f"    ! Serper error for {query!r}: {str(e)[:100]}")
        return []
    return [x["link"] for x in organic if x.get("link")][:max_results]


# --- Free, keyless scrapers. Verified returning real, on-topic results from this
#     box (probe 2026-06): DDG-html, Startpage, Mojeek. Used when no Brave/CSE key
#     is set, AHEAD of the ddgs library (which returns junk on this IP). ---
_SCRAPE_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_SCRAPE_HDRS = {"User-Agent": _SCRAPE_UA, "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml"}


def _search_ddg_html(query: str, max_results: int, country: str, region: str) -> list[str]:
    """DuckDuckGo HTML endpoint scraped directly (NOT the ddgs library, which
    returns junk here). Free, no key. Decodes the uddg redirect to the real URL."""
    from urllib.parse import unquote
    r = httpx.post("https://html.duckduckgo.com/html/",
                   data={"q": query, "kl": region or "us-en"},
                   headers=_SCRAPE_HDRS, timeout=20, follow_redirects=True)
    if r.status_code != 200:
        print(f"    ! DDG-html {r.status_code} for {query!r}")
        return []
    out: list[str] = []
    for href in re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"', r.text):
        m = re.search(r'uddg=([^&]+)', href)
        u = unquote(m.group(1)) if m else href
        if u.startswith("http"):
            out.append(u)
    return list(dict.fromkeys(out))[:max_results]


def _search_startpage(query: str, max_results: int, country: str, region: str) -> list[str]:
    """Startpage (anonymized Google results), scraped directly. Free, no key.
    Highest-quality keyless results, but the most anti-bot, so it is rotated with
    the others rather than hammered alone."""
    r = httpx.get("https://www.startpage.com/sp/search",
                  params={"query": query, "cat": "web"},
                  headers=_SCRAPE_HDRS, timeout=20, follow_redirects=True)
    if r.status_code != 200:
        print(f"    ! Startpage {r.status_code} for {query!r}")
        return []
    links = re.findall(
        r'<a[^>]+class="[^"]*result-(?:link|title)[^"]*"[^>]+href="(https?://[^"]+)"', r.text)
    if not links:
        links = re.findall(r'<a[^>]+class="w-gl__result-url[^"]*"[^>]+href="(https?://[^"]+)"', r.text)
    return list(dict.fromkeys(links))[:max_results]


def _search_mojeek(query: str, max_results: int, country: str, region: str) -> list[str]:
    """Mojeek (independent index), scraped directly. Free, no key, very scrape-
    tolerant; smaller index than Google/DDG so it backs up the other two."""
    r = httpx.get("https://www.mojeek.com/search", params={"q": query},
                  headers=_SCRAPE_HDRS, timeout=20, follow_redirects=True)
    if r.status_code != 200:
        print(f"    ! Mojeek {r.status_code} for {query!r}")
        return []
    links = re.findall(r'<a[^>]+class="ob"[^>]+href="(https?://[^"]+)"', r.text)
    return list(dict.fromkeys(links))[:max_results]


def _search(query: str, max_results: int, country: str = "us") -> list[str]:
    """Search dispatcher, in order of reliability:
      1. Serper.dev Google SERP API     (real Google results; preferred when set)
      2. Brave Search API               (free tier, when a key is set)
      3. Google Custom Search JSON API  (DEAD: Google closed it to new customers
         ~Jan 2026; kept only in case this account is ever grandfathered)
      4. Keyless scrapers DDG-html / Startpage / Mojeek (real results, no key/card,
         rotated per call) -- the working default while no API key is set
      5. ddgs library multi-backend     (last resort; frequently junk on this IP)
    First backend that yields results wins."""
    s_key = _env_val("SERPER_API_KEY")
    if s_key:
        urls = _search_serper(query, max_results, country, s_key)
        if urls:
            print(f"    (Serper: {len(urls)} results)")
            return urls
        print(f"    (Serper: 0 results, falling back)")
    b_key = _brave_api_key()
    if b_key:
        urls = _search_brave_api(query, max_results, country, b_key)
        time.sleep(1.1)   # Brave free tier rate limit: 1 request/second
        if urls:
            print(f"    (Brave API: {len(urls)} results)")
            return urls
        print(f"    (Brave API: 0 results, falling back)")
    g_key, g_cx = _env_val("GOOGLE_CSE_KEY"), _env_val("GOOGLE_CSE_CX")
    if g_key and g_cx and not _CSE_DOWN:
        urls = _search_google_cse(query, max_results, country, g_key, g_cx)
        if urls:
            print(f"    (Google CSE: {len(urls)} results)")
            return urls
        print(f"    (Google CSE: 0 results, falling back)")
    region = {"us": "us-en", "de": "de-de", "gb": "gb-en"}.get(country, "us-en")
    # Free, keyless scrapers verified working (probe 2026-06): real on-topic results,
    # no key/card. Rotated per call to spread load across engines and dodge per-engine
    # rate limits; first one that yields wins.
    import random
    scrapers = [("DDG-html", _search_ddg_html), ("Startpage", _search_startpage),
                ("Mojeek", _search_mojeek)]
    random.shuffle(scrapers)
    for _name, _fn in scrapers:
        try:
            urls = _fn(query, max_results, country, region)
        except Exception as e:
            print(f"    ! {_name} error for {query!r}: {str(e)[:80]}")
            continue
        if urls:
            print(f"    ({_name}: {len(urls)} results)")
            return urls
        print(f"    ({_name}: 0 results, next)")
    # last resort: the ddgs library (frequently junk on this IP)
    return _search_ddg(query, max_results, region)


def _search_ddg(query: str, max_results: int = 10, region: str = "us-en") -> list[str]:
    """ddgs multi-engine HTML search (fallback when no Brave key). Returns up
    to max_results URLs. The default DuckDuckGo backend is frequently rate-
    limited to zero (or junk) results, so we cycle through the other ddgs
    backends and stop at the first that yields. region is derived per-niche
    from discovery.search_country (was hardcoded de-de — wrong for US niches)."""
    backends = ["duckduckgo", "bing", "brave", "google", "mojeek", "yahoo"]
    for be in backends:
        urls: list[str] = []
        try:
            for r in DDGS().text(query, region=region,
                                 max_results=max_results, backend=be):
                u = r.get("href") or r.get("url")
                if u:
                    urls.append(u)
        except Exception as e:
            print(f"    ! ddgs backend={be} error for {query!r}: {str(e)[:80]}")
            continue
        if urls:
            print(f"    (backend={be}: {len(urls)} results)")
            return urls
    return []


def _append_seeds_to_yaml(yaml_path: Path, new_seeds: list[str]) -> None:
    """Append new URLs INSIDE the niche YAML's `seeds:` list (not at EOF).
    Finds the line just before the next top-level key after `seeds:` and
    splices the new bullets there. Preserves existing comments and per-
    seed metadata. Idempotent: URLs already in the file are skipped at
    discovery time, not here.

    YAML structure assumption (matches all niche YAMLs in this repo):
        seeds:
          - { url: "...", company: "...", city: "..." }
          - "https://..."
          ...
        <other-top-level-key>:           <-- insertion point is just above this
    """
    if not new_seeds: return
    lines = yaml_path.read_text(encoding="utf-8").splitlines()
    # Find `seeds:` line, then the first subsequent line that begins a new
    # top-level key (matches r"^[a-zA-Z_]" at column 0).
    seeds_idx = next((i for i, ln in enumerate(lines)
                      if ln.strip().startswith("seeds:")), None)
    if seeds_idx is None:
        # Niche has no seeds: block; fall back to EOF append (less clean
        # but doesn't corrupt the file).
        with yaml_path.open("a", encoding="utf-8") as f:
            f.write("\nseeds:\n")
            for u in new_seeds: f.write(f"  - {u}\n")
        return

    insert_at = len(lines)
    next_top_level_re = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*:")
    for i in range(seeds_idx + 1, len(lines)):
        if next_top_level_re.match(lines[i]):
            insert_at = i
            break

    # Trim trailing blank lines just before the insertion point so the new
    # block sits flush against the existing seeds list.
    while insert_at > seeds_idx + 1 and lines[insert_at - 1].strip() == "":
        insert_at -= 1

    stamp = time.strftime("%Y-%m-%d %H:%M")
    block = [
        "",
        f"  # auto-discovered {stamp} via seed_discover.py",
    ]
    for u in new_seeds:
        block.append(f"  - {u}")
    block.append("")
    new_lines = lines[:insert_at] + block + lines[insert_at:]
    yaml_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def discover_for_niche(slug: str, *, max_per_query: int, dry: bool) -> dict:
    yaml_path, niche = _load_niche(slug)
    queries = niche.get("search_queries") or []
    if not queries:
        print(f"  {slug}: no search_queries in YAML, skipping")
        return {"slug": slug, "skipped": "no_queries"}

    disc_cfg     = niche.get("discovery") or {}
    max_seeds    = int(disc_cfg.get("max_seeds_per_run", 20))
    require_mt   = bool(disc_cfg.get("require_mailto", True))
    require_kw   = list(disc_cfg.get("require_keywords") or [])
    skip_domains = set((disc_cfg.get("exclude_domains") or []))
    country      = str(disc_cfg.get("search_country", "us"))

    existing = _existing_seed_urls(niche)
    print(f"\n=== {slug} ===")
    print(f"  existing seeds : {len(existing)}")
    print(f"  queries        : {len(queries)}")
    print(f"  max_new        : {max_seeds}")
    print(f"  require_mailto : {require_mt}")
    print(f"  require_kw     : {require_kw}")

    candidates: list[str] = []
    seen = set()
    for q in queries:
        urls = _search(q, max_per_query, country)
        print(f"  + search {q!r:54s} -> {len(urls)} results")
        for u in urls:
            u = u.rstrip("/")
            if u in seen or u in existing: continue
            host = urlparse(u).netloc.lower()
            if any(host.endswith(b) for b in skip_domains): continue
            seen.add(u)
            candidates.append(u)

    print(f"  raw candidates : {len(candidates)}")

    validated: list[str] = []
    for u in candidates:
        ok, why = _is_valid_seed(u, require_mt, require_kw)
        if ok:
            validated.append(u)
            print(f"    OK  {u}  [{why}]")
        else:
            print(f"    -   {u}  [{why}]")
        if len(validated) >= max_seeds: break

    if not dry and validated:
        _append_seeds_to_yaml(yaml_path, validated)
        print(f"  + appended {len(validated)} new seeds to {yaml_path.name}")
    return {"slug": slug, "new_seeds": len(validated),
            "examples": validated[:5]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--niche", help="single niche slug; default = all with search_queries")
    ap.add_argument("--max-per-query", type=int, default=10)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if args.niche:
        niches = [args.niche]
    else:
        niches = [p.stem for p in NICHES.glob("*.yaml")]

    results = []
    for slug in niches:
        try:
            results.append(discover_for_niche(
                slug, max_per_query=args.max_per_query, dry=args.dry,
            ))
        except SystemExit as e:
            print(f"  ! {slug}: {e}")
        except Exception as e:
            print(f"  ! {slug}: {e}")

    print("\n=== SUMMARY ===")
    for r in results:
        if r.get("skipped"): continue
        print(f"  {r['slug']:25s} +{r.get('new_seeds',0)} seeds")

    # Tear down the shared playwright/stealth browser if it was started
    # during validation. Without this the python process can hang on exit
    # because of the underlying node child process pipe.
    _shutdown_stealth_browser()
    return 0


if __name__ == "__main__":
    sys.exit(main())
