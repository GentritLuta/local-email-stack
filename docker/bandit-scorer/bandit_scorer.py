"""bandit_scorer.py — innovations #4 (Thompson sampling) + #6 (lead quality).

Two responsibilities:

1. **Variant bandit:** for every cold send, pick the (subject, opening, cta) combo
   that maximizes expected reply probability. Updates posterior from observed
   replies. Thompson sampling = no fixed exploration schedule; balances explore/
   exploit automatically.

2. **Lead quality:** embed each lead with nomic-embed-text, predict P(reply | lead)
   with a logistic regression head retrained nightly on our own send log. The
   sender pulls top_K_by_score from the queue rather than FIFO.

Run as a FastAPI service. n8n calls /variant/pick before each send and /variant/reward
on reply (via the CF Worker → n8n → here). /lead/score is called by AI Finder when
new leads arrive.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Optional

import asyncpg
import httpx
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sklearn.linear_model import LogisticRegression

app = FastAPI(title="bandit-scorer", version="1.0.0")

PG_DSN = os.environ["PG_DSN"]
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")

_pool: Optional[asyncpg.Pool] = None
_lead_model: Optional[LogisticRegression] = None
_lead_model_lock = asyncio.Lock()


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=4)
        async with _pool.acquire() as c:
            await c.execute(
                """
                CREATE TABLE IF NOT EXISTS variants (
                    id        SERIAL PRIMARY KEY,
                    kind      TEXT NOT NULL,       -- subject | opening | cta
                    persona   TEXT NOT NULL,
                    text      TEXT NOT NULL,
                    -- Beta(alpha, beta) prior; updates on observed reply / no-reply.
                    alpha     REAL NOT NULL DEFAULT 1.0,
                    beta      REAL NOT NULL DEFAULT 1.0,
                    impressions INT NOT NULL DEFAULT 0,
                    rewards     INT NOT NULL DEFAULT 0,
                    enabled   BOOLEAN NOT NULL DEFAULT TRUE,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    UNIQUE (kind, persona, text)
                );
                CREATE INDEX IF NOT EXISTS idx_variants_kind_persona
                    ON variants (kind, persona) WHERE enabled;

                CREATE TABLE IF NOT EXISTS lead_features (
                    lead_id TEXT PRIMARY KEY,
                    embedding REAL[] NOT NULL,
                    label INT,           -- 1 = replied, 0 = no-reply (after timeout), NULL = pending
                    scored_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                );
                """
            )
    return _pool


# ─── Variant bandit (innovation #4) ────────────────────────────────────────

class PickVariantRequest(BaseModel):
    persona: str
    kinds: list[str] = ["subject", "opening", "cta"]


class PickedVariant(BaseModel):
    id: int
    kind: str
    text: str


class PickVariantResponse(BaseModel):
    variants: list[PickedVariant]


@app.post("/variant/pick", response_model=PickVariantResponse)
async def pick_variant(req: PickVariantRequest) -> PickVariantResponse:
    pool = await get_pool()
    picked: list[PickedVariant] = []
    async with pool.acquire() as conn:
        for kind in req.kinds:
            rows = await conn.fetch(
                "SELECT id, text, alpha, beta FROM variants "
                "WHERE kind=$1 AND persona=$2 AND enabled",
                kind, req.persona,
            )
            if not rows:
                raise HTTPException(404, f"no variants for ({kind}, {req.persona})")
            # Thompson sampling: draw from each arm's Beta posterior; pick max.
            samples = [(np.random.beta(r["alpha"], r["beta"]), r) for r in rows]
            samples.sort(key=lambda x: -x[0])
            chosen = samples[0][1]
            picked.append(PickedVariant(id=chosen["id"], kind=kind, text=chosen["text"]))
            await conn.execute(
                "UPDATE variants SET impressions = impressions + 1 WHERE id=$1",
                chosen["id"],
            )
    return PickVariantResponse(variants=picked)


class RewardRequest(BaseModel):
    variant_ids: list[int]
    rewarded: bool   # True if recipient replied within reward window (e.g. 7d)


@app.post("/variant/reward")
async def variant_reward(req: RewardRequest) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Beta(alpha, beta): on reward, alpha += 1; on no-reward, beta += 1.
        if req.rewarded:
            await conn.executemany(
                "UPDATE variants SET alpha = alpha + 1, rewards = rewards + 1 WHERE id=$1",
                [(i,) for i in req.variant_ids],
            )
        else:
            await conn.executemany(
                "UPDATE variants SET beta = beta + 1 WHERE id=$1",
                [(i,) for i in req.variant_ids],
            )
    return {"ok": True, "updated": len(req.variant_ids)}


# Weekly cron — phase out provably-bad arms, generate fresh candidates.
@app.post("/variant/curate")
async def variant_curate() -> dict:
    """Disable arms whose 95% CI upper bound is below the population mean;
    add 5 fresh LLM-generated variants per (kind, persona) inspired by top-3 performers."""
    pool = await get_pool()
    disabled = 0
    added = 0
    async with pool.acquire() as conn:
        # Compute population mean reply rate per (kind, persona)
        agg = await conn.fetch("""
            SELECT kind, persona,
                   SUM(rewards)::REAL / GREATEST(SUM(impressions), 1) AS mean_reply
            FROM variants
            WHERE enabled AND impressions >= 20
            GROUP BY kind, persona
        """)
        for a in agg:
            # Beta 95% upper bound = Beta(0.975 quantile) ≈ alpha / (alpha + beta) + 1.96 * sd
            bad = await conn.fetch("""
                SELECT id FROM variants
                WHERE enabled AND impressions >= 30 AND kind=$1 AND persona=$2
                  AND (alpha / (alpha + beta) + 1.96 * SQRT(alpha*beta / POWER(alpha+beta, 2) / (alpha+beta+1))) < $3
            """, a["kind"], a["persona"], a["mean_reply"])
            if bad:
                await conn.execute("UPDATE variants SET enabled=FALSE WHERE id = ANY($1)",
                                   [r["id"] for r in bad])
                disabled += len(bad)
        # Generate fresh variants — uses Qwen via Ollama
        for (kind, persona) in set((a["kind"], a["persona"]) for a in agg):
            top3 = await conn.fetch("""
                SELECT text, alpha / (alpha + beta) AS rate FROM variants
                WHERE enabled AND kind=$1 AND persona=$2 AND impressions >= 20
                ORDER BY alpha / (alpha + beta) DESC LIMIT 3
            """, kind, persona)
            if not top3:
                continue
            top3_text = "\n".join(f"- ({r['rate']:.1%}) {r['text']}" for r in top3)
            prompt = (
                f"You are generating new cold-email {kind} candidates for persona '{persona}'. "
                f"Top-3 performers so far (with reply rates):\n{top3_text}\n\n"
                f"Generate 5 NEW {kind} candidates in the same style — distinct from these. "
                "Return JSON array of strings."
            )
            async with httpx.AsyncClient(timeout=60) as c:
                r = await c.post(
                    f"{OLLAMA_URL}/api/chat",
                    json={
                        "model": "qwen2.5:32b-instruct-q4_K_M",
                        "messages": [{"role": "user", "content": prompt}],
                        "format": "json",
                        "stream": False,
                    },
                )
            try:
                new = json.loads(r.json()["message"]["content"])
                if isinstance(new, list):
                    for txt in new[:5]:
                        await conn.execute(
                            "INSERT INTO variants (kind, persona, text) VALUES ($1,$2,$3) "
                            "ON CONFLICT DO NOTHING",
                            kind, persona, str(txt),
                        )
                        added += 1
            except Exception:
                pass
    return {"disabled": disabled, "added": added}


# ─── Lead quality scoring (innovation #6) ──────────────────────────────────

class LeadScoreRequest(BaseModel):
    lead_id: str
    features_text: str   # concatenation of {company, category, website_summary, title, socials}


class LeadScoreResponse(BaseModel):
    p_reply: float
    p_bounce: float


async def embed(text: str) -> np.ndarray:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{OLLAMA_URL}/api/embeddings",
            json={"model": EMBED_MODEL, "prompt": text},
        )
    return np.asarray(r.json()["embedding"], dtype=np.float32)


async def get_lead_model() -> LogisticRegression:
    global _lead_model
    async with _lead_model_lock:
        if _lead_model is None:
            await retrain_lead_model()
    return _lead_model  # type: ignore


async def retrain_lead_model() -> None:
    """Pull all labeled lead_features and refit. Runs nightly via /lead/retrain."""
    global _lead_model
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT embedding, label FROM lead_features WHERE label IS NOT NULL"
        )
    if len(rows) < 50:
        # Not enough data yet — use a no-op model that returns 0.5 for everything.
        _lead_model = LogisticRegression()
        # Synthetic warm-start with two trivial classes
        X = np.zeros((2, 768), dtype=np.float32)
        X[1, 0] = 1.0
        y = np.array([0, 1])
        _lead_model.fit(X, y)
        return
    X = np.array([r["embedding"] for r in rows], dtype=np.float32)
    y = np.array([r["label"] for r in rows], dtype=np.int8)
    model = LogisticRegression(max_iter=400, C=0.5)
    model.fit(X, y)
    _lead_model = model


@app.post("/lead/score", response_model=LeadScoreResponse)
async def score_lead(req: LeadScoreRequest) -> LeadScoreResponse:
    pool = await get_pool()
    emb = await embed(req.features_text)
    model = await get_lead_model()
    p_reply = float(model.predict_proba(emb.reshape(1, -1))[0, 1])
    # P(bounce) — simple heuristic until we collect bounce-labeled data
    p_bounce = float(np.clip(0.4 - p_reply, 0.02, 0.4))
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO lead_features (lead_id, embedding)
            VALUES ($1, $2)
            ON CONFLICT (lead_id) DO UPDATE SET embedding = EXCLUDED.embedding, scored_at = NOW()
            """,
            req.lead_id, emb.tolist(),
        )
    return LeadScoreResponse(p_reply=p_reply, p_bounce=p_bounce)


class LeadLabelRequest(BaseModel):
    lead_id: str
    replied: bool


@app.post("/lead/label")
async def label_lead(req: LeadLabelRequest) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE lead_features SET label = $1 WHERE lead_id = $2",
            1 if req.replied else 0, req.lead_id,
        )
    return {"ok": True}


@app.post("/lead/retrain")
async def lead_retrain() -> dict:
    await retrain_lead_model()
    return {"ok": True}


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
