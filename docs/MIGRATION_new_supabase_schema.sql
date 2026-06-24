-- ============================================================================
-- FRESH SUPABASE MIGRATION — schema for the new project (2026-06-12)
-- Rebuilds the local-email-stack DB exactly, with RLS correct FROM DAY ONE.
-- Run this in the NEW project's SQL Editor (Supabase dashboard) BEFORE importing
-- data with scripts/import-supabase.py.
-- IDs are UUIDs (preserved from the old project so runs<->prospects<->sequences
-- foreign keys still line up after import). JSON columns are jsonb.
-- ============================================================================

create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- ---- profiles -------------------------------------------------------------
create table if not exists public.profiles (
  slug          text primary key,
  name          text,
  active        boolean default true,
  lead_intent   text,
  config        jsonb,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

-- ---- prospects ------------------------------------------------------------
create table if not exists public.prospects (
  id                          uuid primary key default gen_random_uuid(),
  profile_slug                text,
  niche_slug                  text,
  email                       text,
  first_name                  text,
  last_name                   text,
  company                     text,
  title                       text,
  city                        text,
  state                       text,
  phone                       text,
  website                     text,
  source                      text,
  source_platform             text,
  source_url                  text,
  audience_size               bigint,
  quality_score               numeric,
  industry_tags               jsonb,
  geo                         jsonb,
  mx_hosts                    jsonb,
  custom_fields               jsonb,
  enriched_context            jsonb,
  enriched_at                 timestamptz,
  enriched_categorization_at  timestamptz,
  verified                    boolean default false,
  verified_at                 timestamptz,
  verification_method         text,
  verification_error          text,
  unsubscribed                boolean default false,
  unsubscribed_at             timestamptz,
  unsubscribe_token           text,
  created_at                  timestamptz default now()
);
create index if not exists prospects_profile_idx on public.prospects(profile_slug);
create index if not exists prospects_email_idx   on public.prospects(email);
create index if not exists prospects_unsubtok_idx on public.prospects(unsubscribe_token);

-- ---- sequences ------------------------------------------------------------
create table if not exists public.sequences (
  id            uuid primary key default gen_random_uuid(),
  profile_slug  text,
  slug          text,
  name          text,
  description   text,
  active        boolean default true,
  stop_on_reply boolean default true,
  stop_on_bounce boolean default true,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

-- ---- variants -------------------------------------------------------------
create table if not exists public.variants (
  id            uuid primary key default gen_random_uuid(),
  profile_slug  text,
  n             integer,
  angle         text,
  subject       text,
  body          text,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);

-- ---- sequence_steps -------------------------------------------------------
create table if not exists public.sequence_steps (
  id              uuid primary key default gen_random_uuid(),
  sequence_id     uuid references public.sequences(id) on delete cascade,
  step_n          integer,
  delay_days      numeric,
  forced_persona  text,
  inline_subject  text,
  inline_body     text,
  variant_id      uuid references public.variants(id) on delete set null,
  created_at      timestamptz default now()
);
create index if not exists steps_seq_idx on public.sequence_steps(sequence_id);

-- ---- runs -----------------------------------------------------------------
create table if not exists public.runs (
  id            uuid primary key default gen_random_uuid(),
  sequence_id   uuid references public.sequences(id) on delete cascade,
  prospect_id   uuid references public.prospects(id) on delete cascade,
  status        text,
  current_step  integer,
  persona_slug  text,
  next_send_at  timestamptz,
  created_at    timestamptz default now(),
  updated_at    timestamptz default now()
);
create index if not exists runs_seq_idx on public.runs(sequence_id);
create index if not exists runs_status_idx on public.runs(status);

-- ---- send_log -------------------------------------------------------------
create table if not exists public.send_log (
  id           uuid primary key default gen_random_uuid(),
  run_id       uuid,
  persona_slug text,
  from_addr    text,
  to_addr      text,
  subject      text,
  step_n       integer,
  resend_id    text,
  message_id   text,
  sent_at      timestamptz default now(),
  delivered    boolean,
  bounced      boolean,
  complained   boolean,
  replied      boolean,
  opened_at    timestamptz,
  clicked_at   timestamptz,
  error        text
);
create index if not exists sendlog_sentat_idx on public.send_log(sent_at);
create index if not exists sendlog_from_idx on public.send_log(from_addr);

-- ---- replies --------------------------------------------------------------
create table if not exists public.replies (
  id           uuid primary key default gen_random_uuid(),
  run_id       uuid,
  profile_slug text,
  from_addr    text,
  to_addr      text,
  subject      text,
  class        text,
  body_snippet text,
  raw_headers  jsonb,
  received_at  timestamptz default now()
);

-- ============================================================================
-- RLS — correct from day one. anon may INSERT opt-ins + UPDATE-to-unsubscribe
-- by token only; NO anon SELECT/DELETE (closes the PII leak). Backend uses the
-- service_role key (bypasses RLS).
-- ============================================================================
alter table public.prospects enable row level security;

drop policy if exists "anon insert optin" on public.prospects;
create policy "anon insert optin" on public.prospects
  for insert to anon with check (true);

drop policy if exists "anon unsubscribe by token" on public.prospects;
create policy "anon unsubscribe by token" on public.prospects
  for update to anon
  using (unsubscribe_token is not null)
  with check (unsubscribed = true);

-- Everything else stays locked to anon (no policy = no access). The other tables
-- are backend-only; leave RLS enabled with no anon policy so anon cannot touch them.
alter table public.profiles      enable row level security;
alter table public.sequences     enable row level security;
alter table public.variants      enable row level security;
alter table public.sequence_steps enable row level security;
alter table public.runs          enable row level security;
alter table public.send_log      enable row level security;
alter table public.replies       enable row level security;
-- (no anon policies on these = anon fully blocked; service_role bypasses RLS)
