-- LocalEmailStack — migration 011: client sending-infrastructure credentials
--
-- Run in Supabase → SQL Editor, or via the Management API. Idempotent.
--
-- After a client signs their pilot agreement they complete an access step in the
-- portal (/access/:id): they hand over a SCOPED API token for their DNS / domain
-- host (Hostinger, Cloudflare, etc.) plus any other access notes, with a
-- click-to-sign authorization to use it to provision and operate their sending
-- infrastructure. Stored with the same evidence trail as the contract + billing
-- (timestamp, IP, user-agent, SHA-256).
--
-- We deliberately ask for a SCOPED, REVOCABLE API TOKEN rather than an account
-- password: it is what the provisioning pipeline (push-client-dns.py / the
-- Hostinger + Cloudflare provisioners) needs to auto-publish DNS, and the client
-- can revoke it at any time without changing their account password.
--
-- credentials-sync.py (local) reads new rows, writes the token into
-- sequences/hostinger.env as HOSTINGER_API_TOKEN_<SLUG>, and emails info@ the
-- combined onboarding + access summary. Idempotent via written_to_env_at +
-- notified_at (the Edge Function nulls them on upsert so re-submits re-sync).
--
-- RLS: a client (auth.uid()) reads + writes their OWN row; admins read all.

create table if not exists public.client_credentials (
  id                uuid primary key default gen_random_uuid(),
  client_id         uuid references public.clients(id) on delete cascade,
  profile_slug      text,
  -- which infrastructure the token is for
  registrar         text,                 -- free text: "Hostinger", "Cloudflare", "GoDaddy"…
  dns_host          text,                 -- cloudflare | hostinger | other (mirrors onboarding)
  -- the scoped, revocable API token (NOT an account password)
  api_token         text,
  other_access      text,                 -- any additional access notes the client pastes
  notes             text,
  -- authorization (the signed mandate to use the access)
  authorized        boolean not null default false,
  authorization_text text,                -- exact wording the client agreed to
  authorized_at     timestamptz,
  signer_ip         text,
  signer_user_agent text,
  authorization_sha text,                 -- SHA-256 of (text + identity + ts) audit hash
  -- local-sync flags
  written_to_env_at timestamptz,          -- token written into hostinger.env
  notified_at       timestamptz,          -- info@ emailed the combined details
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  unique (client_id)
);

create index if not exists idx_credentials_client on public.client_credentials(client_id);
create index if not exists idx_credentials_slug on public.client_credentials(profile_slug);

alter table public.client_credentials enable row level security;

-- Client reads their own; admin reads all.
drop policy if exists "credentials_select" on public.client_credentials;
create policy "credentials_select" on public.client_credentials
  for select to authenticated
  using (public.is_admin()
    or exists (select 1 from public.clients c
               where c.id = client_credentials.client_id and c.auth_user_id = auth.uid()));

-- Client inserts/updates their own row; admin all. (The Edge Function uses the
-- service role and bypasses RLS; this keeps direct client writes safe too.)
drop policy if exists "credentials_client_write" on public.client_credentials;
create policy "credentials_client_write" on public.client_credentials
  for all to authenticated
  using (public.is_admin()
    or exists (select 1 from public.clients c
               where c.id = client_credentials.client_id and c.auth_user_id = auth.uid()))
  with check (public.is_admin()
    or exists (select 1 from public.clients c
               where c.id = client_credentials.client_id and c.auth_user_id = auth.uid()));

drop trigger if exists touch_credentials on public.client_credentials;
create trigger touch_credentials before update on public.client_credentials
  for each row execute function public.set_updated_at();
