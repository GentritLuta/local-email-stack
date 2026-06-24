-- LocalEmailStack — migration 008: CRM (invoices + sales) for the client portal
--
-- Run in Supabase → SQL Editor, or via the Management API. Idempotent.
--
-- Adds the two tables the dashboard CRM reads: invoices (imported from the
-- AUREON Factur-X invoice generator or entered by an admin) and sales (closed
-- deals / revenue). Reply outcomes are DERIVED live from replies.raw_headers —
-- no table needed.
--
-- RLS mirrors migration_007: a client (auth.uid()) sees only rows for a client
-- record they own; admins (is_admin()) see all; clients cannot write (only the
-- admin / service role writes invoices + sales).

-- ───────────────────────────────────────────────────────────────────────────
-- invoices
-- ───────────────────────────────────────────────────────────────────────────
create table if not exists public.invoices (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid references public.clients(id) on delete cascade,
  profile_slug  text,
  invoice_ref   text not null,
  title         text,
  amount_cents  bigint not null default 0,
  due_cents     bigint,                      -- outstanding amount (Factur-X DuePayableAmount)
  currency      text not null default 'EUR',
  status        text not null default 'sent',  -- draft | sent | paid | overdue | void
  issued_at     date,
  due_at        date,
  paid_at       timestamptz,
  pdf_path      text,
  source        text not null default 'manual', -- manual | facturx
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now(),
  unique (invoice_ref)
);

-- ───────────────────────────────────────────────────────────────────────────
-- sales (closed deals / revenue tracking)
-- ───────────────────────────────────────────────────────────────────────────
create table if not exists public.sales (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid references public.clients(id) on delete cascade,
  profile_slug   text,
  prospect_email text,
  amount_cents   bigint not null default 0,
  currency       text not null default 'EUR',
  status         text not null default 'won',  -- won | pipeline | lost
  closed_at      timestamptz,
  note           text,
  created_at     timestamptz not null default now()
);

create index if not exists idx_invoices_client on public.invoices(client_id);
create index if not exists idx_invoices_slug on public.invoices(profile_slug);
create index if not exists idx_sales_client on public.sales(client_id);
create index if not exists idx_sales_slug on public.sales(profile_slug);

-- ───────────────────────────────────────────────────────────────────────────
-- RLS — client reads own (via client_id -> auth.uid()); admin all + writes.
-- ───────────────────────────────────────────────────────────────────────────
alter table public.invoices enable row level security;
alter table public.sales    enable row level security;

drop policy if exists "invoices_select" on public.invoices;
create policy "invoices_select" on public.invoices
  for select to authenticated
  using (public.is_admin()
    or exists (select 1 from public.clients c
               where c.id = invoices.client_id and c.auth_user_id = auth.uid()));

drop policy if exists "invoices_admin_write" on public.invoices;
create policy "invoices_admin_write" on public.invoices
  for all to authenticated using (public.is_admin()) with check (public.is_admin());

drop policy if exists "sales_select" on public.sales;
create policy "sales_select" on public.sales
  for select to authenticated
  using (public.is_admin()
    or exists (select 1 from public.clients c
               where c.id = sales.client_id and c.auth_user_id = auth.uid()));

drop policy if exists "sales_admin_write" on public.sales;
create policy "sales_admin_write" on public.sales
  for all to authenticated using (public.is_admin()) with check (public.is_admin());

-- updated_at trigger for invoices (reuse set_updated_at from schema.sql)
drop trigger if exists touch_invoices on public.invoices;
create trigger touch_invoices before update on public.invoices
  for each row execute function public.set_updated_at();
