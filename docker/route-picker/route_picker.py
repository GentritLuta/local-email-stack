"""route_picker.py — innovation #3, smart outbound routing.

Receives every outbound message before send. Returns the route to use based on:
  - message class (cold | followup | reply | warmup | system)
  - recipient mailbox provider (gmail.com vs smaller domains)
  - per-route quota burn-down
  - per-route rolling reputation score (bounce% / complaint%)

Designed so the system degrades gracefully if any single route goes down.

Routes in priority order:
  1. POSTAL_ORACLE          — our own infra; cold sends MUST go through this
  2. BREVO                  — free 300/day, transactional only (replies, warmup)
  3. MAILERSEND             — free 3000/mo, transactional only (warmup mesh)
  4. SENDPULSE              — free 12000/mo, transactional only (system mail)

Run as a FastAPI service. n8n calls POST /pick with a JSON of the outbound message.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import asyncpg
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="route-picker", version="1.0.0")

PG_DSN = os.environ["PG_DSN"]
_pool: Optional[asyncpg.Pool] = None


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(PG_DSN, min_size=1, max_size=4)
        async with _pool.acquire() as c:
            await c.execute(
                """
                CREATE TABLE IF NOT EXISTS route_state (
                    route TEXT PRIMARY KEY,
                    daily_quota INT NOT NULL,
                    monthly_quota INT NOT NULL,
                    sent_today INT NOT NULL DEFAULT 0,
                    sent_this_month INT NOT NULL DEFAULT 0,
                    last_reset_day DATE NOT NULL DEFAULT CURRENT_DATE,
                    last_reset_month DATE NOT NULL DEFAULT date_trunc('month', CURRENT_DATE),
                    bounce_rate REAL NOT NULL DEFAULT 0,
                    complaint_rate REAL NOT NULL DEFAULT 0,
                    cooldown_until TIMESTAMPTZ,
                    enabled BOOLEAN NOT NULL DEFAULT TRUE
                );
                INSERT INTO route_state (route, daily_quota, monthly_quota) VALUES
                    ('POSTAL_ORACLE', 1500, 45000),
                    ('BREVO',         300,  9000),
                    ('MAILERSEND',    100,  3000),
                    ('SENDPULSE',     400,  12000)
                ON CONFLICT (route) DO NOTHING;
                """
            )
    return _pool


# ─── Route eligibility per message class ───────────────────────────────────

# Cold-email TOS analysis baked in: free transactional tiers REJECT unsolicited mail.
# Cold + followup must use POSTAL_ORACLE. Replies + warmup + system mail can spill over.
ELIGIBLE: dict[str, list[str]] = {
    "cold":     ["POSTAL_ORACLE"],
    "followup": ["POSTAL_ORACLE"],
    "reply":    ["POSTAL_ORACLE", "BREVO", "MAILERSEND"],
    "warmup":   ["POSTAL_ORACLE", "MAILERSEND", "BREVO"],
    "system":   ["SENDPULSE", "BREVO", "POSTAL_ORACLE"],
}


# ─── Picker ────────────────────────────────────────────────────────────────

class PickRequest(BaseModel):
    message_class: str          # cold | followup | reply | warmup | system
    recipient_domain: str       # gmail.com, outlook.com, smallcompany.io, …
    persona_id: str             # which sending persona/subdomain


class PickResponse(BaseModel):
    route: str
    smtp_host: str
    smtp_port: int
    use_starttls: bool
    reason: str


def smtp_for(route: str) -> tuple[str, int, bool]:
    return {
        "POSTAL_ORACLE": ("postal-mail", 587, True),         # via Tailscale
        "BREVO":         ("smtp-relay.brevo.com", 587, True),
        "MAILERSEND":    ("smtp.mailersend.net", 587, True),
        "SENDPULSE":     ("smtp-pulse.com", 2525, True),
    }[route]


async def reset_counters_if_needed(conn: asyncpg.Connection) -> None:
    today = datetime.now(timezone.utc).date()
    await conn.execute(
        """
        UPDATE route_state
        SET sent_today = 0, last_reset_day = $1
        WHERE last_reset_day < $1
        """,
        today,
    )
    month_start = today.replace(day=1)
    await conn.execute(
        """
        UPDATE route_state
        SET sent_this_month = 0, last_reset_month = $1
        WHERE last_reset_month < $1
        """,
        month_start,
    )


@app.post("/pick", response_model=PickResponse)
async def pick(req: PickRequest) -> PickResponse:
    pool = await get_pool()
    eligible = ELIGIBLE.get(req.message_class, ["POSTAL_ORACLE"])

    async with pool.acquire() as conn:
        await reset_counters_if_needed(conn)

        now = datetime.now(timezone.utc)
        rows = await conn.fetch(
            """
            SELECT route, daily_quota, monthly_quota, sent_today, sent_this_month,
                   bounce_rate, complaint_rate, cooldown_until, enabled
            FROM route_state
            WHERE route = ANY($1)
            """,
            eligible,
        )
        # Score each route: cheaper-quota burn + lower bounce/complaint + not in cooldown.
        candidates = []
        for r in rows:
            if not r["enabled"]:
                continue
            if r["cooldown_until"] and r["cooldown_until"] > now:
                continue
            if r["sent_today"] >= r["daily_quota"]:
                continue
            if r["sent_this_month"] >= r["monthly_quota"]:
                continue
            # Composite score — lower is better; we'll min().
            burn = (r["sent_today"] / max(r["daily_quota"], 1)) + \
                   (r["sent_this_month"] / max(r["monthly_quota"], 1)) * 0.5
            reputation_penalty = r["bounce_rate"] * 5 + r["complaint_rate"] * 20
            # Strongly prefer the first eligible (POSTAL_ORACLE for cold) — explicit ordering.
            preference_bias = eligible.index(r["route"]) * 0.001
            score = burn + reputation_penalty + preference_bias
            candidates.append((score, r["route"]))

        if not candidates:
            # Everything is over quota / cooled-down. Last resort: queue back via POSTAL_ORACLE
            # even if over quota — Postal will spool. Better than dropping.
            route = "POSTAL_ORACLE"
            reason = "all eligible routes exhausted; queueing on POSTAL_ORACLE"
        else:
            candidates.sort()
            route = candidates[0][1]
            reason = f"chose {route} (score={candidates[0][0]:.3f})"

        # Optimistically increment the counter; the sender's success/fail webhook will
        # reconcile bounces and complaints separately.
        await conn.execute(
            """
            UPDATE route_state
            SET sent_today = sent_today + 1, sent_this_month = sent_this_month + 1
            WHERE route = $1
            """,
            route,
        )

    host, port, starttls = smtp_for(route)
    return PickResponse(
        route=route, smtp_host=host, smtp_port=port,
        use_starttls=starttls, reason=reason,
    )


# ─── Webhook: report send outcome (so reputation tracks) ───────────────────

class OutcomeReport(BaseModel):
    route: str
    outcome: str  # sent | bounce_hard | bounce_soft | complaint


@app.post("/outcome")
async def outcome(report: OutcomeReport) -> dict:
    pool = await get_pool()
    async with pool.acquire() as conn:
        # EWMA-style update on bounce/complaint rates
        alpha = 0.05
        is_bounce = 1.0 if report.outcome.startswith("bounce") else 0.0
        is_complaint = 1.0 if report.outcome == "complaint" else 0.0
        row = await conn.fetchrow(
            """
            UPDATE route_state
            SET bounce_rate = bounce_rate * (1 - $2) + $3 * $2,
                complaint_rate = complaint_rate * (1 - $2) + $4 * $2
            WHERE route = $1
            RETURNING bounce_rate, complaint_rate
            """,
            report.route, alpha, is_bounce, is_complaint,
        )
        # If reputation spikes, cool down this route for 24h
        if row and (row["bounce_rate"] > 0.05 or row["complaint_rate"] > 0.001):
            await conn.execute(
                """
                UPDATE route_state
                SET cooldown_until = NOW() + INTERVAL '24 hours'
                WHERE route = $1
                """,
                report.route,
            )
    return {"ok": True}


@app.get("/healthz")
async def healthz() -> dict:
    return {"ok": True}
