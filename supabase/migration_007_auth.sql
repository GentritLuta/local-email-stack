-- LocalEmailStack — migration 007: real auth + RLS lockdown for the client portal
--
-- Run in Supabase → SQL Editor → New query → paste → Run. Idempotent.
--
-- Replaces the blanket "anon full access" policies with auth-scoped RLS so a
-- logged-in client sees ONLY their own rows and an admin sees everything. The
-- public onboarding form no longer writes directly (it goes through the
-- auth-admin Edge Function with the service role), so anon gets NO access to
-- the onboarding/contract tables.
--
-- NOTE: prospects is intentionally untouched — it was already locked by the
-- earlier RLS pass and the public unsubscribe pages rely on the existing
-- unsubscribe_by_token RPC + a narrow anon path. Do not change it here.
--
-- The PC pipeline uses the service_role key (sequences/supabase.env), which
-- bypasses RLS entirely, so none of this affects provisioning / contract seal.

-- ───────────────────────────────────────────────────────────────────────────
-- 1. Roles
-- ───────────────────────────────────────────────────────────────────────────
create table if not exists public.user_roles (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  is_admin   boolean not null default false,
  created_at timestamptz not null default now()
);
alter table public.user_roles enable row level security;

-- Users may read their OWN role row; nobody writes via the API (only the
-- service role / SQL). No write policy => no API writes. Correct by omission.
drop policy if exists "read own role" on public.user_roles;
create policy "read own role" on public.user_roles
  for select to authenticated using (user_id = auth.uid());

-- ───────────────────────────────────────────────────────────────────────────
-- 2. Helper functions (SECURITY DEFINER so policy lookups can't recurse and the
--    search_path can't be hijacked)
-- ───────────────────────────────────────────────────────────────────────────
create or replace function public.is_admin()
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.user_roles
                 where user_id = auth.uid() and is_admin = true);
$$;
revoke all on function public.is_admin() from public;
grant execute on function public.is_admin() to authenticated, anon;

create or replace function public.owns_slug(p_slug text)
returns boolean language sql stable security definer set search_path = public as $$
  select exists (select 1 from public.clients
                 where profile_slug = p_slug and auth_user_id = auth.uid());
$$;
revoke all on function public.owns_slug(text) from public;
grant execute on function public.owns_slug(text) to authenticated, anon;

-- ───────────────────────────────────────────────────────────────────────────
-- 3. clients
-- ───────────────────────────────────────────────────────────────────────────
alter table public.clients enable row level security;
drop policy if exists "anon full access" on public.clients;

drop policy if exists "clients_select" on public.clients;
create policy "clients_select" on public.clients
  for select to authenticated
  using (auth_user_id = auth.uid() or public.is_admin());

drop policy if exists "clients_update" on public.clients;
create policy "clients_update" on public.clients
  for update to authenticated
  using (auth_user_id = auth.uid() or public.is_admin())
  with check (auth_user_id = auth.uid() or public.is_admin());

-- ───────────────────────────────────────────────────────────────────────────
-- 4. onboarding_submissions  (owned via client_id FK)
-- ───────────────────────────────────────────────────────────────────────────
alter table public.onboarding_submissions enable row level security;
drop policy if exists "anon full access" on public.onboarding_submissions;

drop policy if exists "submissions_select" on public.onboarding_submissions;
create policy "submissions_select" on public.onboarding_submissions
  for select to authenticated
  using (
    public.is_admin()
    or exists (select 1 from public.clients c
               where c.id = onboarding_submissions.client_id
                 and c.auth_user_id = auth.uid())
  );

drop policy if exists "submissions_update_admin" on public.onboarding_submissions;
create policy "submissions_update_admin" on public.onboarding_submissions
  for update to authenticated using (public.is_admin()) with check (public.is_admin());

-- ───────────────────────────────────────────────────────────────────────────
-- 5. provisioning_status  (owned via submission → client)
-- ───────────────────────────────────────────────────────────────────────────
alter table public.provisioning_status enable row level security;
drop policy if exists "anon full access" on public.provisioning_status;

drop policy if exists "provstatus_select" on public.provisioning_status;
create policy "provstatus_select" on public.provisioning_status
  for select to authenticated
  using (
    public.is_admin()
    or exists (
      select 1 from public.onboarding_submissions s
      join public.clients c on c.id = s.client_id
      where s.id = provisioning_status.submission_id
        and c.auth_user_id = auth.uid())
  );

-- ───────────────────────────────────────────────────────────────────────────
-- 6. contracts  (owned via client_id; sign = the draft→signed transition only)
-- ───────────────────────────────────────────────────────────────────────────
alter table public.contracts enable row level security;
drop policy if exists "anon full access" on public.contracts;

drop policy if exists "contracts_select" on public.contracts;
create policy "contracts_select" on public.contracts
  for select to authenticated
  using (public.is_admin()
    or exists (select 1 from public.clients c
               where c.id = contracts.client_id and c.auth_user_id = auth.uid()));

-- Owner may move their OWN contract from draft → signed and nothing else. The
-- USING clause checks the OLD row (must be draft + owned); WITH CHECK the NEW
-- row (must be signed + owned). The service-role seal (sets sealed/sha256) is
-- unaffected (bypasses RLS).
drop policy if exists "contracts_sign" on public.contracts;
create policy "contracts_sign" on public.contracts
  for update to authenticated
  using (status = 'draft'
    and exists (select 1 from public.clients c
                where c.id = contracts.client_id and c.auth_user_id = auth.uid()))
  with check (status = 'signed'
    and exists (select 1 from public.clients c
                where c.id = contracts.client_id and c.auth_user_id = auth.uid()));

drop policy if exists "contracts_update_admin" on public.contracts;
create policy "contracts_update_admin" on public.contracts
  for update to authenticated using (public.is_admin()) with check (public.is_admin());

-- ───────────────────────────────────────────────────────────────────────────
-- 7. Campaign-metrics tables read by the client dashboard (getCampaignMetrics):
--    scope to the client's own profile_slug, or admin. (prospects is NOT here —
--    left as-is from the earlier RLS pass.)
-- ───────────────────────────────────────────────────────────────────────────
alter table public.sequences enable row level security;
drop policy if exists "anon full access" on public.sequences;
drop policy if exists "sequences_select" on public.sequences;
create policy "sequences_select" on public.sequences
  for select to authenticated using (public.is_admin() or public.owns_slug(profile_slug));

alter table public.replies enable row level security;
drop policy if exists "anon full access" on public.replies;
drop policy if exists "replies_select" on public.replies;
create policy "replies_select" on public.replies
  for select to authenticated using (public.is_admin() or public.owns_slug(profile_slug));

-- runs has no profile_slug column → join via sequences
alter table public.runs enable row level security;
drop policy if exists "anon full access" on public.runs;
drop policy if exists "runs_select" on public.runs;
create policy "runs_select" on public.runs
  for select to authenticated
  using (public.is_admin()
    or exists (select 1 from public.sequences sq
               where sq.id = runs.sequence_id and public.owns_slug(sq.profile_slug)));

-- ───────────────────────────────────────────────────────────────────────────
-- 8. One identity per email — dedup index (clients table). The find-or-create
--    flow in the Edge Function relies on this to never make two client rows for
--    one email. (Pre-checked: no duplicate emails exist as of migration time.)
-- ───────────────────────────────────────────────────────────────────────────
create unique index if not exists uq_clients_email_lower on public.clients (lower(email));

-- ───────────────────────────────────────────────────────────────────────────
-- 9. Seed the operator as admin. Safe to run before info@ exists (no-op then);
--    re-run after the operator account is created, or rely on the Edge Function
--    grant_admin path. Idempotent.
-- ───────────────────────────────────────────────────────────────────────────
insert into public.user_roles (user_id, is_admin)
select id, true from auth.users where email = 'info@aureonglobal.de'
on conflict (user_id) do update set is_admin = true;
