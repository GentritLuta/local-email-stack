"""local_business — multi-source local business sourcing.

Delegates to the existing scraper service which knows how to drive Crawlee +
Playwright + FlareSolverr + the AI-heal layer across Google Maps, Yelp, Bing
Places, and the Overpass API. Innovation #1 handles selector drift behind it.

Config:
  category:                 str (e.g. "restaurant", "real_estate_agency", "dentist")
  location:                 str (e.g. "Austin, TX") — geocoded if lat/lng absent
  lat:                      float (optional if location given)
  lng:                      float (optional if location given)
  radius_m:                 int (default 10000)
  min_rating:               float (optional)
  max_rating:               float (optional)
  sources:                  list of {google_maps, yelp, bing_places, overpass} (default all)
  limit:                    int (default 200)
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from . import Lead, SourcingEngine, register

logger = logging.getLogger("engines.local_business")

SCRAPER_URL = os.environ.get("SCRAPER_URL", "http://scraper:8080")


@register("local_business")
class LocalBusinessEngine(SourcingEngine):
    async def search(self, config: dict) -> list[Lead]:
        category = config.get("category", "")
        location = config.get("location", "")
        lat, lng = config.get("lat"), config.get("lng")
        radius = int(config.get("radius_m", 10_000))
        min_rating = float(config.get("min_rating", 0))
        max_rating = float(config.get("max_rating", 5.1))
        sources = config.get("sources") or ["google_maps", "yelp", "bing_places", "overpass"]
        limit = int(config.get("limit", 200))

        # Geocode if needed
        if (lat is None or lng is None) and location:
            try:
                async with httpx.AsyncClient(timeout=20) as c:
                    r = await c.get(
                        "https://nominatim.openstreetmap.org/search",
                        params={"q": location, "format": "json", "limit": 1},
                        headers={"User-Agent": "local-email-stack/4.0"},
                    )
                    j = r.json()
                    if j:
                        lat = float(j[0]["lat"])
                        lng = float(j[0]["lon"])
            except Exception as ex:
                logger.warning("nominatim geocode failed for %s: %s", location, ex)

        merged: dict[str, Lead] = {}

        async with httpx.AsyncClient(timeout=180) as c:
            for src in sources:
                try:
                    r = await c.post(
                        f"{SCRAPER_URL}/scrape/{src}",
                        json={
                            "query": category,
                            "lat": lat,
                            "lng": lng,
                            "radius_m": radius,
                            "location": location,
                            "limit": limit,
                        },
                    )
                    if r.status_code != 200:
                        logger.warning("scraper %s returned %s", src, r.status_code)
                        continue
                    rows = r.json().get("results", [])
                    for row in rows:
                        # Dedupe across sources by website (if present) or name+address
                        key = row.get("website") or f"{row.get('name','')}|{row.get('address','')}"
                        if key in merged:
                            continue
                        rating = float(row.get("rating") or 0)
                        if rating and (rating < min_rating or rating > max_rating):
                            continue
                        merged[key] = Lead(
                            source="local_business",
                            source_id=f"{src}:{row.get('source_id') or key}",
                            handle="",
                            display_name=row.get("name", ""),
                            bio=row.get("category", ""),
                            url=row.get("website", ""),
                            location=row.get("address", ""),
                            extra={
                                "phone": row.get("phone"),
                                "rating": row.get("rating"),
                                "reviews": row.get("reviews"),
                                "discovered_via": src,
                                "raw": row,
                            },
                        )
                        if len(merged) >= limit:
                            break
                except Exception as ex:
                    logger.exception("scraper %s failed: %s", src, ex)
                if len(merged) >= limit:
                    break

        return list(merged.values())[:limit]
