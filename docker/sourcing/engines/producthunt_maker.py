"""producthunt_maker — find recent Product Hunt makers via the public GraphQL API.

Free dev token at https://api.producthunt.com/v2/docs.

Config:
  categories:               [list of slugs, e.g. ["saas", "developer-tools"]]
  launched_in_last_days:    int
  limit:                    int
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.producthunt_maker")
PH_TOKEN = os.environ.get("PRODUCTHUNT_TOKEN", "")


@register("producthunt_maker")
class ProductHuntMakerEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        if not PH_TOKEN:
            logger.warning("PRODUCTHUNT_TOKEN unset; engine disabled")
            return []
        categories = config.get("categories") or []
        days = int(config.get("launched_in_last_days", 365))
        limit = int(config.get("limit", 100))
        since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        query = """
        query($topic: String, $after: DateTime) {
          posts(topic: $topic, postedAfter: $after, first: 50) {
            edges { node { id name slug tagline url
              makers { id name username headline twitterUsername websiteUrl } } }
          }
        }
        """

        results: dict[str, Lead] = {}
        async with httpx.AsyncClient(timeout=30) as c:
            for cat in categories or [None]:
                try:
                    r = await c.post(
                        "https://api.producthunt.com/v2/api/graphql",
                        headers={"Authorization": f"Bearer {PH_TOKEN}", "Content-Type": "application/json"},
                        json={"query": query, "variables": {"topic": cat, "after": since}},
                    )
                    if r.status_code != 200:
                        logger.warning("PH returned %s", r.status_code)
                        continue
                    edges = r.json().get("data", {}).get("posts", {}).get("edges", []) or []
                    for e in edges:
                        post = e.get("node", {}) or {}
                        for m in post.get("makers", []) or []:
                            uid = str(m.get("id", ""))
                            if not uid or uid in results:
                                continue
                            results[uid] = Lead(
                                source="producthunt_maker",
                                source_id=uid,
                                handle=m.get("username", ""),
                                display_name=m.get("name", ""),
                                bio=m.get("headline", ""),
                                url=m.get("websiteUrl") or f"https://www.producthunt.com/@{m.get('username','')}",
                                extra={
                                    "twitter": m.get("twitterUsername"),
                                    "product": post.get("name"),
                                    "product_url": post.get("url"),
                                    "tagline": post.get("tagline"),
                                    "category": cat,
                                },
                            )
                            if len(results) >= limit:
                                break
                        if len(results) >= limit:
                            break
                except Exception as ex:
                    logger.exception("PH category %s failed: %s", cat, ex)
                if len(results) >= limit:
                    break
        return list(results.values())[:limit]
