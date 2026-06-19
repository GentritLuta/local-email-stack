-- migration_013: at most one in-flight onboarding submission per client.
-- Before this, every form POST inserted a new onboarding_submissions row, so
-- resubmitting on the same email stacked unlimited submissions (mark-eting had 3),
-- each of which could spawn its own profile. The auth-admin `submit` action now
-- reuses the open submission; this partial unique index enforces it at the DB level.
-- Terminal states (live / error / superseded / cancelled) do not block a fresh start.

create unique index if not exists uq_one_open_submission_per_client
  on public.onboarding_submissions (client_id)
  where status in ('pending', 'provisioning', 'needs_dns', 'ready', 'awaiting_signature');
