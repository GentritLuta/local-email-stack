"""instagram_profile — find IG profiles by hashtag + bio keyword + followers.

Uses instaloader. Needs throwaway IG credentials in INSTAGRAM_USERNAME/PASSWORD env.

Config:
  hashtags:          [list]
  bio_keywords:      [list]
  min_followers:     int
  max_followers:     int
  limit:             int
"""

from __future__ import annotations

import asyncio
import logging
import os

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.instagram_profile")


@register("instagram_profile")
class InstagramProfileEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        try:
            import instaloader
        except ImportError:
            logger.error("instaloader not installed; instagram_profile disabled")
            return []
        user = os.environ.get("INSTAGRAM_USERNAME", "")
        pw = os.environ.get("INSTAGRAM_PASSWORD", "")
        hashtags = config.get("hashtags") or []
        bio_kws = [k.lower() for k in config.get("bio_keywords") or []]
        min_f = int(config.get("min_followers", 0))
        max_f = int(config.get("max_followers", 10**9))
        limit = int(config.get("limit", 100))

        def blocking() -> list[Lead]:
            L = instaloader.Instaloader(quiet=True, download_pictures=False,
                                        download_videos=False, download_comments=False,
                                        save_metadata=False)
            try:
                if user and pw:
                    L.login(user, pw)
            except Exception as ex:
                logger.warning("IG login failed: %s (continuing anonymously)", ex)
            results: dict[str, Lead] = {}
            for tag in hashtags:
                try:
                    ht = instaloader.Hashtag.from_name(L.context, tag.lstrip("#"))
                    for post in ht.get_top_posts():
                        owner = post.owner_username
                        if owner in results:
                            continue
                        try:
                            p = instaloader.Profile.from_username(L.context, owner)
                        except Exception:
                            continue
                        if p.followers < min_f or p.followers > max_f:
                            continue
                        bio = (p.biography or "").lower()
                        if bio_kws and not any(k in bio for k in bio_kws):
                            continue
                        results[owner] = Lead(
                            source="instagram_profile",
                            source_id=str(p.userid),
                            handle=owner,
                            display_name=p.full_name or owner,
                            bio=p.biography or "",
                            url=f"https://instagram.com/{owner}",
                            follower_count=p.followers,
                            extra={
                                "business_category": p.business_category_name,
                                "external_url": p.external_url,
                                "is_verified": p.is_verified,
                                "discovered_via_hashtag": tag,
                            },
                        )
                        if len(results) >= limit:
                            return list(results.values())
                except Exception as ex:
                    logger.exception("IG hashtag %s failed: %s", tag, ex)
            return list(results.values())

        return await asyncio.to_thread(blocking)
