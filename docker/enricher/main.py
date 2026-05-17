"""enricher/main.py — maximum public-context enrichment for every lead.

Pulls every freely-available signal: website crawl, cross-platform social profiles,
WHOIS/DNS/SSL/tech-stack, news + press mentions, business records, archive.org,
schema.org, OpenGraph. Output is a single nested JSON object stored in
leads_enriched.profile (jsonb).

Endpoints:
  GET  /healthz
  POST /enrich/lead {lead_id, level}     → enrich one lead
  POST /enrich/batch {niche_slug, level} → enrich every unfinished lead in a niche
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

import asyncpg
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from modules import (
    website as mod_website,
    social as mod_social,
    infra as mod_infra,
    techstack as mod_tech,
    news as mod_news,
    business as mod_business,
    signals as mod_signals,
)

logger = logging.getLogger("enricher")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

PG_DSN = os.environ["PG_DSN"]
SCRAPER_URL = os.environ.get("SCRAPER_URL", "http://scraper:8080")
SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://searxng:8080")
SOURCING_URL = os.environ.get("SOURCING_URL", "http://sourcing:8000")
CONCURRENCY = int(os.environ.get("ENRICH_CONCURRENCY", "4"))

_pool: asyncpg.Pool | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    _pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=8)
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads_enriched (
                lead_id    UUID PRIMARY KEY,
                profile    JSONB NOT NULL,
                level      TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
    yield
    await _pool.close()


app = FastAPI(title="enricher", version="1.0.0", lifespan=lifespan)


class LeadEnrichRequest(BaseModel):
    lead_id: str
    level: str = "comprehensive"   # minimal | standard | comprehensive | deep


class BatchEnrichRequest(BaseModel):
    niche_slug: str
    level: str = "comprehensive"
    limit: int = 200


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.post("/enrich/lead")
async def enrich_lead(req: LeadEnrichRequest) -> dict:
    assert _pool is not None
    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, source, source_id, core FROM leads_raw WHERE id = $1",
            uuid.UUID(req.lead_id),
        )
    if not row:
        raise HTTPException(404, "lead not found")
    profile = await _enrich(row, req.level)
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO leads_enriched (lead_id, profile, level)
            VALUES ($1, $2::jsonb, $3)
            ON CONFLICT (lead_id) DO UPDATE
              SET profile = EXCLUDED.profile, level = EXCLUDED.level, updated_at = NOW()
            """,
            row["id"], _json_dumps(profile), req.level,
        )
    return {"lead_id": req.lead_id, "profile": profile}


@app.post("/enrich/batch")
async def enrich_batch(req: BatchEnrichRequest) -> dict:
    assert _pool is not None
    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT r.id, r.source, r.source_id, r.core
            FROM leads_raw r
            LEFT JOIN leads_enriched e ON e.lead_id = r.id
            WHERE r.niche_slug = $1 AND e.lead_id IS NULL
            LIMIT $2
            """,
            req.niche_slug, req.limit,
        )
    sem = asyncio.Semaphore(CONCURRENCY)

    async def one(r):
        async with sem:
            try:
                profile = await _enrich(r, req.level)
                async with _pool.acquire() as conn:
                    await conn.execute(
                        """
                        INSERT INTO leads_enriched (lead_id, profile, level)
                        VALUES ($1, $2::jsonb, $3)
                        ON CONFLICT (lead_id) DO UPDATE
                          SET profile = EXCLUDED.profile, level = EXCLUDED.level, updated_at = NOW()
                        """,
                        r["id"], _json_dumps(profile), req.level,
                    )
                return True
            except Exception as ex:
                logger.exception("enrich %s failed: %s", r["id"], ex)
                return False

    started = time.time()
    outcomes = await asyncio.gather(*[one(r) for r in rows])
    return {
        "niche_slug": req.niche_slug,
        "attempted": len(rows),
        "succeeded": sum(outcomes),
        "elapsed_sec": time.time() - started,
    }


# ─── The enrichment pipeline ───────────────────────────────────────────────

async def _enrich(row: asyncpg.Record, level: str) -> dict[str, Any]:
    import json
    core_in = json.loads(row["core"]) if isinstance(row["core"], str) else row["core"]
    profile: dict[str, Any] = {
        "lead_id": str(row["id"]),
        "source": row["source"],
        "source_id": row["source_id"],
        "core": core_in,
        "social": {},
        "web": {},
        "infra": {},
        "external": {},
        "signals": {},
    }

    website = (core_in.get("url") or "").strip()
    company_name = core_in.get("display_name") or core_in.get("handle") or ""
    owner_name = core_in.get("display_name") or ""

    # 1. Website crawl
    if website:
        try:
            profile["web"] = await mod_website.crawl(website, SCRAPER_URL)
        except Exception as ex:
            logger.warning("website crawl failed: %s", ex)

    # 2. Cross-platform socials (always — cheap)
    try:
        profile["social"] = await mod_social.crosscheck(core_in, profile.get("web", {}))
    except Exception as ex:
        logger.warning("social crosscheck failed: %s", ex)

    if level == "minimal":
        return profile

    # 3. Tech stack on website
    if website:
        try:
            profile["web"]["tech_stack"] = await mod_tech.detect(website, profile["web"].get("pages", {}))
        except Exception as ex:
            logger.warning("tech_stack failed: %s", ex)

    if level == "standard":
        profile["signals"] = mod_signals.compute(profile)
        return profile

    # 4. Infra: WHOIS, DNS, SSL, archive.org
    if website:
        try:
            profile["infra"] = await mod_infra.collect(website)
        except Exception as ex:
            logger.warning("infra collect failed: %s", ex)

    # 5. External: news + press + business records
    try:
        profile["external"] = await mod_news.search(SEARXNG_URL, owner_name, company_name)
    except Exception as ex:
        logger.warning("news search failed: %s", ex)

    try:
        profile["external"]["business_records"] = await mod_business.lookup(company_name, website)
    except Exception as ex:
        logger.warning("business records failed: %s", ex)

    profile["signals"] = mod_signals.compute(profile)
    return profile


def _json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, default=str, ensure_ascii=False)
