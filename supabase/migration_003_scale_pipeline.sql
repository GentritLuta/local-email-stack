-- Tier 2 scale-out migration:
--   * prospect_candidates: queue table replacing per-source .txt files
--   * prospects: add categorization columns (audience, geo, tags, score)
--
-- Idempotent: safe to re-run.

-- ─── prospect_candidates: discovery queue ─────────────────────────────────
CREATE TABLE IF NOT EXISTS prospect_candidates (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  profile_slug TEXT NOT NULL,
  niche_slug   TEXT NOT NULL,
  source       TEXT NOT NULL,                          -- 'youtube' | 'tradingview' | 'instagram' | ...
  handle       TEXT NOT NULL,                          -- platform-specific identifier
  status       TEXT NOT NULL DEFAULT 'pending',        -- pending|claimed|done|failed
  claimed_by   TEXT,                                   -- worker_id holding the claim
  claimed_at   TIMESTAMPTZ,
  done_at      TIMESTAMPTZ,
  attempts     INT NOT NULL DEFAULT 0,
  last_error   TEXT,
  meta         JSONB,                                  -- platform-specific blob (e.g. {channel_id, title})
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (profile_slug, source, handle)
);

CREATE INDEX IF NOT EXISTS prospect_candidates_pending_idx
  ON prospect_candidates (profile_slug, source, status, created_at)
  WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS prospect_candidates_claimed_idx
  ON prospect_candidates (claimed_at)
  WHERE status = 'claimed';

-- ─── prospects: categorization columns ────────────────────────────────────
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS source_platform TEXT;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS audience_size   INTEGER;
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS industry_tags   TEXT[];
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS geo             TEXT;     -- ISO country code or region
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS quality_score   INTEGER;  -- 0-100 composite score
ALTER TABLE prospects ADD COLUMN IF NOT EXISTS enriched_categorization_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS prospects_quality_idx
  ON prospects (profile_slug, quality_score DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS prospects_audience_idx
  ON prospects (profile_slug, audience_size DESC NULLS LAST);

CREATE INDEX IF NOT EXISTS prospects_industry_idx
  ON prospects USING GIN (industry_tags);

-- ─── RLS (anon role gets full access, same pattern as existing tables) ───
ALTER TABLE prospect_candidates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS prospect_candidates_anon_all ON prospect_candidates;
CREATE POLICY prospect_candidates_anon_all ON prospect_candidates
  FOR ALL TO anon USING (true) WITH CHECK (true);
