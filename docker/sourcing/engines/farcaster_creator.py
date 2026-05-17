"""farcaster_creator — find Farcaster users by channel + bio + activity.

Uses Neynar's free hub API. Sign up at https://dev.neynar.com (free tier
covers ~250k req/mo). Set NEYNAR_API_KEY in env.

Config:
  channels:           [list of channel parent_urls or channel ids]
  bio_keywords:       [list of strings] (post-hoc filter)
  min_followers:      int
  recent_cast_days:   int (default 14)
  limit:              int (default 200)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.farcaster_creator")
NEYNAR_KEY = os.environ.get("NEYNAR_API_KEY", "")


@register("farcaster_creator")
class FarcasterCreatorEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        if not NEYNAR_KEY:
            logger.warning("NEYNAR_API_KEY unset; farcaster engine disabled")
            return []

        channels = config.get("channels") or []
        bio_kws = [k.lower() for k in config.get("bio_keywords") or []]
        min_followers = int(config.get("min_followers", 100))
        recent_days = int(config.get("recent_cast_days", 14))
        limit = int(config.get("limit", 200))

        cutoff = datetime.now(timezone.utc) - timedelta(days=recent_days)
        headers = {"accept": "application/json", "api_key": NEYNAR_KEY}
        results: dict[str, Lead] = {}

        async with httpx.AsyncClient(timeout=30, headers=headers) as c:
            for ch in channels:
                # GET /v2/farcaster/feed/channels?channel_ids=&with_recasts=false&limit=100
                try:
                    r = await c.get(
                        "https://api.neynar.com/v2/farcaster/feed/channels",
                        params={"channel_ids": ch, "limit": 100, "with_recasts": "false"},
                    )
                    if r.status_code != 200:
                        logger.warning("neynar feed %s returned %s", ch, r.status_code)
                        continue
                    casts = r.json().get("casts", [])
                    for cast in casts:
                        author = cast.get("author", {}) or {}
                        fid = str(author.get("fid", ""))
                        if not fid or fid in results:
                            continue
                        if author.get("follower_count", 0) < min_followers:
                            continue
                        bio = (author.get("profile", {}).get("bio", {}).get("text") or "").lower()
                        if bio_kws and not any(k in bio for k in bio_kws):
                            continue
                        ts = cast.get("timestamp")
                        if ts:
                            try:
                                if datetime.fromisoformat(ts.replace("Z", "+00:00")) < cutoff:
                                    continue
                            except Exception:
                                pass
                        results[fid] = Lead(
                            source="farcaster_creator",
                            source_id=fid,
                            handle=author.get("username", ""),
                            display_name=author.get("display_name", ""),
                            bio=bio,
                            url=f"https://warpcast.com/{author.get('username','')}",
                            follower_count=author.get("follower_count"),
                            extra={
                                "fid": fid,
                                "channel_seen_in": ch,
                                "power_badge": author.get("power_badge"),
                                "verifications": author.get("verifications"),
                            },
                        )
                        if len(results) >= limit:
                            break
                except Exception as ex:
                    logger.exception("neynar channel %s failed: %s", ch, ex)
                if len(results) >= limit:
                    break

        return list(results.values())[:limit]
