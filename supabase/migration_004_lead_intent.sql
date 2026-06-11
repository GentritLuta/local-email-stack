-- Per-client targeting + auto-search migration.
--   * profiles.lead_intent: JSONB describing the kind of leads each client wants
--   * search_jobs: queue table for "go find more leads for this profile"
--
-- Idempotent: safe to re-run.

-- ─── profiles.lead_intent ─────────────────────────────────────────────────
-- Shape (free-form JSONB, but conventionally):
--   {
--     "target_audience":   "Crypto influencers and TradingView indicator authors",
--     "industries":        ["trading_crypto", "trading_general"],
--     "location_geos":     ["US", "DE", "GB"],
--     "platforms":         ["youtube", "tradingview", "instagram", "twitter"],
--     "audience_size_min": 5000,
--     "default_sequence_slug": "algoalpha-aureon-2026-05-17",
--     "search_keywords":   ["crypto signals", "tradingview indicator review"],
--     "notes":             "Free-form operator notes"
--   }

ALTER TABLE profiles
  ADD COLUMN IF NOT EXISTS lead_intent JSONB;

-- ─── search_jobs: queued discovery requests per profile ──────────────────
CREATE TABLE IF NOT EXISTS search_jobs (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_slug TEXT NOT NULL,
  niche_slug   TEXT,                                -- optional override
  intent_snap  JSONB,                               -- snapshot of lead_intent at request time
  status       TEXT NOT NULL DEFAULT 'pending',    -- pending|running|done|failed
  requested_by TEXT,                                -- operator identifier (free text)
  started_at   TIMESTAMPTZ,
  finished_at  TIMESTAMPTZ,
  last_error   TEXT,
  result       JSONB,                               -- per-platform counts after completion
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS search_jobs_pending_idx
  ON search_jobs (status, created_at)
  WHERE status = 'pending';

ALTER TABLE search_jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS search_jobs_anon_all ON search_jobs;
CREATE POLICY search_jobs_anon_all ON search_jobs
  FOR ALL TO anon USING (true) WITH CHECK (true);
