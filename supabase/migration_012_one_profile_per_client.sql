-- migration_012: one profile per client.
-- A client maps to at most one provisioning profile. Before this, the onboard
-- pipeline minted a fresh slug (company-2, company-3, ...) for every submission,
-- so a client that submitted three times got three profiles (the mark-eting bug).
-- The pipeline now reuses clients.profile_slug; this index is the belt-and-suspenders
-- DB guarantee. NULLs (not yet provisioned) are exempt.

create unique index if not exists uq_clients_profile_slug
  on public.clients (profile_slug)
  where profile_slug is not null;
