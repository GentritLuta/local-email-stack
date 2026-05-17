"""business — OpenCorporates + Wikidata lookups for company name."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger("enricher.business")


async def lookup(company: str, website: str = "") -> dict:
    if not company:
        return {}
    out: dict = {}
    async with httpx.AsyncClient(timeout=20) as c:
        # OpenCorporates — anonymous tier allows limited queries
        try:
            r = await c.get(
                "https://api.opencorporates.com/v0.4/companies/search",
                params={"q": company, "per_page": 3, "order": "score"},
            )
            if r.status_code == 200:
                hits = (r.json().get("results") or {}).get("companies") or []
                out["opencorporates"] = [{
                    "name": h["company"].get("name"),
                    "jurisdiction": h["company"].get("jurisdiction_code"),
                    "company_number": h["company"].get("company_number"),
                    "incorporation_date": h["company"].get("incorporation_date"),
                    "status": h["company"].get("current_status"),
                    "url": h["company"].get("opencorporates_url"),
                } for h in hits[:3]]
        except Exception as ex:
            logger.debug("opencorporates failed: %s", ex)

        # Wikidata via search API (free, no key)
        try:
            r = await c.get(
                "https://www.wikidata.org/w/api.php",
                params={"action": "wbsearchentities", "search": company,
                        "language": "en", "format": "json", "limit": 1, "type": "item"},
            )
            if r.status_code == 200:
                hits = r.json().get("search") or []
                if hits:
                    out["wikidata"] = {
                        "id": hits[0].get("id"),
                        "label": hits[0].get("label"),
                        "description": hits[0].get("description"),
                        "url": hits[0].get("concepturi"),
                    }
        except Exception as ex:
            logger.debug("wikidata failed: %s", ex)

    return out
