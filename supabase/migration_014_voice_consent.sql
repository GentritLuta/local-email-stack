-- migration_014_voice_consent.sql
-- Consent + call-tracking fields for the AI voice agent (voice-agent/).
-- An AI-cloned voice is an "artificial voice" under the TCPA, so a number is only
-- dialable with prior express consent on record. These columns are what
-- voice-agent/compliance.can_call() reads and what dial.py writes back.
alter table prospects add column if not exists consent_to_ai_call boolean not null default false;
alter table prospects add column if not exists call_consent_at     timestamptz;
alter table prospects add column if not exists call_consent_source text;   -- e.g. 'home_value_funnel'
alter table prospects add column if not exists dnc                 boolean not null default false;
alter table prospects add column if not exists last_call_at        timestamptz;
alter table prospects add column if not exists call_outcome        text;    -- booked|callback|not_interested|do_not_call|no_answer

-- Fast pull of the callable pool (freshest consent first = speed-to-lead).
create index if not exists idx_prospects_callable
  on prospects (call_consent_at desc)
  where consent_to_ai_call = true and dnc = false and unsubscribed = false;
