"""youtube_channel — find YouTube channels by search query + sub threshold + recency.

Uses yt-dlp (which works on YouTube's public search/channel surfaces without
API quota). For each search query, fetches the top-N results, filters by sub
count + upload recency + country bias.

Config:
  search_queries:           [list of strings]
  min_subscribers:          int
  max_subscribers:          int (optional)
  uploaded_in_last_days:    int (optional, recency filter)
  country_bias:             [list of ISO-2 country codes, optional]
  limit:                    int
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.youtube_channel")


def _parse_sub_count(s: str | int | None) -> int | None:
    if s is None:
        return None
    if isinstance(s, int):
        return s
    s = str(s).lower().replace(",", "").strip()
    mult = 1
    if s.endswith("k"):
        mult, s = 1_000, s[:-1]
    elif s.endswith("m"):
        mult, s = 1_000_000, s[:-1]
    elif s.endswith("b"):
        mult, s = 1_000_000_000, s[:-1]
    try:
        return int(float(s) * mult)
    except Exception:
        return None


@register("youtube_channel")
class YouTubeChannelEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        try:
            from yt_dlp import YoutubeDL
        except ImportError:
            logger.error("yt-dlp not installed; cannot run youtube_channel engine")
            return []

        queries: list[str] = config.get("search_queries") or []
        min_subs = int(config.get("min_subscribers", 0))
        max_subs = int(config.get("max_subscribers", 10**12))
        uploaded_within = config.get("uploaded_in_last_days")
        country_bias: list[str] = [c.upper() for c in (config.get("country_bias") or [])]
        limit = int(config.get("limit", 100))

        cutoff = None
        if uploaded_within:
            cutoff = datetime.now(timezone.utc) - timedelta(days=int(uploaded_within))

        opts = {
            "quiet": True,
            "extract_flat": "in_playlist",
            "skip_download": True,
            "no_warnings": True,
            "default_search": "ytsearch",
        }

        results: dict[str, Lead] = {}

        def blocking_search(q: str) -> list[dict]:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(f"ytsearch{limit*2}:{q}", download=False)
                return info.get("entries", []) or []

        for q in queries:
            try:
                entries = await asyncio.to_thread(blocking_search, q)
                for e in entries:
                    ch_id = e.get("channel_id") or e.get("uploader_id")
                    if not ch_id or ch_id in results:
                        continue

                    # Pull channel-level metadata for sub count, country, upload-cadence proxy
                    ch_url = e.get("channel_url") or f"https://www.youtube.com/channel/{ch_id}"
                    ch_info = await asyncio.to_thread(
                        lambda: YoutubeDL({"quiet": True, "skip_download": True, "no_warnings": True})
                            .extract_info(ch_url, download=False)
                    )
                    subs = _parse_sub_count(ch_info.get("channel_follower_count"))
                    if subs is not None and (subs < min_subs or subs > max_subs):
                        continue
                    country = (ch_info.get("uploader_country") or "").upper()
                    if country_bias and country and country not in country_bias:
                        continue

                    # Recent-upload filter — check first entry's upload_date
                    if cutoff:
                        first = (ch_info.get("entries") or [{}])[0]
                        ud = first.get("upload_date")
                        try:
                            dt = datetime.strptime(ud, "%Y%m%d").replace(tzinfo=timezone.utc)
                            if dt < cutoff:
                                continue
                        except Exception:
                            pass

                    results[ch_id] = Lead(
                        source="youtube_channel",
                        source_id=ch_id,
                        handle=ch_info.get("uploader_id") or ch_info.get("channel") or "",
                        display_name=ch_info.get("channel") or "",
                        bio=ch_info.get("description") or "",
                        url=ch_info.get("channel_url") or ch_url,
                        location=country,
                        follower_count=subs,
                        extra={
                            "video_count": ch_info.get("playlist_count"),
                            "view_count_total": ch_info.get("channel_follower_count"),
                            "links": ch_info.get("channel_url"),
                        },
                    )
                    if len(results) >= limit:
                        break
            except Exception as ex:
                logger.exception("yt-dlp search %s failed: %s", q, ex)
            if len(results) >= limit:
                break

        return list(results.values())[:limit]
