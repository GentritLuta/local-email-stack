"""reddit_user — find Reddit users active in target subreddits.

Uses PRAW with a Reddit script-type app (free; create at
https://www.reddit.com/prefs/apps).

Config:
  subreddits:        [list of subreddit names without "r/"]
  min_karma:         int (combined link+comment)
  recent_post_days:  int
  bio_keywords:      [list] (post-hoc filter on user.profile.subreddit description)
  limit:             int
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.reddit_user")


@register("reddit_user")
class RedditUserEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        try:
            import praw
        except ImportError:
            logger.error("praw not installed; reddit_user engine disabled")
            return []
        cid = os.environ.get("REDDIT_CLIENT_ID")
        csecret = os.environ.get("REDDIT_CLIENT_SECRET")
        agent = os.environ.get("REDDIT_USER_AGENT", "local-email-stack/4.0")
        if not (cid and csecret):
            logger.warning("REDDIT_CLIENT_ID/SECRET unset; reddit_user disabled")
            return []

        subs = config.get("subreddits") or []
        min_karma = int(config.get("min_karma", 100))
        recent_days = int(config.get("recent_post_days", 30))
        bio_kws = [k.lower() for k in config.get("bio_keywords") or []]
        limit = int(config.get("limit", 100))
        cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)

        def blocking_search() -> list[Lead]:
            reddit = praw.Reddit(client_id=cid, client_secret=csecret, user_agent=agent)
            out: dict[str, Lead] = {}
            for sub_name in subs:
                try:
                    sub = reddit.subreddit(sub_name)
                    for s in sub.new(limit=200):
                        if not s.author:
                            continue
                        name = s.author.name
                        if name in out:
                            continue
                        ts = datetime.fromtimestamp(s.created_utc, tz=timezone.utc)
                        if ts < cutoff:
                            continue
                        try:
                            u = reddit.redditor(name)
                            karma = (u.link_karma or 0) + (u.comment_karma or 0)
                            if karma < min_karma:
                                continue
                            bio = ""
                            try:
                                bio = (u.subreddit.public_description or "").lower()
                            except Exception:
                                pass
                            if bio_kws and not any(k in bio for k in bio_kws):
                                continue
                            out[name] = Lead(
                                source="reddit_user",
                                source_id=name,
                                handle=name,
                                display_name=name,
                                bio=bio,
                                url=f"https://reddit.com/user/{name}",
                                follower_count=karma,
                                extra={
                                    "link_karma": u.link_karma,
                                    "comment_karma": u.comment_karma,
                                    "discovered_via_subreddit": sub_name,
                                    "created_utc": u.created_utc,
                                },
                            )
                            if len(out) >= limit:
                                return list(out.values())
                        except Exception:
                            continue
                except Exception as ex:
                    logger.exception("reddit sub %s failed: %s", sub_name, ex)
            return list(out.values())

        return await asyncio.to_thread(blocking_search)
