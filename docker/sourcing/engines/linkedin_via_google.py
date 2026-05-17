"""linkedin_via_google — find LinkedIn profiles by searching Google's index.

Avoids LinkedIn's hostile anti-scraping by going through the SearXNG meta-search
service (which uses Google + Bing + DDG behind the scenes, free, self-hosted).

Config:
  titles:                   [list of role strings, e.g. ["CEO", "Founder", "CTO"]]
  company_size_keywords:    [list of strings, e.g. ["startup", "series-a", "seed"]]
  industry_keywords:        [list of strings, e.g. ["fintech", "saas", "ai"]]
  location_keywords:        [list of strings, optional]
  limit:                    int
"""

from __future__ import annotations

import logging
import os
import re

import httpx

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.linkedin_via_google")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")
PROFILE_URL_RE = re.compile(r"https?://(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9\-_%]+/?")


@register("linkedin_via_google")
class LinkedInViaGoogleEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        titles = config.get("titles") or []
        company_kws = config.get("company_size_keywords") or []
        industry_kws = config.get("industry_keywords") or []
        location_kws = config.get("location_keywords") or []
        limit = int(config.get("limit", 100))

        results: dict[str, Lead] = {}
        async with httpx.AsyncClient(timeout=30) as c:
            for title in titles or [""]:
                for industry in industry_kws or [""]:
                    q_parts = ["site:linkedin.com/in/"]
                    if title:
                        q_parts.append(f'"{title}"')
                    if industry:
                        q_parts.append(f'"{industry}"')
                    for ck in company_kws:
                        q_parts.append(f'"{ck}"')
                    for lk in location_kws:
                        q_parts.append(f'"{lk}"')
                    q = " ".join(q_parts)
                    try:
                        r = await c.get(
                            f"{SEARXNG_URL}/search",
                            params={"q": q, "format": "json", "categories": "general"},
                        )
                        if r.status_code != 200:
                            logger.warning("searxng returned %s", r.status_code)
                            continue
                        for item in r.json().get("results", []):
                            url = item.get("url") or ""
                            m = PROFILE_URL_RE.match(url)
                            if not m:
                                continue
                            slug = url.rstrip("/").split("/in/")[-1]
                            if slug in results:
                                continue
                            results[slug] = Lead(
                                source="linkedin_via_google",
                                source_id=slug,
                                handle=slug,
                                display_name=item.get("title", "").split(" - ")[0],
                                bio=item.get("content", ""),
                                url=url.rstrip("/"),
                                extra={
                                    "search_query": q,
                                    "raw_title": item.get("title"),
                                },
                            )
                            if len(results) >= limit:
                                break
                    except Exception as ex:
                        logger.exception("searxng search failed: %s", ex)
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break

        return list(results.values())[:limit]
