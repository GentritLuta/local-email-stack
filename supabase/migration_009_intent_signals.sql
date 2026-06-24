-- Intent-signal / seller-appointment engine results table.
--   Per-lead intent signals discovered by the signal-pack engine
--   (sequences/intent_signals.py). One row per (profile, signal, evidence_url).
--
-- This is the B2C seller-lead layer: rows here are HOMEOWNERS / seller leads
-- per agent-client metro, NOT the agent prospects in `prospects`.
--
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS intent_signals (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_slug    TEXT NOT NULL,                 -- the agent-client this lead is for
  pack            TEXT NOT NULL,                 -- signal pack id (e.g. us_real_estate_distress)
  metro           TEXT,                          -- agent's local area scoped for the scan
  lead_key        TEXT NOT NULL,                 -- stable id for the seller lead (url/address hash)
  lead_label      TEXT,                          -- human label (post title / owner-or-address)
  signal_id       TEXT NOT NULL,                 -- which signal fired
  found           BOOLEAN NOT NULL DEFAULT false,
  evidence_url    TEXT,
  evidence_snippet TEXT,
  event_date      TEXT,                          -- best-effort signal date (free text)
  confidence      REAL,                          -- 0..1 evidence confidence
  weight          REAL,                          -- signal weight from the pack
  score           REAL,                          -- weight * confidence * recency_decay
  channel         TEXT,                          -- routing: direct_mail|optin_funnel|ad_audience|...
  status          TEXT NOT NULL DEFAULT 'new',   -- new|routed|dismissed
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (profile_slug, signal_id, evidence_url)
);

CREATE INDEX IF NOT EXISTS intent_signals_profile_idx
  ON intent_signals (profile_slug, status, score DESC);

CREATE INDEX IF NOT EXISTS intent_signals_new_idx
  ON intent_signals (profile_slug, created_at)
  WHERE status = 'new';

-- Follows the search_jobs (migration 004) convention: backend uses the anon key.
ALTER TABLE intent_signals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS intent_signals_anon_all ON intent_signals;
CREATE POLICY intent_signals_anon_all ON intent_signals
  FOR ALL TO anon USING (true) WITH CHECK (true);
