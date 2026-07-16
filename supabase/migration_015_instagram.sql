-- LocalEmailStack — migration 015: per-client Instagram publishing credentials
--
-- Run in Supabase → SQL Editor (idempotent). Extends client_credentials (011).
--
-- A social/both client connects their own Instagram in the portal
-- (/connect-instagram): they paste a long-lived Meta Graph API token. The
-- auth-admin Edge Function (action: connect_instagram) verifies the token against
-- the Graph API server-side, derives the IG Business account id + @username, and
-- stores them on the client's row with the service role. The token, like api_token,
-- is NEVER selected back to the browser.
--
-- credentials-sync.py reads new rows (ig_written_to_env_at is null) and writes
-- IG_<SLUG>_TOKEN / IG_<SLUG>_USER_ID into SocialForge's env so the poster can
-- publish, then stamps ig_written_to_env_at. RLS is inherited from 011
-- (own-row read/write by client_id → clients.auth_user_id; admin all).

alter table public.client_credentials
  add column if not exists ig_access_token      text,
  add column if not exists ig_user_id           text,
  add column if not exists ig_username          text,
  add column if not exists ig_token_verified_at timestamptz,
  add column if not exists ig_written_to_env_at timestamptz;
