"""context_enrich.py — given a prospect's company URL (or email domain), pull
back the structured business context we need to write a credible pitch:

  * product summary (what they sell, in one line)
  * value prop / hero copy
  * pricing tiers (regex over price tables and pricing-page text)
  * user / customer count (regex like "75,000+ traders")
  * target customer (heuristic from copy)
  * key value-prop bullets (the first 3-5 short paragraphs that look like a feature list)
  * case studies / outcome numbers ("up 89%", "+ $340k", etc.)
  * social links (twitter / x / linkedin / youtube / instagram)
  * pages fetched + scraped_at timestamp

Heuristic-only (no LLM, no API costs). Visits the homepage + the first
matching /pricing / /about / /product subpage, parses inline metadata, runs
deterministic regexes. Returns a dict — the orchestrator writes it to
`prospects.enriched_context`. Re-runs are idempotent.

CLI (for ad-hoc):
    py sequences/context_enrich.py https://algoalpha.io
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

USER_AGENT = "Mozilla/5.0 LocalEmailStack/0.4 context-enrich"

PRICE_RX = re.compile(
    r"(?:\$|€|£|USD\s*|EUR\s*)\d{1,3}(?:[.,]\d{2,3})?(?:\s*/\s*(?:mo|month|yr|year|user|seat))?",
    re.I,
)
USER_COUNT_RX = re.compile(
    r"\b\d{1,3}(?:[,.\s]\d{3})+\+?\s*(?:active\s+)?(?:users|customers|traders|members|subscribers|agents|clients|teams|sellers|buyers)\b",
    re.I,
)
OUTCOME_RX = re.compile(
    r"(?:from\s+\d[\d.,]*\s+to\s+\d[\d.,]*|up\s+\d+\s*%|\+\s*\d+\s*%|\d+\s*x\s+(?:more|higher|better)|"
    r"saved?\s+\$?\d|added\s+\$?\d|generated\s+\$?\d|\d+\s*hours?\s+saved)",
    re.I,
)
SOCIAL_RX = re.compile(
    r"https?://(?:www\.)?"
    r"(?:twitter\.com|x\.com|linkedin\.com|youtube\.com|instagram\.com|facebook\.com|github\.com|tiktok\.com|threads\.net)/[^\s\"'<>)]+",
    re.I,
)

CANDIDATE_SUBPAGES = ["/pricing", "/plans", "/about", "/product", "/products", "/features", "/how-it-works"]


@dataclass
class EnrichedContext:
    product_summary:   str = ""
    value_prop:        str = ""
    pricing_samples:   list[str] = field(default_factory=list)
    user_count:        Optional[str] = None
    target_customer:   str = ""
    key_bullets:       list[str] = field(default_factory=list)
    outcome_snippets:  list[str] = field(default_factory=list)
    social_links:      dict[str, str] = field(default_factory=dict)
    pages_fetched:     list[str] = field(default_factory=list)
    source_url:        str = ""
    scraped_at:        str = ""


def _fetch(url: str, timeout: int = 20) -> Optional[str]:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT,
                                   "Accept": "text/html,application/xhtml+xml"}) as c:
            r = c.get(url)
            if r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""):
                return r.text
    except Exception:
        return None
    return None


def _extract_from(html: str, ctx: EnrichedContext) -> None:
    """Run all heuristics over one fetched page, merging into ctx in-place."""
    soup = BeautifulSoup(html, "lxml")

    # 1. Product summary: og:description > meta description > first H1
    if not ctx.product_summary:
        og = soup.find("meta", property="og:description")
        if og and og.get("content"):
            ctx.product_summary = og["content"].strip()[:240]
    if not ctx.product_summary:
        md = soup.find("meta", attrs={"name": "description"})
        if md and md.get("content"):
            ctx.product_summary = md["content"].strip()[:240]
    if not ctx.product_summary:
        h1 = soup.find("h1")
        if h1: ctx.product_summary = h1.get_text(" ", strip=True)[:240]

    # 2. Value prop: the first <p> after the first heading
    if not ctx.value_prop:
        first_h = soup.find(["h1", "h2"])
        if first_h:
            sib = first_h.find_next(["p", "h2", "h3"])
            while sib is not None:
                if sib.name == "p":
                    txt = sib.get_text(" ", strip=True)
                    if 20 < len(txt) < 280:
                        ctx.value_prop = txt; break
                sib = sib.find_next(["p", "h2", "h3"])

    # 3. Pricing samples — dedupe, cap at 8
    seen_prices = set(ctx.pricing_samples)
    for m in PRICE_RX.finditer(soup.get_text(" ", strip=True)):
        p = m.group(0).strip()
        if p not in seen_prices and len(seen_prices) < 8:
            seen_prices.add(p); ctx.pricing_samples.append(p)

    # 4. User / customer count — first match wins
    if not ctx.user_count:
        m = USER_COUNT_RX.search(soup.get_text(" ", strip=True))
        if m: ctx.user_count = m.group(0).strip()

    # 5. Target customer — look for "for [adjective] [noun]" patterns near top
    if not ctx.target_customer:
        top_text = soup.get_text(" ", strip=True)[:1200]
        m = re.search(r"\bfor\s+(?:active\s+|professional\s+|busy\s+|growing\s+|serious\s+)?"
                      r"([a-z]+(?:\s+[a-z]+){0,3})\s+(?:traders|investors|agents|brokers|teams|"
                      r"businesses|founders|companies|creators|operators|owners|professionals|"
                      r"firms|brokerages|developers|marketers)\b",
                      top_text, re.I)
        if m: ctx.target_customer = m.group(0).strip()[:120]

    # 6. Key bullets — short <li>'s in the first 2 lists, often the feature row
    if len(ctx.key_bullets) < 5:
        for ul in soup.find_all(["ul", "ol"], limit=4):
            for li in ul.find_all("li", limit=8):
                t = li.get_text(" ", strip=True)
                if 8 < len(t) < 140 and t not in ctx.key_bullets:
                    ctx.key_bullets.append(t)
                    if len(ctx.key_bullets) >= 8: break
            if len(ctx.key_bullets) >= 8: break

    # 7. Outcome snippets (case studies, numbers, deltas)
    text = soup.get_text(" ", strip=True)
    for m in OUTCOME_RX.finditer(text):
        start = max(0, m.start() - 80); end = min(len(text), m.end() + 80)
        snippet = text[start:end].strip()
        # tighten to one sentence containing the match
        bits = re.split(r"(?<=[.!?])\s+", snippet)
        best = next((b for b in bits if m.group(0).lower() in b.lower()), snippet)
        best = best.strip()[:200]
        if best not in ctx.outcome_snippets and len(ctx.outcome_snippets) < 6:
            ctx.outcome_snippets.append(best)

    # 8. Social links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if SOCIAL_RX.match(href):
            host = urlparse(href).hostname or ""
            key = host.replace("www.", "").split(".")[0]
            if key and key not in ctx.social_links:
                ctx.social_links[key] = href


def enrich(url_or_email: str) -> Optional[EnrichedContext]:
    """Main entry point. Accepts a full URL or a bare email address (whose
    domain is treated as https://<domain>)."""
    if "@" in url_or_email:
        base = "https://" + url_or_email.split("@", 1)[1]
    else:
        base = url_or_email if url_or_email.startswith(("http://", "https://")) else f"https://{url_or_email}"

    ctx = EnrichedContext(source_url=base,
                          scraped_at=dt.datetime.utcnow().isoformat() + "Z")

    homepage = _fetch(base)
    if homepage is None: return None
    ctx.pages_fetched.append(base)
    _extract_from(homepage, ctx)

    # Try the first subpage that actually exists. Stop after one hit — we are
    # not crawling, just one extra page for richer pricing/about context.
    parsed = urlparse(base)
    root = f"{parsed.scheme}://{parsed.netloc}"
    for sub in CANDIDATE_SUBPAGES:
        url = root + sub
        body = _fetch(url)
        if body:
            ctx.pages_fetched.append(url)
            _extract_from(body, ctx)
            break

    return ctx


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url", help="company URL or email address")
    args = ap.parse_args()
    ctx = enrich(args.url)
    if ctx is None:
        print("fetch failed"); return 2
    print(json.dumps(asdict(ctx), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
