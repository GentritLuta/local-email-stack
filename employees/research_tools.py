# -*- coding: utf-8 -*-
"""research_tools.py - keyless research + image tools for the Adriatik editorial roles.

Stdlib only (urllib, re, json) so it runs on a fresh RTX with no pip installs, same
philosophy as rtx-operator/local_model.py. Every function returns plain dicts/lists,
never raises on a bad network call (returns an empty result + an "error" field instead)
so a single flaky backend can't crash an unattended shift.

Backends (probed live 2026-07-02):
  search_news         Google News RSS (keyless, reliable, current)
  search_wikipedia     Wikipedia API (keyless, background/verification)
  fetch_url            plain GET + HTML-tag-strip, for reading a source article
  find_real_image       Openverse -> Wikimedia Commons fallback (real, CC-licensed photos;
                        for NEWS and INVESTIGATION pieces only - never fabricate a news photo)
  find_illustration_image  pollinations.ai (AI-generated; OPINION and RESEARCH covers only,
                        never news/investigation - editorial policy, not a technical limit)
  search_aleph          OCCRP Aleph (leaked documents, corporate/court records aggregator;
                        for commercial/political corruption investigation)
  search_corporate_registry  GLEIF (global legal-entity identifiers; corporate identity/
                        ownership verification)
  search_wikidata        structured entity data (positions held, board memberships,
                        organizational relationships)

Known-flaky/unusable backends (probed 2026-07-02, NOT used here): general keyless web
search (DuckDuckGo html, Startpage) returned redirect/bot-check codes; GDELT timed out;
OpenSanctions and OpenCorporates both require a registered API key (401 without one) so
they are not wired in - genuinely keyless equivalents (Aleph, GLEIF, Wikidata) are used
instead. RSS + Wikipedia + Openverse/Commons + Aleph/GLEIF/Wikidata cover news,
background verification, real images, and open-source corporate/political research
without depending on any of the flaky/gated ones.
"""
import json
import re
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (AdriatikEditorial/1.0; +https://adriatik.pages.dev)"
_TIMEOUT = 12


def _get(url: str, timeout: int = _TIMEOUT) -> tuple:
    """Returns (ok, text_or_error)."""
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, r.read().decode("utf-8", errors="replace")
    except Exception as e:
        return False, str(e)


def _get_json(url: str, timeout: int = _TIMEOUT) -> tuple:
    ok, text = _get(url, timeout)
    if not ok:
        return False, {"error": text}
    try:
        return True, json.loads(text)
    except Exception as e:
        return False, {"error": f"bad json: {e}"}


# ─── news research ───────────────────────────────────────────────────────────

def search_news(query: str, max_results: int = 8) -> list:
    """Google News RSS search. Returns [{title, link, source, published}]."""
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(query)
           + "&hl=en-US&gl=US&ceid=US:en")
    ok, xml = _get(url)
    if not ok:
        return [{"error": xml}]
    items = re.findall(r"<item>(.*?)</item>", xml, re.S)
    out = []
    for raw in items[:max_results]:
        title = re.search(r"<title>(.*?)</title>", raw, re.S)
        link = re.search(r"<link>(.*?)</link>", raw, re.S)
        pub = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.S)
        source = re.search(r"<source[^>]*>(.*?)</source>", raw, re.S)
        out.append({
            "title": _unescape(title.group(1)) if title else "",
            "link": (link.group(1) or "").strip() if link else "",
            "published": pub.group(1).strip() if pub else "",
            "source": _unescape(source.group(1)) if source else "",
        })
    return out


def _unescape(s: str) -> str:
    s = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", s, flags=re.S).strip()
    for a, b in (("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"),
                 ("&quot;", '"'), ("&#39;", "'")):
        s = s.replace(a, b)
    return s.strip()


# ─── background / verification ───────────────────────────────────────────────

def search_wikipedia(query: str, max_results: int = 5) -> list:
    """Returns [{title, snippet, url}] for background facts and cross-checks."""
    url = ("https://en.wikipedia.org/w/api.php?action=query&list=search&format=json"
           f"&srlimit={max_results}&srsearch=" + urllib.parse.quote(query))
    ok, data = _get_json(url)
    if not ok:
        return [{"error": data.get("error", "unknown")}]
    out = []
    for r in data.get("query", {}).get("search", []):
        title = r.get("title", "")
        snippet = re.sub(r"<[^>]+>", "", r.get("snippet", ""))
        out.append({
            "title": title,
            "snippet": snippet,
            "url": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
        })
    return out


def fetch_url(url: str, max_chars: int = 6000) -> dict:
    """Fetch a page and return readable text (crude tag-strip, stdlib only).
    Use to read a news article or source page found via search_news/search_wikipedia
    before asserting a fact from it."""
    ok, html = _get(url, timeout=15)
    if not ok:
        return {"url": url, "error": html, "text": ""}
    html = re.sub(r"(?is)<(script|style|nav|header|footer|noscript)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = _unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return {"url": url, "error": None, "text": text.strip()[:max_chars]}


# ─── images ───────────────────────────────────────────────────────────────────
# WorkImage shape (must match D:/adriatik/lib/content.ts exactly):
#   { url, credit, alt, sourcePage }

def find_real_image(query: str, max_results: int = 5) -> list:
    """Real, CC-licensed photos only. Openverse first, Wikimedia Commons fallback.
    Use for NEWS and INVESTIGATION pieces. If this returns [], the piece runs
    text-only - never substitute an AI-generated image for a real news photo."""
    out = []
    ok, data = _get_json(
        "https://api.openverse.org/v1/images/?q=" + urllib.parse.quote(query)
        + f"&page_size={max_results}&license_type=commercial,modification")
    if ok:
        for r in data.get("results", [])[:max_results]:
            img_url = r.get("url") or ""
            if not img_url:
                continue
            creator = r.get("creator") or "Unknown"
            license_ = (r.get("license") or "").upper()
            out.append({
                "url": img_url,
                "credit": f"{creator} / {license_} via Openverse",
                "alt": (r.get("title") or query)[:200],
                "sourcePage": r.get("foreign_landing_url") or r.get("detail_url") or "",
            })
    if out:
        return out
    ok, data = _get_json(
        "https://commons.wikimedia.org/w/api.php?action=query&generator=search"
        f"&gsrsearch={urllib.parse.quote(query)}&gsrnamespace=6&gsrlimit={max_results}"
        "&prop=imageinfo&iiprop=url|extmetadata&format=json")
    if not ok:
        return []
    pages = (data.get("query") or {}).get("pages") or {}
    for p in pages.values():
        info = (p.get("imageinfo") or [{}])[0]
        img_url = info.get("url", "")
        if not img_url:
            continue
        meta = info.get("extmetadata", {})
        artist = re.sub(r"<[^>]+>", "", (meta.get("Artist", {}) or {}).get("value", "Unknown"))
        license_ = (meta.get("LicenseShortName", {}) or {}).get("value", "CC")
        out.append({
            "url": img_url,
            "credit": f"{artist} / {license_} via Wikimedia Commons",
            "alt": p.get("title", query)[:200],
            "sourcePage": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(p.get('title',''))}",
        })
    return out


def find_illustration_image(prompt: str, width: int = 1200, height: int = 800) -> dict:
    """AI-generated illustrative image (Pollinations/Flux, free, keyless).
    OPINION and RESEARCH covers only - NEVER for news or investigation pieces,
    which must use find_real_image or run text-only."""
    url = (f"https://image.pollinations.ai/prompt/{urllib.parse.quote(prompt)}"
           f"?width={width}&height={height}&nologo=true&model=flux")
    return {
        "url": url,
        "credit": "AI-generated illustration (Pollinations/Flux)",
        "alt": prompt[:200],
        "sourcePage": "",
    }


# ─── open-source corruption / corporate / political investigation ────────────

def search_aleph(query: str, schema: str = "Company", max_results: int = 8) -> list:
    """OCCRP Aleph: search leaked documents, corporate registries, and court records
    aggregated from public and leaked sources. schema: "Company", "Person",
    "LegalEntity", "Organization", or "" for any. Lawful open-source use only - this
    indexes public records and previously-published leak collections, not private
    account access. Known quirk: a bare query with no schema filter can 500; always
    pass a schema. HONEST LIMITATION (checked 2026-07-02): anonymous/keyless access
    only searches ~21 small public casefiles, not OCCRP's major leak databases
    (Panama Papers, Offshore Leaks, etc.) - those need a free Aleph account. Treat a
    result here as a bonus, not a primary source; search_news + fetch_url remain the
    main research path until a real Aleph API key is added to this function."""
    q = urllib.parse.quote(query)
    schema_part = f"&filter%3Aschemata={urllib.parse.quote(schema)}" if schema else ""
    ok, data = _get_json(
        f"https://aleph.occrp.org/api/2/entities?q={q}{schema_part}&limit={max_results}")
    if not ok:
        return [{"error": data.get("error", "unknown")}]
    out = []
    for r in (data.get("results") or [])[:max_results]:
        props = r.get("properties", {}) or {}
        out.append({
            "name": r.get("name") or (props.get("name") or [""])[0],
            "schema": r.get("schema", ""),
            "countries": props.get("country", []),
            "collection": (r.get("collection") or {}).get("label", ""),
            "url": f"https://aleph.occrp.org/entities/{r.get('id')}" if r.get("id") else "",
        })
    return out


def search_corporate_registry(company_name: str, max_results: int = 5) -> list:
    """GLEIF global Legal Entity Identifier registry - real, keyless, verifies a
    company's registered legal name, jurisdiction, and status. Good for confirming a
    company actually exists and how its legal name is registered, before naming it in
    a piece."""
    ok, data = _get_json(
        "https://api.gleif.org/api/v1/lei-records?filter%5Bentity.legalName%5D="
        + urllib.parse.quote(company_name) + f"&page%5Bsize%5D={max_results}")
    if not ok:
        return [{"error": data.get("error", "unknown")}]
    out = []
    for r in data.get("data", [])[:max_results]:
        attrs = r.get("attributes", {})
        entity = attrs.get("entity", {})
        out.append({
            "legalName": (entity.get("legalName") or {}).get("name", ""),
            "lei": attrs.get("lei", ""),
            "jurisdiction": entity.get("jurisdiction", ""),
            "status": entity.get("status", ""),
            "registeredAddress": entity.get("legalAddress", {}).get("addressLines", []),
        })
    return out


def search_wikidata(query: str, max_results: int = 5) -> list:
    """Structured entity data: positions held, board memberships, organizational
    relationships. Useful for cross-checking who holds what office or board seat
    before asserting a connection between a person and a company or institution."""
    ok, data = _get_json(
        "https://www.wikidata.org/w/api.php?action=wbsearchentities&search="
        + urllib.parse.quote(query) + f"&language=en&format=json&limit={max_results}")
    if not ok:
        return [{"error": data.get("error", "unknown")}]
    out = []
    for r in data.get("search", [])[:max_results]:
        out.append({
            "label": r.get("label", ""),
            "description": r.get("description", ""),
            "id": r.get("id", ""),
            "url": f"https://www.wikidata.org/wiki/{r.get('id','')}",
        })
    return out


# ─── tool schema (OpenAI-style function-calling, for local_agent.py) ──────────

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "search_news", "description": "Search current news via Google News RSS.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "max_results": {"type": "integer"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "search_wikipedia", "description": "Search Wikipedia for background/verification.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "max_results": {"type": "integer"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "fetch_url", "description": "Fetch and read a web page's text content.",
        "parameters": {"type": "object", "properties": {
            "url": {"type": "string"}, "max_chars": {"type": "integer"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "find_real_image",
        "description": "Find a real, CC-licensed photo. Required for news/investigation pieces.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "max_results": {"type": "integer"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "find_illustration_image",
        "description": "Generate an AI illustration. Opinion/research covers only, never news/investigation.",
        "parameters": {"type": "object", "properties": {
            "prompt": {"type": "string"}, "width": {"type": "integer"}, "height": {"type": "integer"}},
            "required": ["prompt"]}}},
    {"type": "function", "function": {
        "name": "search_aleph",
        "description": "Search OCCRP Aleph for corporate/court records and leaked documents (open-source corruption research).",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "schema": {"type": "string"}, "max_results": {"type": "integer"}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "search_corporate_registry",
        "description": "Verify a company's registered legal identity via the global GLEIF registry.",
        "parameters": {"type": "object", "properties": {
            "company_name": {"type": "string"}, "max_results": {"type": "integer"}},
            "required": ["company_name"]}}},
    {"type": "function", "function": {
        "name": "search_wikidata",
        "description": "Look up structured facts: positions held, board memberships, organizational ties.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"}, "max_results": {"type": "integer"}},
            "required": ["query"]}}},
]

TOOL_FUNCS = {
    "search_news": search_news,
    "search_wikipedia": search_wikipedia,
    "fetch_url": fetch_url,
    "find_real_image": find_real_image,
    "find_illustration_image": find_illustration_image,
    "search_aleph": search_aleph,
    "search_corporate_registry": search_corporate_registry,
    "search_wikidata": search_wikidata,
}


if __name__ == "__main__":
    print("search_news('Kosovo'):", len(search_news("Kosovo", 3)), "results")
    print("search_wikipedia('rule of law Balkans'):", len(search_wikipedia("rule of law Balkans", 3)), "results")
    print("find_real_image('Belgrade skyline'):", len(find_real_image("Belgrade skyline", 3)), "results")
    r = find_illustration_image("Balkan mountain landscape, editorial photo style")
    print("find_illustration_image url:", r["url"][:80], "...")
    print("search_aleph('Kosovo', 'Company'):", search_aleph("Kosovo", "Company", 3))
    print("search_corporate_registry('Deutsche Bank'):", len(search_corporate_registry("Deutsche Bank", 2)), "results")
    print("search_wikidata('Kosovo'):", len(search_wikidata("Kosovo", 3)), "results")
