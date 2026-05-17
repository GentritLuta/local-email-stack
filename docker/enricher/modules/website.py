"""website — crawl home + about + team + blog + pricing + careers via scraper service.

The scraper service exposes /scrape/url which returns clean text + extracted metadata
(OpenGraph, schema.org, favicon) for any URL. We hit common page paths.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urljoin, urlparse

import httpx

logger = logging.getLogger("enricher.website")

CANDIDATE_PATHS = [
    ("home",    ""),
    ("about",   "/about"),
    ("about",   "/about-us"),
    ("team",    "/team"),
    ("team",    "/people"),
    ("team",    "/leadership"),
    ("team",    "/founders"),
    ("contact", "/contact"),
    ("contact", "/contact-us"),
    ("blog",    "/blog"),
    ("blog",    "/news"),
    ("pricing", "/pricing"),
    ("careers", "/careers"),
    ("careers", "/jobs"),
]


async def crawl(website: str, scraper_url: str) -> dict:
    if not website.startswith("http"):
        website = "https://" + website
    parsed = urlparse(website)
    base = f"{parsed.scheme}://{parsed.netloc}"

    seen_kinds: dict[str, dict] = {}
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as c:
        async def fetch_one(kind: str, path: str):
            if kind in seen_kinds:
                return
            url = urljoin(base + "/", path.lstrip("/"))
            try:
                r = await c.post(f"{scraper_url}/scrape/url", json={"url": url})
                if r.status_code != 200:
                    return
                data = r.json()
                if data.get("status") != "ok":
                    return
                seen_kinds[kind] = {
                    "url": url,
                    "title": data.get("title", ""),
                    "description": data.get("description", ""),
                    "clean_text": (data.get("text") or "")[:6000],
                    "opengraph": data.get("opengraph", {}),
                    "schema_org": data.get("schema_org", []),
                    "favicon": data.get("favicon"),
                    "links": data.get("links", []),
                }
            except Exception as ex:
                logger.debug("page %s failed: %s", url, ex)

        await asyncio.gather(*[fetch_one(kind, path) for kind, path in CANDIDATE_PATHS])

    # Blog-recent-posts: if /blog returned links, grab top 5 internal links and crawl
    if "blog" in seen_kinds:
        internal = [
            l for l in seen_kinds["blog"].get("links", [])
            if isinstance(l, str) and parsed.netloc in l
        ][:5]
        async with httpx.AsyncClient(timeout=30) as c:
            posts = []
            for link in internal:
                try:
                    r = await c.post(f"{scraper_url}/scrape/url", json={"url": link})
                    if r.status_code == 200 and r.json().get("status") == "ok":
                        d = r.json()
                        posts.append({
                            "url": link,
                            "title": d.get("title", ""),
                            "summary": (d.get("text") or "")[:1000],
                        })
                except Exception:
                    continue
            seen_kinds["blog"]["recent_posts"] = posts

    return {"website": website, "pages": seen_kinds}
