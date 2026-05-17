"""social — cross-platform handle resolution + per-platform profile fetch.

For each lead, extract social handles from:
  - the source itself (e.g. Twitter lead already has handle)
  - website pages crawled (links to twitter.com, instagram.com, …)
  - bio fields, openGraph metadata

Then fetch a lightweight profile snapshot for each found handle.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

logger = logging.getLogger("enricher.social")

PLATFORM_PATTERNS = {
    "twitter":   re.compile(r"(?:twitter\.com|x\.com)/(?!intent|share|hashtag)([A-Za-z0-9_]{1,15})\b", re.I),
    "linkedin":  re.compile(r"linkedin\.com/in/([A-Za-z0-9\-_%]+)/?", re.I),
    "instagram": re.compile(r"instagram\.com/([A-Za-z0-9_.]{1,30})/?", re.I),
    "facebook":  re.compile(r"facebook\.com/([A-Za-z0-9_.]+)/?", re.I),
    "youtube":   re.compile(r"youtube\.com/(?:@|c/|channel/|user/)?([A-Za-z0-9_\-]+)", re.I),
    "tiktok":    re.compile(r"tiktok\.com/@([A-Za-z0-9_.]+)/?", re.I),
    "github":    re.compile(r"github\.com/([A-Za-z0-9_\-]+)/?", re.I),
    "bluesky":   re.compile(r"bsky\.app/profile/([A-Za-z0-9\-_.]+)", re.I),
    "mastodon":  re.compile(r"@([A-Za-z0-9_]+)@([A-Za-z0-9\-.]+)"),
    "farcaster": re.compile(r"warpcast\.com/([A-Za-z0-9_\-]+)", re.I),
    "threads":   re.compile(r"threads\.net/@([A-Za-z0-9_.]+)", re.I),
    "reddit":    re.compile(r"reddit\.com/u(?:ser)?/([A-Za-z0-9_\-]+)", re.I),
}


def find_handles(text_blob: str) -> dict[str, str]:
    """Scan a blob of text for social handles. Returns {platform: handle}."""
    out: dict[str, str] = {}
    for platform, pat in PLATFORM_PATTERNS.items():
        m = pat.search(text_blob)
        if m:
            out[platform] = m.group(1)
    return out


async def crosscheck(core: dict, web: dict) -> dict[str, Any]:
    handles: dict[str, str] = {}

    # 1. The source itself
    src = core.get("source", "")
    if src == "twitter_profile":
        handles["twitter"] = core.get("handle", "")
    elif src == "linkedin_via_google":
        handles["linkedin"] = core.get("handle", "")
    elif src == "youtube_channel":
        handles["youtube"] = core.get("handle", "")
    elif src == "github_developer":
        handles["github"] = core.get("handle", "")
    elif src == "farcaster_creator":
        handles["farcaster"] = core.get("handle", "")
    elif src == "instagram_profile":
        handles["instagram"] = core.get("handle", "")
    elif src == "tiktok_creator":
        handles["tiktok"] = core.get("handle", "")
    elif src == "bluesky_user":
        handles["bluesky"] = core.get("handle", "")
    elif src == "reddit_user":
        handles["reddit"] = core.get("handle", "")

    # 2. Scan website pages
    blob_parts = []
    for page in (web.get("pages") or {}).values():
        for link in (page.get("links") or []):
            blob_parts.append(str(link))
        blob_parts.append(page.get("clean_text", ""))
    blob = "\n".join(blob_parts)
    for k, v in find_handles(blob).items():
        handles.setdefault(k, v)

    # 3. Lightweight profile snapshots (best-effort, all free, all rate-limited friendly)
    profiles: dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
        if "github" in handles:
            try:
                r = await c.get(f"https://api.github.com/users/{handles['github']}")
                if r.status_code == 200:
                    g = r.json()
                    profiles["github"] = {
                        "user": handles["github"],
                        "name": g.get("name"),
                        "bio": g.get("bio"),
                        "followers": g.get("followers"),
                        "public_repos": g.get("public_repos"),
                        "blog": g.get("blog"),
                        "twitter": g.get("twitter_username"),
                        "company": g.get("company"),
                        "url": g.get("html_url"),
                    }
            except Exception:
                pass
        if "bluesky" in handles:
            try:
                r = await c.get(
                    "https://api.bsky.app/xrpc/app.bsky.actor.getProfile",
                    params={"actor": handles["bluesky"]},
                )
                if r.status_code == 200:
                    p = r.json()
                    profiles["bluesky"] = {
                        "handle": p.get("handle"),
                        "display_name": p.get("displayName"),
                        "bio": p.get("description"),
                        "followers": p.get("followersCount"),
                        "posts": p.get("postsCount"),
                        "url": f"https://bsky.app/profile/{p.get('handle')}",
                    }
            except Exception:
                pass
        # Other platforms: include handle + URL only; deeper fetch deferred to `deep` level
        for plat, h in handles.items():
            if plat in profiles:
                continue
            profiles[plat] = {"handle": h, "url": _url_for(plat, h)}

    return profiles


def _url_for(platform: str, handle: str) -> str:
    return {
        "twitter":   f"https://x.com/{handle}",
        "linkedin":  f"https://linkedin.com/in/{handle}",
        "instagram": f"https://instagram.com/{handle}",
        "facebook":  f"https://facebook.com/{handle}",
        "youtube":   f"https://youtube.com/@{handle}",
        "tiktok":    f"https://tiktok.com/@{handle}",
        "github":    f"https://github.com/{handle}",
        "bluesky":   f"https://bsky.app/profile/{handle}",
        "farcaster": f"https://warpcast.com/{handle}",
        "threads":   f"https://threads.net/@{handle}",
        "reddit":    f"https://reddit.com/u/{handle}",
        "mastodon":  f"https://{handle}",
    }.get(platform, "")
