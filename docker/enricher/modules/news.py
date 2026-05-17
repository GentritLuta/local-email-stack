"""news — search SearXNG for news + press + podcast mentions of a person/company."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("enricher.news")


async def search(searxng_url: str, person: str, company: str) -> dict:
    out: dict = {"news_mentions": [], "podcast_appearances": [], "press": [], "interviews": []}
    queries = []
    if company:
        queries.append((f'"{company}" news',                "news_mentions"))
        queries.append((f'"{company}" press',               "press"))
        queries.append((f'"{company}" interview',           "interviews"))
        queries.append((f'"{company}" podcast guest',       "podcast_appearances"))
    if person:
        queries.append((f'"{person}" podcast',              "podcast_appearances"))
        queries.append((f'"{person}" interview',            "interviews"))

    async with httpx.AsyncClient(timeout=20) as c:
        for q, bucket in queries:
            try:
                r = await c.get(
                    f"{searxng_url}/search",
                    params={"q": q, "format": "json", "categories": "general"},
                )
                if r.status_code != 200:
                    continue
                for item in (r.json().get("results") or [])[:6]:
                    out[bucket].append({
                        "url": item.get("url"),
                        "title": item.get("title"),
                        "snippet": item.get("content", "")[:300],
                        "engine": item.get("engine"),
                    })
            except Exception as ex:
                logger.debug("searxng %s failed: %s", q, ex)
    # Dedup each bucket by URL
    for k in out:
        seen = set()
        deduped = []
        for it in out[k]:
            if it["url"] in seen:
                continue
            seen.add(it["url"])
            deduped.append(it)
        out[k] = deduped[:5]
    return out
