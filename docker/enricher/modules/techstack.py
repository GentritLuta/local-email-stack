"""techstack — detect CMS, analytics, marketing, frontend, hosting from page HTML.

Heuristic detector inspired by Wappalyzer's open rules. Lightweight; pure regex.
Walks already-crawled pages (no extra HTTP) so it's near-zero cost.
"""

from __future__ import annotations

import re
from typing import Iterable

SIGNATURES: dict[str, dict[str, list[str]]] = {
    "cms": {
        "WordPress":     [r"wp-content/", r"wp-includes/", r"<meta name=.generator. content=.WordPress"],
        "Webflow":       [r"webflow\.com", r"data-wf-page"],
        "Squarespace":   [r"squarespace\.com", r"static1\.squarespace\.com"],
        "Wix":           [r"static\.parastorage\.com", r"wix\.com"],
        "Shopify":       [r"cdn\.shopify\.com", r"Shopify\.theme"],
        "Ghost":         [r"<meta name=.generator. content=.Ghost"],
        "HubSpot CMS":   [r"hs-scripts\.com", r"hubspot\.com"],
        "Notion":        [r"notion\.so", r"notion\.site"],
        "Framer":        [r"framer\.com", r"data-framer"],
    },
    "analytics": {
        "Google Analytics 4": [r"gtag\(['\"]config['\"], ['\"]G-", r"www\.googletagmanager\.com/gtag/js"],
        "Google Tag Manager": [r"googletagmanager\.com/gtm\.js"],
        "Plausible":          [r"plausible\.io/js"],
        "Fathom":             [r"fathom\.com/script"],
        "Mixpanel":           [r"cdn\.mxpnl\.com"],
        "PostHog":            [r"posthog\.com/", r"posthog\.init"],
        "Segment":            [r"cdn\.segment\.com/analytics\.js"],
        "Heap":               [r"cdn\.heapanalytics\.com"],
    },
    "marketing": {
        "HubSpot":   [r"js\.hs-scripts\.com", r"js\.hsforms\.net"],
        "Mailchimp": [r"chimpstatic\.com", r"mc\.us"],
        "Intercom":  [r"widget\.intercom\.io"],
        "Drift":     [r"js\.driftt\.com"],
        "Crisp":     [r"client\.crisp\.chat"],
        "Tidio":     [r"code\.tidio\.co"],
        "Klaviyo":   [r"static\.klaviyo\.com"],
        "ActiveCampaign": [r"activehosted\.com"],
    },
    "frontend": {
        "React":   [r"_next/static/", r"data-reactroot", r'"react":"'],
        "Next.js": [r"_next/static/", r"__NEXT_DATA__"],
        "Vue":     [r"data-v-[a-z0-9]+", r'"vue":"'],
        "Nuxt":    [r"_nuxt/"],
        "Svelte":  [r"svelte-[a-z0-9]+"],
        "Angular": [r"ng-version="],
    },
    "hosting_cdn": {
        "Cloudflare": [r"cf-ray", r"__cf_bm"],
        "Vercel":     [r"x-vercel-id", r"vercel\.app"],
        "Netlify":    [r"netlify\.app", r"x-nf-request-id"],
        "GitHub Pages": [r"github\.io"],
        "AWS CloudFront": [r"x-amz-cf-id", r"cloudfront\.net"],
        "Fastly":     [r"x-fastly", r"fastly\.net"],
    },
}


def _join_haystack(pages: dict) -> str:
    chunks: list[str] = []
    for p in pages.values():
        for k in ("clean_text", "title", "description"):
            v = p.get(k)
            if isinstance(v, str):
                chunks.append(v)
        for ln in (p.get("links") or []):
            chunks.append(str(ln))
    return "\n".join(chunks)


async def detect(website: str, pages: dict) -> dict:
    """Note: detection runs against the text we already have. For full accuracy we'd
    re-fetch raw HTML, but the cost-vs-signal tradeoff isn't worth it at our scale."""
    hay = _join_haystack(pages)
    out: dict[str, list[str]] = {k: [] for k in SIGNATURES.keys()}
    for category, sigs in SIGNATURES.items():
        for name, patterns in sigs.items():
            for pat in patterns:
                if re.search(pat, hay, re.I):
                    out[category].append(name)
                    break
    # dedupe + sort
    return {k: sorted(set(v)) for k, v in out.items() if v}
