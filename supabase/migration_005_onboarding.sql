-- LocalEmailStack — migration 005: client onboarding (SaaS dashboard)
--
-- Run in Supabase → SQL Editor → New query → paste → Run. Idempotent.
-- Adds the tables the public SaaS app + onboard-pipeline.py use as a work queue.
--
-- Flow: the web app writes onboarding_submissions(status=pending). The PC
-- pipeline (LES-onboard-pipeline) picks it up, runs provisioning, and writes
-- per-step progress to provisioning_status, flipping submission.status as it goes.

-- ───────────────────────────────────────────────────────────────────────────
-- Tables
-- ───────────────────────────────────────────────────────────────────────────

create table if not exists clients (
  id            uuid primary key default gen_random_uuid(),
  auth_user_id  uuid,                       -- Supabase auth user (null in anon-key v1)
  email         text,                       -- contact / login email
  company       text,
  profile_slug  text references profiles(slug) on delete set null,  -- linked once provisioned
  status        text not null default 'new',  -- new | onboarding | provisioning | live | paused
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table if not exists onboarding_submissions (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid references clients(id) on delete cascade,
  raw_answers   jsonb not null,             -- the full onboarding form payload
  -- pipeline lifecycle:
  status        text not null default 'pending',
  -- pending -> provisioning -> needs_dns | ready -> live | error
  error         text,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table if not exists provisioning_status (
  id            uuid primary key default gen_random_uuid(),
  submission_id uuid references onboarding_submissions(id) on delete cascade,
  step          text not null,              -- profile | copy | domains | leads | warmup | golive
  state         text not null default 'pending',  -- pending | running | done | needs_input | error
  detail        text,                       -- human-readable progress (e.g. "domains 4/12 verified")
  payload       jsonb,                      -- structured extra (e.g. DNS records to paste)
  updated_at    timestamptz not null default now(),
  unique (submission_id, step)
);

create index if not exists idx_submissions_status on onboarding_submissions(status);
create index if not exists idx_provstatus_submission on provisioning_status(submission_id);

-- ───────────────────────────────────────────────────────────────────────────
-- RLS — mirror the existing "anon full access" model (v1 localhost; tighten to
-- per-user RLS when Supabase Auth is added).
-- ───────────────────────────────────────────────────────────────────────────
alter table clients                enable row level security;
alter table onboarding_submissions enable row level security;
alter table provisioning_status    enable row level security;

do $$
declare t text;
begin
  for t in select unnest(array['clients','onboarding_submissions','provisioning_status']) loop
    execute format('drop policy if exists "anon full access" on %I', t);
    execute format(
      'create policy "anon full access" on %I for all to anon using (true) with check (true)', t);
  end loop;
end $$;

-- ───────────────────────────────────────────────────────────────────────────
-- updated_at triggers (reuse set_updated_at() from schema.sql)
-- ───────────────────────────────────────────────────────────────────────────
do $$
declare t text;
begin
  for t in select unnest(array['clients','onboarding_submissions','provisioning_status']) loop
    execute format('drop trigger if exists touch_%I on %I', t, t);
    execute format(
      'create trigger touch_%I before update on %I for each row execute function set_updated_at()', t, t);
  end loop;
end $$;
