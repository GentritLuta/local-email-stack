-- LocalEmailStack — migration 010: continuation agreements
--
-- The pilot agreement (signed at onboarding) is now billing-free. ~90 days after
-- the pilot is signed, a CONTINUATION agreement is auto-issued (10% commission,
-- EUR 500/mo retainer, 12-month term, governed by the Client's own jurisdiction).
-- Billing-on-file unlocks only after the client signs the continuation.
--
-- A client therefore has up to two contracts: kind='pilot' and kind='continuation'.
-- The old unique(submission_id) blocked that; we relax it to unique per (submission, kind).

-- 1. kind column (existing rows are pilots).
alter table public.contracts add column if not exists kind text not null default 'pilot';

-- 2. Replace the single-contract-per-submission constraint with per-kind.
alter table public.contracts drop constraint if exists contracts_submission_id_key;
drop index if exists contracts_submission_kind_uq;
create unique index contracts_submission_kind_uq
  on public.contracts (submission_id, kind);

-- 3. Track that the client was emailed to sign the continuation (avoid re-spamming).
alter table public.contracts add column if not exists notified_at timestamptz;

-- Existing rows: ensure kind is set.
update public.contracts set kind = 'pilot' where kind is null;
