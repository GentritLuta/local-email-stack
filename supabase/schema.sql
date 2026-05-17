-- LocalEmailStack — Supabase schema
--
-- Run this in Supabase → SQL Editor → New query → paste → Run.
-- Idempotent (re-running is safe). All tables get realtime + RLS enabled.
--
-- After running:
--   1. Project Settings → API → copy 'Project URL' and 'anon' public key
--   2. Paste both into desktop app Settings → Sync (or sequences/supabase.env)

-- ───────────────────────────────────────────────────────────────────────────
-- Core tables
-- ───────────────────────────────────────────────────────────────────────────

create table if not exists profiles (
  slug          text primary key,
  name          text not null,
  config        jsonb not null,         -- full profile JSON (mailboxes, voice, warmup, etc.)
  active        boolean not null default true,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create table if not exists variants (
  id            uuid primary key default gen_random_uuid(),
  profile_slug  text references profiles(slug) on delete cascade,
  n             int not null,            -- 1..20 within a profile's variant set
  angle         text,                    -- soft_intro, data_anchor, etc.
  subject       text not null,
  body          text not null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (profile_slug, n)
);

create table if not exists sequences (
  id              uuid primary key default gen_random_uuid(),
  profile_slug    text references profiles(slug) on delete cascade,
  slug            text not null,         -- per-profile unique identifier
  name            text not null,
  description     text,
  stop_on_reply   boolean not null default true,
  stop_on_bounce  boolean not null default true,
  active          boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (profile_slug, slug)
);

create table if not exists sequence_steps (
  id              uuid primary key default gen_random_uuid(),
  sequence_id     uuid references sequences(id) on delete cascade,
  step_n          int not null,
  delay_days      int not null default 0,         -- days after the previous step
  variant_id      uuid references variants(id),   -- optional: pull from variant library
  inline_subject  text,                            -- or one-off subject/body for this step
  inline_body     text,
  forced_persona  text,                            -- optional: lock step to one persona
  created_at      timestamptz not null default now(),
  unique (sequence_id, step_n)
);

create table if not exists prospects (
  id              uuid primary key default gen_random_uuid(),
  profile_slug    text references profiles(slug) on delete cascade,
  email           text not null,
  first_name      text,
  last_name       text,
  company         text,
  custom_fields   jsonb,
  source          text,                  -- where this prospect came from
  created_at      timestamptz not null default now(),
  unique (profile_slug, email)
);

-- Verification + enrichment columns (added 2026-05-17, autonomous lead pipeline)
alter table prospects add column if not exists verified            boolean not null default false;
alter table prospects add column if not exists verified_at         timestamptz;
alter table prospects add column if not exists verification_method text;   -- mx_verified | smtp_verified | invalid_syntax | disposable | no_mx | smtp_rejected | smtp_failed
alter table prospects add column if not exists verification_error  text;
alter table prospects add column if not exists mx_hosts            jsonb;  -- ordered MX records used at verification time
alter table prospects add column if not exists niche_slug          text;   -- niche that produced this lead
alter table prospects add column if not exists title               text;   -- role/title (e.g. "Co-Owner")
alter table prospects add column if not exists phone               text;
alter table prospects add column if not exists city                text;
alter table prospects add column if not exists state               text;
alter table prospects add column if not exists website             text;   -- the lead's company/personal site
alter table prospects add column if not exists source_url          text;   -- exact URL we scraped them from
alter table prospects add column if not exists enriched_context    jsonb;  -- product, pricing, target customer, case studies, social (filled by context_autofill.py)
alter table prospects add column if not exists enriched_at         timestamptz;  -- when context_autofill last touched this row
create index if not exists idx_prospects_enriched_at on prospects (enriched_at);

-- Unsubscribe state. Each prospect gets a stable per-prospect token so the
-- email's "Unsubscribe" button hits a static page that PATCHes prospects
-- (RLS allows it via the matching token).
alter table prospects add column if not exists unsubscribed        boolean not null default false;
alter table prospects add column if not exists unsubscribed_at     timestamptz;
alter table prospects add column if not exists unsubscribe_token   text;
update prospects set unsubscribe_token = gen_random_uuid()::text where unsubscribe_token is null;
alter table prospects alter column unsubscribe_token set default gen_random_uuid()::text;
alter table prospects alter column unsubscribe_token set not null;
create unique index if not exists idx_prospects_unsub_token on prospects (unsubscribe_token);

create index if not exists idx_prospects_verified    on prospects (verified);
create index if not exists idx_prospects_niche       on prospects (niche_slug);

create table if not exists runs (
  id              uuid primary key default gen_random_uuid(),
  sequence_id     uuid references sequences(id) on delete cascade,
  prospect_id     uuid references prospects(id) on delete cascade,
  persona_slug    text,                  -- which persona this run uses (rotated)
  status          text not null default 'queued',  -- queued | running | paused_replied | paused_bounced | completed | cancelled
  current_step    int not null default 1,
  next_send_at    timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (sequence_id, prospect_id)
);

create table if not exists send_log (
  id              uuid primary key default gen_random_uuid(),
  run_id          uuid references runs(id) on delete cascade,
  step_n          int not null,
  persona_slug    text,
  from_addr       text not null,
  to_addr         text not null,
  subject         text not null,
  resend_id       text,
  message_id      text,
  delivered       boolean,
  bounced         boolean default false,
  replied         boolean default false,
  complained      boolean default false,
  opened_at       timestamptz,
  clicked_at      timestamptz,
  sent_at         timestamptz not null default now(),
  error           text
);

create table if not exists replies (
  id              uuid primary key default gen_random_uuid(),
  run_id          uuid references runs(id),         -- nullable: unattributed replies still recorded
  profile_slug    text references profiles(slug),
  from_addr       text not null,
  to_addr         text not null,
  subject         text,
  class           text not null,        -- reply | bounce | complaint | unrelated
  body_snippet    text,
  raw_headers     jsonb,
  received_at     timestamptz not null default now()
);

create table if not exists warmup_state (
  profile_slug    text primary key references profiles(slug) on delete cascade,
  enabled         boolean not null default false,
  current_day     int not null default 0,
  started_at      date,
  last_tick_at    timestamptz,
  reputation      jsonb not null default '{}',
  updated_at      timestamptz not null default now()
);

-- ───────────────────────────────────────────────────────────────────────────
-- Realtime + indexes
-- ───────────────────────────────────────────────────────────────────────────

-- Indexes for the hot paths
create index if not exists idx_runs_next_send_at    on runs (next_send_at) where status = 'queued';
create index if not exists idx_runs_status          on runs (status);
create index if not exists idx_send_log_run         on send_log (run_id, step_n);
create index if not exists idx_send_log_sent_at     on send_log (sent_at desc);
create index if not exists idx_replies_received_at  on replies (received_at desc);

-- Enable realtime on the tables the desktop app subscribes to
alter publication supabase_realtime add table profiles;
alter publication supabase_realtime add table sequences;
alter publication supabase_realtime add table runs;
alter publication supabase_realtime add table send_log;
alter publication supabase_realtime add table replies;
alter publication supabase_realtime add table warmup_state;

-- ───────────────────────────────────────────────────────────────────────────
-- Row Level Security
-- ───────────────────────────────────────────────────────────────────────────
-- For a single-tenant personal control plane, we just allow the anon role
-- full access (the URL+anon-key acts as the auth boundary).
-- For multi-user later, switch to JWT-based policies.

alter table profiles        enable row level security;
alter table variants        enable row level security;
alter table sequences       enable row level security;
alter table sequence_steps  enable row level security;
alter table prospects       enable row level security;
alter table runs            enable row level security;
alter table send_log        enable row level security;
alter table replies         enable row level security;
alter table warmup_state    enable row level security;

do $$
declare t text;
begin
  for t in select unnest(array[
    'profiles','variants','sequences','sequence_steps',
    'prospects','runs','send_log','replies','warmup_state'
  ]) loop
    execute format('drop policy if exists "anon full access" on %I', t);
    execute format(
      'create policy "anon full access" on %I for all to anon using (true) with check (true)',
      t
    );
  end loop;
end $$;

-- Trigger to keep updated_at in sync
create or replace function set_updated_at() returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end $$;

do $$
declare t text;
begin
  for t in select unnest(array['profiles','variants','sequences','runs','warmup_state']) loop
    execute format('drop trigger if exists touch_%I on %I', t, t);
    execute format(
      'create trigger touch_%I before update on %I for each row execute function set_updated_at()',
      t, t
    );
  end loop;
end $$;
