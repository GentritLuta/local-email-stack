"""sourcing/main.py — universal lead sourcing service.

Implements the engine + niche abstraction described in SOURCING_AND_NICHES.md.

Routes:
  GET  /healthz
  GET  /engines                          → list registered engines
  GET  /niches                           → list loaded niches
  POST /niches/reload                    → re-read niches/*.yaml from disk
  POST /source/run                       → run a niche end-to-end (returns job id)
  GET  /source/jobs/{job_id}             → job status + lead count

Niches hot-reload from /app/niches every NICHE_RELOAD_SECONDS (default 300).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
import yaml
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from engines import REGISTRY, Lead

logger = logging.getLogger("sourcing")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

NICHES_DIR = Path(os.environ.get("NICHES_DIR", "/app/niches"))
NICHE_RELOAD_SECONDS = int(os.environ.get("NICHE_RELOAD_SECONDS", "300"))
PG_DSN = os.environ["PG_DSN"]
ENRICHER_URL = os.environ.get("ENRICHER_URL", "http://enricher:8000")

_niches: dict[str, dict] = {}
_pool: asyncpg.Pool | None = None
_jobs: dict[str, dict] = {}


# ─── Lifecycle ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _pool
    _pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=8)
    async with _pool.acquire() as conn:
        await conn.execute(
            """
            CREATE TABLE IF NOT EXISTS leads_raw (
                id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                source       TEXT NOT NULL,
                source_id    TEXT NOT NULL,
                niche_slug   TEXT NOT NULL,
                core         JSONB NOT NULL,
                fetched_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE (source, source_id)
            );
            CREATE INDEX IF NOT EXISTS idx_leads_raw_niche ON leads_raw (niche_slug);
            """
        )
    await load_niches()
    task = asyncio.create_task(_reload_loop())
    try:
        yield
    finally:
        task.cancel()
        await _pool.close()


async def _reload_loop():
    while True:
        await asyncio.sleep(NICHE_RELOAD_SECONDS)
        try:
            await load_niches()
        except Exception as e:
            logger.exception("niche reload failed: %s", e)


async def load_niches():
    global _niches
    fresh: dict[str, dict] = {}
    if NICHES_DIR.exists():
        for p in NICHES_DIR.glob("*.yaml"):
            try:
                doc = yaml.safe_load(p.read_text(encoding="utf-8"))
                slug = doc.get("slug") or p.stem
                doc["_path"] = str(p)
                fresh[slug] = doc
            except Exception as e:
                logger.exception("failed to load niche %s: %s", p, e)
    _niches = fresh
    logger.info("niches loaded: %d (%s)", len(fresh), ", ".join(sorted(fresh.keys())))


app = FastAPI(title="sourcing", version="1.0.0", lifespan=lifespan)


# ─── Models ────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    niche_slug: str
    overrides: dict[str, Any] = Field(default_factory=dict)
    auto_enrich: bool = True


class RunResponse(BaseModel):
    job_id: str


class JobStatus(BaseModel):
    job_id: str
    niche_slug: str
    status: str
    started_at: float
    finished_at: float | None
    leads_found: int
    leads_inserted: int
    error: str | None = None


# ─── Endpoints ─────────────────────────────────────────────────────────────

@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}


@app.get("/engines")
async def list_engines() -> dict:
    return {"engines": sorted(REGISTRY.keys())}


@app.get("/niches")
async def list_niches() -> dict:
    return {"niches": {k: {"name": v.get("name"), "engines": [e["engine"] for e in v.get("sourcing_engines", [])]} for k, v in _niches.items()}}


@app.post("/niches/reload")
async def niches_reload() -> dict:
    await load_niches()
    return {"loaded": len(_niches)}


@app.post("/source/run", response_model=RunResponse)
async def source_run(req: RunRequest) -> RunResponse:
    if req.niche_slug not in _niches:
        raise HTTPException(404, f"unknown niche {req.niche_slug}")
    job_id = str(uuid.uuid4())
    _jobs[job_id] = {
        "job_id": job_id,
        "niche_slug": req.niche_slug,
        "status": "running",
        "started_at": time.time(),
        "finished_at": None,
        "leads_found": 0,
        "leads_inserted": 0,
        "error": None,
    }
    asyncio.create_task(_run_niche(job_id, req))
    return RunResponse(job_id=job_id)


@app.get("/source/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str) -> JobStatus:
    job = _jobs.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job")
    return JobStatus(**job)


# ─── Runner ────────────────────────────────────────────────────────────────

async def _run_niche(job_id: str, req: RunRequest):
    job = _jobs[job_id]
    niche = _niches[req.niche_slug]
    try:
        engines_cfg = niche.get("sourcing_engines", [])
        all_leads: list[Lead] = []
        for e in engines_cfg:
            engine_name = e["engine"]
            engine_cls = REGISTRY.get(engine_name)
            if not engine_cls:
                logger.warning("engine %s not registered, skipping", engine_name)
                continue
            config = {**e.get("config", {}), **req.overrides.get(engine_name, {})}
            engine = engine_cls()
            try:
                logger.info("job %s: running engine %s", job_id, engine_name)
                leads = await engine.search(config)
                logger.info("job %s: engine %s returned %d leads", job_id, engine_name, len(leads))
                all_leads.extend(leads)
            except Exception as ex:
                logger.exception("engine %s failed: %s", engine_name, ex)

        job["leads_found"] = len(all_leads)

        # Insert into DB (dedup by source+source_id via UNIQUE)
        inserted = 0
        if _pool and all_leads:
            async with _pool.acquire() as conn:
                for lead in all_leads:
                    res = await conn.execute(
                        """
                        INSERT INTO leads_raw (source, source_id, niche_slug, core)
                        VALUES ($1, $2, $3, $4::jsonb)
                        ON CONFLICT (source, source_id) DO NOTHING
                        """,
                        lead.source, lead.source_id, req.niche_slug, lead.core_json(),
                    )
                    if res.endswith(" 1"):
                        inserted += 1
        job["leads_inserted"] = inserted

        # Trigger enrichment if requested (fire-and-forget)
        if req.auto_enrich and inserted > 0:
            try:
                import httpx
                async with httpx.AsyncClient(timeout=10) as c:
                    await c.post(
                        f"{ENRICHER_URL}/enrich/batch",
                        json={"niche_slug": req.niche_slug, "level": niche.get("enrichment", {}).get("level", "comprehensive")},
                    )
            except Exception as ex:
                logger.warning("enricher trigger failed: %s", ex)

        job["status"] = "done"
    except Exception as ex:
        logger.exception("job %s failed: %s", job_id, ex)
        job["status"] = "failed"
        job["error"] = str(ex)
    finally:
        job["finished_at"] = time.time()
