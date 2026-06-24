-- LocalEmailStack — migration 006: digital contract signing (self-hosted e-sign)
--
-- Run in Supabase → SQL Editor → New query → paste → Run. Idempotent.
--
-- Adds a `contracts` work-row per onboarding submission. The pilot agreement is
-- auto-generated (Aureon Global L.L.C. as Provider) from the submission's
-- raw_answers, the client click-to-signs it in the SaaS app, and the PC pipeline
-- stamps the server-observed audit trail (IP, user-agent, SHA-256 integrity lock)
-- and renders a locked signed PDF.
--
-- GATE: onboard-pipeline.py refuses to provision (no profile, copy, domains,
-- leads, or warmup) until a signed contract exists for the submission. So no
-- client work — and no sends — ever happen before the agreement is signed.

-- ───────────────────────────────────────────────────────────────────────────
-- contracts
-- ───────────────────────────────────────────────────────────────────────────
create table if not exists contracts (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid references clients(id) on delete cascade,
  submission_id   uuid references onboarding_submissions(id) on delete cascade,
  profile_slug    text,                       -- linked once provisioned (no FK: contract precedes profile)
  contract_ref    text not null,              -- e.g. "AG ACME 2026 01 v1.0"
  contract_html   text not null,              -- the full generated agreement at draft time

  -- lifecycle: draft -> (client signs) -> signed -> (pipeline stamps) -> sealed
  --            void  (superseded / cancelled)
  status          text not null default 'draft',

  -- ─── client-supplied sign intent (written by the browser) ────────────────
  signer_name     text,                       -- typed full legal name
  signer_email    text,                       -- who signed
  signer_title    text,                       -- their title (optional)
  signature_text  text,                       -- the typed signature string
  consent         boolean not null default false,  -- "I agree to be legally bound" checkbox
  signed_at       timestamptz,                -- client click time (browser)

  -- ─── server-observed audit trail (stamped by the PC pipeline) ────────────
  signer_ip       text,                       -- IP observed server-side at seal time
  signer_user_agent text,
  contract_sha256 text,                       -- sha256 of contract_html at seal — integrity lock
  sealed_at       timestamptz,                -- when the pipeline finalized + locked
  signed_pdf_path text,                       -- local path to the rendered signed PDF

  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  unique (submission_id)                       -- one live contract per submission
);

create index if not exists idx_contracts_submission on contracts(submission_id);
create index if not exists idx_contracts_status on contracts(status);

-- ───────────────────────────────────────────────────────────────────────────
-- RLS — mirror the existing "anon full access" v1 model (localhost; tighten to
-- per-user RLS when Supabase Auth lands). Anon may read its draft + write the
-- sign intent; the pipeline uses the service key for the seal stamp.
-- ───────────────────────────────────────────────────────────────────────────
alter table contracts enable row level security;
drop policy if exists "anon full access" on contracts;
create policy "anon full access" on contracts for all to anon using (true) with check (true);

-- updated_at trigger (reuse set_updated_at() from schema.sql)
drop trigger if exists touch_contracts on contracts;
create trigger touch_contracts before update on contracts
  for each row execute function set_updated_at();
