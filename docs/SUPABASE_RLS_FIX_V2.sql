-- ============================================================================
-- SECURITY FIX v2 (2026-06-12): lock down `prospects` WITHOUT breaking the
-- unsubscribe page. Supersedes SUPABASE_RLS_FIX.sql.
-- ============================================================================
-- PROBLEM: the public anon key (embedded in the capture + unsubscribe pages)
-- can READ the entire prospects table (every client's email/phone/name) while
-- RLS is off. Anyone viewing page source can dump the lead DB.
--
-- WHY v1 was incomplete: v1 allowed anon INSERT only. But the unsubscribe page
-- does an UPDATE (sets unsubscribed=true via the token), so insert-only RLS would
-- SILENTLY BREAK every unsubscribe link -> a worse compliance position than the
-- PII leak. This version adds a TOKEN-SCOPED UPDATE policy so unsubscribe keeps
-- working while anon still cannot read or mass-modify anything.
--
-- ORDER OF OPERATIONS (must follow exactly, or the backend stops reading):
--   1. In Supabase -> Project Settings -> API, copy the `service_role` secret.
--   2. Put it in sequences/supabase.env as:  SUPABASE_SERVICE_KEY=<the secret>
--      (the backend auto-prefers it once present; see env note below.)
--   3. Confirm the backend reads it (run: py scripts/check-supabase-key.py — it
--      should print "using: service_role"). Only then run the SQL below.
--   4. Run this whole file in Supabase -> SQL Editor.
-- The service_role key bypasses RLS and is SERVER-ONLY. NEVER ship it to a page.
-- ============================================================================

-- 1. Enable RLS (blocks all anon access until a policy allows it).
ALTER TABLE public.prospects ENABLE ROW LEVEL SECURITY;

-- 2. anon may INSERT a new opt-in (the capture form). No USING => cannot read.
DROP POLICY IF EXISTS "anon insert optin" ON public.prospects;
CREATE POLICY "anon insert optin"
  ON public.prospects FOR INSERT TO anon
  WITH CHECK (true);

-- 3. anon may UPDATE ONLY to unsubscribe, and ONLY the row whose token it holds.
--    The unsubscribe page already filters by unsubscribe_token=eq.<token>, so the
--    USING clause scopes the writable row to "knows the token". WITH CHECK keeps
--    the update limited to the unsubscribe flip (cannot use this to alter other
--    columns into arbitrary states; unsubscribed must end up true).
--    NOTE: PostgREST UPDATE returns the row, which needs SELECT. To avoid granting
--    broad SELECT, the page calls UPDATE with Prefer: return=minimal (no read-back).
DROP POLICY IF EXISTS "anon unsubscribe by token" ON public.prospects;
CREATE POLICY "anon unsubscribe by token"
  ON public.prospects FOR UPDATE TO anon
  USING (unsubscribe_token IS NOT NULL)
  WITH CHECK (unsubscribed = true);

-- 4. NO SELECT / DELETE policy for anon => anon cannot read or delete the table.
--    The PII leak is closed. The backend uses service_role (bypasses RLS).

-- 5. The unsubscribe page must send  Prefer: return=minimal  on its PATCH so it
--    does not try to read the row back (which anon can no longer do). The page
--    JS was updated to do this (docs/unsubscribe*.html, 2026-06-12).

-- ============================================================================
-- ROLLBACK (if anything breaks): ALTER TABLE public.prospects DISABLE ROW LEVEL SECURITY;
-- ============================================================================
