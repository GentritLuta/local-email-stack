"""intent_signals.py — seller-intent orchestrator (the seller-appointment front end).

For an agent-client and a metro, run a signal pack's fixed search instructions,
validate evidence, score deterministically, and store seller-lead signals into
the `intent_signals` table (migration 009). The AI/search never freelances: each
signal expands the SAME templated query and only keyword-validated, evidence-
backed results count. No qualifying public evidence => no signal.

Channels are advisory routing only. B2C signals never produce a consumer
cold-email action (enforced by signal_pack_lib). Homeowners are emailed only
after they opt into the funnel.

USAGE
    py sequences/intent_signals.py run --profile <agent_slug> --metro "Austin, TX"
    py sequences/intent_signals.py run --profile <slug> --metro "Austin, TX" --dry
    py sequences/intent_signals.py packs
    py sequences/intent_signals.py selftest      # offline (no network/DB)

Metro-scan mode runs the social-listening signals (templates keyed on {metro}).
Public-record signals keyed on {address}/{owner} are skipped until a seller list
is supplied; they need a public-records data source, not a web search.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

import signal_pack_lib as spl
import intent_score as isc

REPO = Path(__file__).resolve().parent.parent
SUPA_ENV = REPO / "sequences" / "supabase.env"
SEARCH_ENV = REPO / "sequences" / "search.env"

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# default pack per jurisdiction
DEFAULT_PACK = {"US": "us_real_estate_distress", "EU": "eu_b2b"}


# ─── env / supabase (mirrors queue_lib.py) ─────────────────────────────────

def _load_supabase_env() -> tuple[str, str]:
    env: dict[str, str] = {}
    if SUPA_ENV.exists():
        for line in SUPA_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_SERVICE_KEY") or env.get("SUPABASE_ANON_KEY", "")
    return url.rstrip("/"), key


def _supa_headers(key: str) -> dict:
    return {"apikey": key, "Authorization": f"Bearer {key}",
            "Content-Type": "application/json"}


def get_client_geos(profile_slug: str) -> list[str]:
    """Read profiles.lead_intent.location_geos for the client. Empty on miss."""
    url, key = _load_supabase_env()
    if not url or not key:
        return []
    try:
        r = httpx.get(
            f"{url}/rest/v1/profiles?slug=eq.{profile_slug}&select=lead_intent",
            headers=_supa_headers(key), timeout=20)
        if r.status_code != 200:
            return []
        rows = r.json() or []
        if not rows:
            return []
        li = rows[0].get("lead_intent") or {}
        return list(li.get("location_geos") or [])
    except Exception:
        return []


def _store_rows(rows: list[dict]) -> int:
    url, key = _load_supabase_env()
    if not url or not key:
        raise RuntimeError(f"missing SUPABASE_URL / key in {SUPA_ENV}")
    headers = {**_supa_headers(key),
               "Prefer": "resolution=ignore-duplicates,return=representation"}
    r = httpx.post(f"{url}/rest/v1/intent_signals", headers=headers,
                   json=rows, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"store {r.status_code}: {r.text[:300]}")
    return len(r.json() if r.content else [])


# ─── search dispatch (mirrors seed_discover.py Serper-first chain) ─────────

def _serper_key() -> Optional[str]:
    v = os.environ.get("SERPER_API_KEY")
    if v and v.strip() and not v.strip().startswith("<"):
        return v.strip()
    if SEARCH_ENV.exists():
        for line in SEARCH_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SERPER_API_KEY") and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and not val.startswith("<"):
                    return val
    return None


def _search_serper(query: str, num: int, gl: str, key: str) -> list[dict]:
    try:
        r = httpx.post("https://google.serper.dev/search",
                       json={"q": query, "num": min(num, 10), "gl": gl or "us"},
                       headers={"X-API-KEY": key, "Content-Type": "application/json"},
                       timeout=20)
        if r.status_code != 200:
            print(f"    ! Serper {r.status_code}: {r.text[:120]}")
            return []
        organic = r.json().get("organic") or []
    except Exception as e:
        print(f"    ! Serper error: {str(e)[:100]}")
        return []
    out = []
    for it in organic:
        if it.get("link"):
            out.append({"title": it.get("title", ""), "link": it["link"],
                        "snippet": it.get("snippet", ""), "date": it.get("date")})
    return out[:num]


def _brave_key() -> Optional[str]:
    v = os.environ.get("BRAVE_SEARCH_API_KEY")
    if v and v.strip() and not v.strip().startswith("<"):
        return v.strip()
    if SEARCH_ENV.exists():
        for line in SEARCH_ENV.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("BRAVE_SEARCH_API_KEY") and "=" in line:
                val = line.split("=", 1)[1].strip().strip('"').strip("'")
                if val and not val.startswith("<"):
                    return val
    return None


def _search_brave(query: str, num: int, gl: str, key: str) -> list[dict]:
    """Brave Search API (free tier ~2k/mo). Real results with title+snippet."""
    try:
        r = httpx.get("https://api.search.brave.com/res/v1/web/search",
                      params={"q": query, "count": min(num, 20), "country": gl or "us"},
                      headers={"X-Subscription-Token": key, "Accept": "application/json"},
                      timeout=20)
        if r.status_code != 200:
            print(f"    ! Brave {r.status_code}: {r.text[:120]}")
            return []
        results = (r.json().get("web") or {}).get("results") or []
    except Exception as e:
        print(f"    ! Brave error: {str(e)[:100]}")
        return []
    out = []
    for x in results:
        if x.get("url"):
            out.append({"title": x.get("title", ""), "link": x["url"],
                        "snippet": x.get("description", ""), "date": x.get("age")})
    return out[:num]


_KW_HDRS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml"}


def _strip(s: str) -> str:
    s = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", s or "")
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _kw_ddg(query: str, num: int) -> list[dict]:
    """DuckDuckGo HTML endpoint, scraped directly. Title + link + snippet."""
    from urllib.parse import unquote
    try:
        r = httpx.post("https://html.duckduckgo.com/html/", data={"q": query},
                       headers=_KW_HDRS, timeout=20, follow_redirects=True)
        if r.status_code != 200:
            return []
    except Exception:
        return []
    titles = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                        r.text, re.S)
    snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
    out = []
    for i, (href, title) in enumerate(titles):
        mm = re.search(r"uddg=([^&]+)", href)
        link = unquote(mm.group(1)) if mm else href
        if not link.startswith("http"):
            continue
        out.append({"title": _strip(title), "link": link,
                    "snippet": _strip(snippets[i]) if i < len(snippets) else "",
                    "date": None})
    return out[:num]


def _kw_startpage(query: str, num: int) -> list[dict]:
    """Startpage (anonymized Google), scraped. Title + link; snippet best-effort."""
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
        out.append({"title": _strip(title), "link": link, "snippet": "", "date": None})
    return out[:num]


def _kw_mojeek(query: str, num: int) -> list[dict]:
    """Mojeek (independent index), scraped. Title + link."""
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
        out.append({"title": _strip(title), "link": link, "snippet": "", "date": None})
    return out[:num]


def _simplify_query(q: str) -> str:
    """Keyless HTML engines do not parse Google operators. Turn site:reddit.com
    into the keyword 'reddit', drop OR and exact-match quotes."""
    q = re.sub(r"\bsite:(\S+)", lambda m: m.group(1).split(".")[0], q)
    q = q.replace('"', "")
    q = re.sub(r"\bOR\b", " ", q)
    return re.sub(r"\s+", " ", q).strip()


def _search_reddit(query: str, num: int) -> list[dict]:
    """Reddit's free public search JSON. Structured results with real titles,
    self-text snippets, and dates. No key, just a User-Agent. This is exactly
    where people publicly post selling intent, so it is the best free source."""
    import datetime as _dt
    q = _simplify_query(query)
    try:
        r = httpx.get("https://www.reddit.com/search.json",
                      params={"q": q, "sort": "relevance", "t": "year",
                              "limit": min(num * 2, 25), "type": "link"},
                      headers={"User-Agent": "aureon-intent-research/0.1"}, timeout=20)
        if r.status_code != 200:
            return []
        children = (r.json().get("data") or {}).get("children") or []
    except Exception:
        return []
    out = []
    for c in children:
        d = c.get("data") or {}
        perm = d.get("permalink")
        if not perm:
            continue
        date = None
        try:
            date = _dt.datetime.utcfromtimestamp(int(d["created_utc"])).strftime("%Y-%m-%d")
        except Exception:
            pass
        out.append({"title": d.get("title", ""),
                    "link": "https://www.reddit.com" + perm,
                    "snippet": (d.get("selftext", "") or "")[:300], "date": date})
    return out[:num]


def _search(query: str, num: int, gl: str) -> list[dict]:
    """Serper first when a key with credits is set; otherwise rotate the keyless
    scrapers (DDG / Startpage / Mojeek), first that yields wins. Mirrors the
    seed_discover.py backend chain, adapted to return title+snippet for evidence."""
    key = _serper_key()
    if key:
        res = _search_serper(query, num, gl, key)
        if res:
            return res
        # serper returned nothing (e.g. out of credits) -> try Brave, then keyless
    bkey = _brave_key()
    if bkey:
        res = _search_brave(query, num, gl, bkey)
        time.sleep(1.1)  # Brave free tier: 1 req/sec
        if res:
            return res
    # Reddit's own JSON search is free, structured, dated, and exactly where
    # people post selling intent -> try it first.
    res = _search_reddit(query, num)
    if res:
        return res
    # Keyless engines choke on Google operators, so simplify for them. Startpage
    # is most reliable on this IP; DDG/Mojeek are backups.
    kq = _simplify_query(query)
    scrapers = [("Startpage", _kw_startpage), ("DDG", _kw_ddg), ("Mojeek", _kw_mojeek)]
    for _name, _fn in scrapers:
        try:
            res = _fn(kq, num)
        except Exception:
            res = []
        if res:
            return res
    return []


# ─── evidence + rendering ──────────────────────────────────────────────────

_SOCIAL_DOMAINS = ("reddit.com", "nextdoor.com", "x.com", "twitter.com",
                   "quora.com", "facebook.com", "forum")


def _deslug(link: str) -> str:
    from urllib.parse import urlparse
    return re.sub(r"[-_/]+", " ", urlparse(link or "").path)


def _label(result: dict) -> str:
    """Clean lead label. Falls back to the URL slug when the scraper returned a
    junk title (CSS leak from Startpage etc.)."""
    from urllib.parse import urlparse
    t = _strip(result.get("title", ""))
    if not t or "{" in t or "css-" in t.lower():
        seg = [s for s in urlparse(result.get("link", "")).path.split("/") if s]
        t = re.sub(r"[-_]+", " ", seg[-1] if seg else "").strip().title()
    return t[:200]


def evidence_match(signal: dict, result: dict) -> tuple[bool, float]:
    """Keyword-grounded evidence test. Confidence rises with how many of the
    signal's evidence_keywords appear in the title, snippet, OR the de-slugged
    URL path (reddit/forum slugs carry the post title). found requires at least
    one. Social signals also require a discussion-domain link."""
    kws = [k.lower() for k in (signal.get("evidence_keywords") or [])]
    hay = (f"{_strip(result.get('title',''))} {result.get('snippet','')} "
           f"{_deslug(result.get('link',''))}").lower()
    hits = [k for k in kws if k in hay]
    if not hits:
        return False, 0.0
    conf = min(1.0, 0.4 + 0.2 * len(hits))
    if signal.get("kind") == "social_listening":
        link = (result.get("link") or "").lower()
        if not any(d in link for d in _SOCIAL_DOMAINS):
            conf *= 0.6  # could be a re-post / aggregator, trust it less
    return True, round(conf, 4)


def _extract_date(result: dict) -> Optional[str]:
    if result.get("date"):
        return str(result["date"])
    snip = result.get("snippet", "") or ""
    m = re.search(r"\b(20[12]\d)[-/](0?[1-9]|1[0-2])[-/](0?[1-9]|[12]\d|3[01])\b", snip)
    if m:
        return m.group(0)
    m = re.search(r"\b(20[12]\d)\b", snip)
    return m.group(0) if m else None


def _needs_lead(template: str) -> bool:
    return "{address}" in template or "{owner}" in template


def _render(template: str, metro: str, lead: Optional[dict]) -> str:
    lead = lead or {}
    repl = {
        "{metro}": metro or "", "{city}": metro or "",
        "{county}": (lead.get("county") or metro or ""),
        "{address}": (lead.get("address") or ""),
        "{owner}": (lead.get("owner") or ""),
        "{company}": (lead.get("company") or ""),
    }
    out = template
    for k, v in repl.items():
        out = out.replace(k, v)
    return re.sub(r"\s+", " ", out).strip()


_ADDR_RE = re.compile(
    r"\b\d{1,6}\s+(?:[NSEW]\.?\s+)?(?:[A-Z][A-Za-z0-9.'-]*\s+){0,4}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Court|Ct|"
    r"Circle|Cir|Way|Place|Pl|Trail|Trl|Highway|Hwy|Parkway|Pkwy|Terrace|Ter|"
    r"Cove|Cv|Loop|Path|Run|Pass|Bend|Square|Sq|Crossing|Xing)\b\.?", re.I)


def _extract_addresses(url: str, limit: int = 25) -> list[str]:
    """Fetch a notice/list page and pull US street addresses off it. Best-effort
    and free: this is what turns a county tax-sale page into individual property
    leads. Returns de-duplicated address strings."""
    try:
        r = httpx.get(url, headers=_KW_HDRS, timeout=15, follow_redirects=True)
        if r.status_code != 200:
            return []
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r.text))
    except Exception:
        return []
    out, seen = [], set()
    for m in _ADDR_RE.finditer(text):
        a = re.sub(r"\s+", " ", m.group(0)).strip().rstrip(".")
        key = a.lower()
        if key in seen or len(a) > 60 or len(a) < 6:
            continue
        seen.add(key)
        out.append(a)
        if len(out) >= limit:
            break
    return out


def _write_artifact(profile_slug: str, metro: str, pack_id: str,
                    rows: list[dict], by_lead: dict) -> Path:
    """Persist the scan to a local JSON artifact under out/intent/. This is the
    self-contained store the router reads, so the pipeline needs no DB."""
    import datetime as _dt
    out_dir = REPO / "out" / "intent"
    out_dir.mkdir(parents=True, exist_ok=True)
    metro_slug = re.sub(r"[^a-z0-9]+", "_", metro.lower()).strip("_") or "all"
    path = out_dir / f"{profile_slug}__{metro_slug}.signals.json"
    payload = {
        "profile_slug": profile_slug, "pack": pack_id, "metro": metro,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "leads": sorted(
            ({"lead_key": k, "intent": isc.aggregate(v)} for k, v in by_lead.items()),
            key=lambda d: d["intent"], reverse=True),
        "rows": rows,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ─── orchestration ─────────────────────────────────────────────────────────

def run_pack(profile_slug: str, metro: str, *, pack_id: Optional[str] = None,
             store_db: bool = False, enrich_addresses: bool = False,
             dry: bool = False, limit: int = 40, max_per_query: int = 8,
             today: Optional[dt.date] = None,
             geos_override: Optional[list[str]] = None,
             lead: Optional[dict] = None) -> dict:
    geos = geos_override if geos_override is not None else get_client_geos(profile_slug)
    if not geos:
        print(f"  ! no location_geos for {profile_slug}; pass --geos to proceed")
        return {"profile": profile_slug, "error": "no_geos"}

    if not pack_id:
        primary = str(geos[0]).upper()
        pack_id = DEFAULT_PACK.get(primary if primary == "US" else "EU")

    pack = spl.load_pack(pack_id)            # validates + guardrails
    spl.assert_for_client(pack, geos)        # guardrail 1: jurisdiction gate
    gl = "us" if str(pack["jurisdiction"]).upper() == "US" else "de"

    print(f"\n=== intent scan: {profile_slug} / {pack_id} / {metro!r} "
          f"(geos={geos}{' DRY' if dry else ''}) ===")

    rows: list[dict] = []
    by_lead: dict[str, list[float]] = {}
    skipped: list[str] = []
    _fetches = [0]          # cap on address-extraction page fetches per run
    max_fetches = 12

    for sig in pack["signals"]:
        sid = sig["id"]
        templates = sig["query_templates"]
        runnable = [t for t in templates if lead or not _needs_lead(t)]
        if not runnable:
            skipped.append(sid)
            continue
        found_for_sig = 0
        for tmpl in runnable:
            q = _render(tmpl, metro, lead)
            results = _search(q, max_per_query, gl)
            print(f"  [{sid}] {q!r} -> {len(results)} results")
            for res in results:
                found, conf = evidence_match(sig, res)
                if not found:
                    continue
                ev_date = _extract_date(res)
                url = res["link"]

                addrs = []
                if (enrich_addresses and sig.get("kind") == "public_record"
                        and _fetches[0] < max_fetches):
                    _fetches[0] += 1
                    addrs = _extract_addresses(url)

                for addr in (addrs or [None]):
                    ev_url = url if not addr else (
                        url + "#addr=" + hashlib.md5(addr.encode("utf-8")).hexdigest()[:8])
                    lead_key = hashlib.md5(ev_url.encode("utf-8")).hexdigest()[:16]
                    label = addr if addr else _label(res)
                    score = isc.signal_score(sig["confidence_weight"], conf, ev_date,
                                             sig.get("recency_days"), today)
                    by_lead.setdefault(lead_key, []).append(score)
                    rows.append({
                        "profile_slug": profile_slug, "pack": pack_id, "metro": metro,
                        "lead_key": lead_key, "lead_label": label[:200],
                        "signal_id": sid, "found": True, "evidence_url": ev_url,
                        "evidence_snippet": (addr or res.get("snippet", "") or "")[:500],
                        "event_date": ev_date, "confidence": conf,
                        "weight": sig["confidence_weight"], "score": score,
                        "channel": sig["channel"], "status": "new",
                    })
                    found_for_sig += 1
                    if len(rows) >= limit:
                        break
                if len(rows) >= limit:
                    break
            time.sleep(3.0)  # pace to avoid keyless-engine rate limits
            if len(rows) >= limit:
                break
        if len(rows) >= limit:
            break

    # dedup rows by (signal_id, evidence_url) to match the table's unique key
    seen = set()
    deduped = []
    for row in rows:
        k = (row["signal_id"], row["evidence_url"])
        if k in seen:
            continue
        seen.add(k)
        deduped.append(row)

    artifact = None
    stored = 0
    if deduped and not dry:
        artifact = _write_artifact(profile_slug, metro, pack_id, deduped, by_lead)
        if store_db:
            try:
                stored = _store_rows(deduped)
            except Exception as e:
                print(f"  ! DB store skipped ({str(e)[:100]})")

    summary = {
        "profile": profile_slug, "pack": pack_id, "metro": metro,
        "signals_run": len(pack["signals"]) - len(skipped),
        "skipped_need_lead": skipped,
        "leads_found": len(by_lead),
        "signal_rows": len(deduped),
        "artifact": str(artifact) if artifact else None,
        "stored_db": stored, "dry": dry,
        "top_leads": sorted(
            ({"lead_key": k, "intent": isc.aggregate(v)} for k, v in by_lead.items()),
            key=lambda d: d["intent"], reverse=True)[:5],
    }
    print("\n--- SUMMARY ---")
    print(json.dumps(summary, indent=2))
    return summary


# ─── CLI + offline selftest ────────────────────────────────────────────────

def _selftest() -> int:
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  {'OK ' if cond else 'FAIL'} {label}")
        ok = ok and cond

    # packs load through the guarded loader
    for pid in ("us_real_estate_distress", "eu_b2b"):
        try:
            spl.load_pack(pid)
            check(f"{pid} loads", True)
        except Exception as e:
            check(f"{pid} loads ({e})", False)

    # render substitutes metro and drops lead placeholders
    r = _render('site:reddit.com selling my house {metro} recommend realtor', "Austin, TX", None)
    check(f"render metro ({r!r})", "Austin, TX" in r and "{metro}" not in r)
    check("needs_lead detects address", _needs_lead('"{address}" foreclosure'))
    check("needs_lead false for metro-only", not _needs_lead('selling {metro}'))

    # evidence_match: keyword hit on a reddit link is found with decent confidence
    sig = {"kind": "social_listening", "evidence_keywords": ["realtor", "recommend"]}
    found, conf = evidence_match(
        sig, {"title": "Recommend a realtor in Austin?", "snippet": "looking for an agent",
              "link": "https://reddit.com/r/Austin/x"})
    check(f"evidence found on reddit ({conf})", found and conf >= 0.4)
    # no keyword -> not found
    nf, _ = evidence_match(sig, {"title": "weather today", "snippet": "", "link": "https://x"})
    check("evidence not found without keyword", not nf)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="scan a metro for an agent-client")
    p_run.add_argument("--profile", required=True)
    p_run.add_argument("--metro", required=True)
    p_run.add_argument("--pack", default=None)
    p_run.add_argument("--geos", default=None, help="comma geos override e.g. US")
    p_run.add_argument("--limit", type=int, default=40)
    p_run.add_argument("--max-per-query", type=int, default=8)
    p_run.add_argument("--store-db", action="store_true",
                       help="also insert into the intent_signals table (needs migration 009)")
    p_run.add_argument("--enrich-addresses", action="store_true",
                       help="fetch public-record result pages and extract property addresses")
    p_run.add_argument("--dry", action="store_true")

    sub.add_parser("packs", help="list available signal packs")
    sub.add_parser("selftest", help="offline checks (no network/DB)")

    args = ap.parse_args()
    if args.cmd == "packs":
        for pid in spl.list_packs():
            try:
                p = spl.load_pack(pid)
                print(f"  {pid:30s} {p['audience']:4s} {p['jurisdiction']:3s} "
                      f"{len(p['signals'])} signals")
            except spl.SignalPackError as e:
                print(f"  {pid:30s} INVALID: {e}")
        return 0
    if args.cmd == "selftest":
        return _selftest()
    if args.cmd == "run":
        geos = [g.strip() for g in args.geos.split(",")] if args.geos else None
        run_pack(args.profile, args.metro, pack_id=args.pack, dry=args.dry,
                 limit=args.limit, max_per_query=args.max_per_query, geos_override=geos,
                 store_db=args.store_db, enrich_addresses=args.enrich_addresses)
        return 0


if __name__ == "__main__":
    sys.exit(main())
