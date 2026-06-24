-- LocalEmailStack — migration 009: billing profiles (charge authorization on file)
--
-- Run in Supabase → SQL Editor, or via the Management API. Idempotent.
--
-- After a client signs their service agreement they complete a billing-on-file
-- step: their billing identity + funding method (Payoneer email / IBAN) + a
-- click-to-sign charge authorization (general wording — "AUREON may charge me
-- via Payoneer / my provided method for services rendered"). Stored with the
-- same evidence trail as the contract (timestamp, IP, user-agent, SHA-256).
--
-- NO raw card PAN / CVV is stored here (PCI). The card_* columns hold only a
-- tokenized reference + last4/brand IF a PCI processor is added later.
--
-- RLS: a client (auth.uid()) reads + inserts their OWN row; admins read all.

create table if not exists public.billing_profiles (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid references public.clients(id) on delete cascade,
  profile_slug    text,
  -- billing identity
  billing_name    text,                 -- billing contact full name
  legal_name      text,                 -- company legal name
  billing_email   text,
  address_line    text,
  city            text,
  postal_code     text,
  country         text,
  vat_id          text,                 -- VAT / tax ID (optional)
  -- funding identity (no raw card data)
  payoneer_email  text,
  iban            text,
  -- tokenized card reference ONLY (filled by a PCI processor later; never raw)
  card_token      text,
  card_last4      text,
  card_brand      text,
  card_exp        text,
  -- charge authorization (the signed mandate)
  authorized      boolean not null default false,
  authorization_text text,              -- exact wording the client agreed to
  authorized_at   timestamptz,
  signer_ip       text,
  signer_user_agent text,
  authorization_sha text,               -- SHA-256 of (text + identity + ts) audit hash
  -- where the per-invoice charge runs
  payoneer_status text,                 -- pending | requested | charged | failed (per latest action)
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (client_id)
);

create index if not exists idx_billing_client on public.billing_profiles(client_id);
create index if not exists idx_billing_slug on public.billing_profiles(profile_slug);

alter table public.billing_profiles enable row level security;

-- Client reads their own; admin reads all.
drop policy if exists "billing_select" on public.billing_profiles;
create policy "billing_select" on public.billing_profiles
  for select to authenticated
  using (public.is_admin()
    or exists (select 1 from public.clients c
               where c.id = billing_profiles.client_id and c.auth_user_id = auth.uid()));

-- Client inserts/updates their own row; admin all. (The Edge Function uses the
-- service role and bypasses RLS, but this keeps the table safe for direct client
-- writes too.)
drop policy if exists "billing_client_write" on public.billing_profiles;
create policy "billing_client_write" on public.billing_profiles
  for all to authenticated
  using (public.is_admin()
    or exists (select 1 from public.clients c
               where c.id = billing_profiles.client_id and c.auth_user_id = auth.uid()))
  with check (public.is_admin()
    or exists (select 1 from public.clients c
               where c.id = billing_profiles.client_id and c.auth_user_id = auth.uid()));

drop trigger if exists touch_billing on public.billing_profiles;
create trigger touch_billing before update on public.billing_profiles
  for each row execute function public.set_updated_at();
