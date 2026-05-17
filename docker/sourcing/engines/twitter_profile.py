"""twitter_profile — find X/Twitter accounts matching bio keywords + follower threshold.

Uses twscrape (https://github.com/vladkens/twscrape) which works without an X API
subscription. Requires throwaway X accounts in twscrape's local SQLite store; bootstrap
script seeds them from TWSCRAPE_ACCOUNTS env var (a JSON array of {username,password,
email,email_password,...} dicts).

Config schema:
  bio_keywords:           [list of strings — must appear in bio]
  exclude_bio_keywords:   [list of strings — must NOT appear]
  min_followers:          int
  max_followers:          int (optional — drop mega-accounts)
  recent_post_within_days: int (optional — activity filter)
  language:               str (optional, e.g. "en")
  limit:                  int
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.twitter_profile")


@register("twitter_profile")
class TwitterProfileEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        try:
            from twscrape import API
        except ImportError:
            logger.error("twscrape not installed; cannot run twitter_profile engine")
            return []

        bio_kws: list[str] = config.get("bio_keywords") or []
        excl_kws: list[str] = [k.lower() for k in config.get("exclude_bio_keywords") or []]
        min_followers = int(config.get("min_followers", 0))
        max_followers = int(config.get("max_followers", 10**9))
        recent_days = config.get("recent_post_within_days")
        lang = config.get("language")
        limit = int(config.get("limit", 100))

        api = API()  # uses DB at ./twscrape.db by default
        results: dict[str, Lead] = {}
        cutoff = None
        if recent_days:
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(recent_days))

        # Strategy: for each bio keyword, run a User search; merge results; filter.
        for kw in bio_kws or ["founder"]:  # always have at least one search term
            try:
                async for user in api.search_user(kw, limit=limit * 3):
                    if user.id_str in results:
                        continue
                    bio = (user.rawDescription or "").lower()
                    if any(x in bio for x in excl_kws):
                        continue
                    if user.followersCount < min_followers or user.followersCount > max_followers:
                        continue
                    if lang and (user.profile_lang or "").lower() != lang.lower():
                        continue
                    if cutoff:
                        # cheap freshness: check user's most recent tweet if cached
                        try:
                            tweets = []
                            async for t in api.user_tweets(user.id, limit=1):
                                tweets.append(t)
                            if tweets and tweets[0].date < cutoff:
                                continue
                        except Exception:
                            pass
                    results[user.id_str] = Lead(
                        source="twitter_profile",
                        source_id=user.id_str,
                        handle=user.username,
                        display_name=user.displayname,
                        bio=user.rawDescription or "",
                        url=f"https://x.com/{user.username}",
                        location=user.location or "",
                        follower_count=user.followersCount,
                        extra={
                            "verified": user.verified,
                            "tweets_count": user.statusesCount,
                            "joined": str(user.created),
                            "profile_url": user.profileImageUrl,
                        },
                    )
                    if len(results) >= limit:
                        break
            except Exception as ex:
                logger.exception("twscrape search failed for %s: %s", kw, ex)
            if len(results) >= limit:
                break
        return list(results.values())[:limit]
