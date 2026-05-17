"""bluesky_user — find Bluesky (AT Protocol) users by feed + bio keyword.

Uses the public AppView API at api.bsky.app. No auth required for public reads.

Config:
  feeds:           [list of feed AT-URIs OR custom feed names]
  bio_keywords:    [list of strings]
  min_followers:   int
  limit:           int
"""

from __future__ import annotations

import logging

import httpx

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.bluesky_user")


@register("bluesky_user")
class BlueskyUserEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        feeds = config.get("feeds") or []
        bio_kws = [k.lower() for k in config.get("bio_keywords") or []]
        min_followers = int(config.get("min_followers", 100))
        limit = int(config.get("limit", 100))

        results: dict[str, Lead] = {}
        async with httpx.AsyncClient(timeout=30) as c:
            for feed in feeds:
                try:
                    # Use the popular "What's Hot" or custom feeds
                    r = await c.get(
                        "https://api.bsky.app/xrpc/app.bsky.feed.getFeed",
                        params={"feed": feed, "limit": 100},
                    )
                    if r.status_code != 200:
                        logger.warning("bsky feed %s returned %s", feed, r.status_code)
                        continue
                    for item in r.json().get("feed", []):
                        author = item.get("post", {}).get("author", {}) or {}
                        did = author.get("did")
                        handle = author.get("handle", "")
                        if not did or handle in results:
                            continue
                        # Fetch profile for follower count + bio
                        pr = await c.get(
                            "https://api.bsky.app/xrpc/app.bsky.actor.getProfile",
                            params={"actor": handle},
                        )
                        if pr.status_code != 200:
                            continue
                        p = pr.json()
                        followers = p.get("followersCount", 0)
                        if followers < min_followers:
                            continue
                        bio = (p.get("description") or "").lower()
                        if bio_kws and not any(k in bio for k in bio_kws):
                            continue
                        results[handle] = Lead(
                            source="bluesky_user",
                            source_id=did,
                            handle=handle,
                            display_name=p.get("displayName", handle),
                            bio=p.get("description") or "",
                            url=f"https://bsky.app/profile/{handle}",
                            follower_count=followers,
                            extra={
                                "did": did,
                                "discovered_via_feed": feed,
                                "posts_count": p.get("postsCount"),
                            },
                        )
                        if len(results) >= limit:
                            break
                except Exception as ex:
                    logger.exception("bsky feed %s failed: %s", feed, ex)
                if len(results) >= limit:
                    break
        return list(results.values())[:limit]
