"""github_developer — find GitHub users by language + activity + bio keywords.

Uses the GitHub REST API. Free with a personal access token (5000 req/hr).

Config:
  languages:        [list of strings, e.g. ["TypeScript", "Go"]]
  bio_keywords:     [list of strings to match in user bio]
  min_followers:    int (default 50)
  pushed_within_days: int (default 60) — last activity recency
  locations:        [list of strings, optional]
  limit:            int (default 100)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.github_developer")
GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")


@register("github_developer")
class GithubDeveloperEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        if not GH_TOKEN:
            logger.warning("GITHUB_TOKEN unset; rate limit will be 60/hr (vs 5000)")
        languages = config.get("languages") or []
        bio_kws = config.get("bio_keywords") or []
        min_followers = int(config.get("min_followers", 50))
        pushed_days = int(config.get("pushed_within_days", 60))
        locations = config.get("locations") or []
        limit = int(config.get("limit", 100))

        pushed_cutoff = (datetime.now(timezone.utc) - timedelta(days=pushed_days)).strftime("%Y-%m-%d")

        headers = {"Accept": "application/vnd.github+json"}
        if GH_TOKEN:
            headers["Authorization"] = f"Bearer {GH_TOKEN}"

        results: dict[str, Lead] = {}
        async with httpx.AsyncClient(timeout=30, headers=headers) as c:
            # Use the /search/users API with language and followers filters; bio filters apply post-hoc.
            for lang in languages or [""]:
                for loc in locations or [""]:
                    q_parts = [f"language:{lang}"] if lang else []
                    q_parts.append(f"followers:>={min_followers}")
                    if loc:
                        q_parts.append(f"location:\"{loc}\"")
                    # pushed: filter requires repo search; for users, we filter via repo cross-ref below.
                    q = " ".join(q_parts)
                    try:
                        r = await c.get(
                            "https://api.github.com/search/users",
                            params={"q": q, "per_page": min(100, limit * 2), "sort": "followers"},
                        )
                        if r.status_code != 200:
                            logger.warning("GH search returned %s: %s", r.status_code, r.text[:200])
                            continue
                        for u in r.json().get("items", []):
                            login = u["login"]
                            if login in results:
                                continue
                            # Pull user details for bio + active repos check
                            ud = await c.get(u["url"])
                            if ud.status_code != 200:
                                continue
                            user = ud.json()
                            bio = (user.get("bio") or "").lower()
                            if bio_kws and not any(k.lower() in bio for k in bio_kws):
                                continue
                            # Recent activity check via /users/{u}/repos sorted=pushed
                            rp = await c.get(user["repos_url"] + "?sort=pushed&per_page=1")
                            if rp.status_code == 200 and rp.json():
                                last_push = rp.json()[0].get("pushed_at", "")
                                if last_push < pushed_cutoff:
                                    continue
                            results[login] = Lead(
                                source="github_developer",
                                source_id=login,
                                handle=login,
                                display_name=user.get("name") or login,
                                bio=user.get("bio") or "",
                                url=user.get("html_url") or f"https://github.com/{login}",
                                location=user.get("location") or "",
                                follower_count=user.get("followers"),
                                extra={
                                    "company": user.get("company"),
                                    "blog": user.get("blog"),
                                    "twitter": user.get("twitter_username"),
                                    "public_repos": user.get("public_repos"),
                                    "created_at": user.get("created_at"),
                                },
                            )
                            if len(results) >= limit:
                                break
                    except Exception as ex:
                        logger.exception("GH search failed: %s", ex)
                    if len(results) >= limit:
                        break
                if len(results) >= limit:
                    break

        return list(results.values())[:limit]
