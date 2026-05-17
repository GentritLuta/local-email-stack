"""tiktok_creator — find TikTok creators by hashtag + engagement + recency.

Uses TikTokApi (https://github.com/davidteather/TikTok-Api). Needs Playwright.

Config:
  hashtags:                 [list]
  min_followers:            int
  min_engagement_rate:      float (likes+comments+shares / followers, avg over recent N)
  recent_posts_within_days: int
  limit:                    int
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.tiktok_creator")


@register("tiktok_creator")
class TikTokCreatorEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        try:
            from TikTokApi import TikTokApi
        except ImportError:
            logger.error("TikTokApi not installed; tiktok_creator disabled")
            return []
        hashtags = config.get("hashtags") or []
        min_followers = int(config.get("min_followers", 1000))
        min_eng = float(config.get("min_engagement_rate", 0.02))
        recent_days = int(config.get("recent_posts_within_days", 14))
        limit = int(config.get("limit", 100))
        cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)

        results: dict[str, Lead] = {}
        async with TikTokApi() as api:
            await api.create_sessions(num_sessions=1, sleep_after=3, headless=True)
            for tag in hashtags:
                try:
                    ht = api.hashtag(name=tag.lstrip("#"))
                    async for video in ht.videos(count=200):
                        author = video.author
                        if not author or author.username in results:
                            continue
                        ainfo = await author.info()
                        stats = ainfo.get("stats", {})
                        followers = stats.get("followerCount", 0)
                        if followers < min_followers:
                            continue
                        avg_likes = stats.get("heartCount", 0) / max(stats.get("videoCount", 1), 1)
                        eng = avg_likes / max(followers, 1)
                        if eng < min_eng:
                            continue
                        # Recency: video.create_time
                        ts = datetime.fromtimestamp(video.create_time or 0, tz=timezone.utc)
                        if ts < cutoff:
                            continue
                        u = ainfo.get("user", {})
                        results[author.username] = Lead(
                            source="tiktok_creator",
                            source_id=u.get("id", author.username),
                            handle=author.username,
                            display_name=u.get("nickname", ""),
                            bio=u.get("signature", ""),
                            url=f"https://tiktok.com/@{author.username}",
                            follower_count=followers,
                            extra={
                                "video_count": stats.get("videoCount"),
                                "heart_count": stats.get("heartCount"),
                                "engagement_rate": eng,
                                "discovered_via_hashtag": tag,
                                "verified": u.get("verified"),
                                "bio_link": u.get("bioLink"),
                            },
                        )
                        if len(results) >= limit:
                            break
                except Exception as ex:
                    logger.exception("TikTok hashtag %s failed: %s", tag, ex)
                if len(results) >= limit:
                    break
        return list(results.values())[:limit]
