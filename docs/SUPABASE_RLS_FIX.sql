-- ============================================================================
-- SECURITY FIX: lock down the `prospects` table (run in Supabase SQL editor)
-- ============================================================================
-- PROBLEM (found 2026-06-10): the public anon key is embedded in the live
-- home-value capture page. With RLS off, that key can READ the entire prospects
-- table (every client's leads: email, phone, name). Anyone who views the page
-- source can dump the whole lead database. This closes that hole: anonymous
-- visitors may INSERT a new opt-in, but may NOT read, update, or delete anything.
--
-- The backend scripts must then use the SERVICE_ROLE key (which bypasses RLS) to
-- read/write — see the note at the bottom. Run this in the Supabase dashboard:
-- Project -> SQL Editor -> paste -> Run.
-- ============================================================================

-- 1. Turn RLS on (blocks ALL access until a policy explicitly allows it).
ALTER TABLE public.prospects ENABLE ROW LEVEL SECURITY;

-- 2. Allow the public/anon role to INSERT only (the capture form needs this).
--    No USING clause = cannot read; no UPDATE/DELETE policy = cannot modify.
DROP POLICY IF EXISTS "anon can insert opt-ins" ON public.prospects;
CREATE POLICY "anon can insert opt-ins"
  ON public.prospects
  FOR INSERT
  TO anon
  WITH CHECK (true);

-- 3. (Optional but recommended) restrict anon inserts to funnel sources only,
--    so the public key can't be used to flood arbitrary rows. Replace policy #2
--    with this stricter version if you want:
-- DROP POLICY IF EXISTS "anon can insert opt-ins" ON public.prospects;
-- CREATE POLICY "anon can insert funnel opt-ins"
--   ON public.prospects FOR INSERT TO anon
--   WITH CHECK (source IN ('home_value_funnel'));

-- 4. Do the same for the `replies` table if the unsubscribe pages write to it
--    with the anon key (check before enabling; uncomment if so):
-- ALTER TABLE public.replies ENABLE ROW LEVEL SECURITY;

-- ============================================================================
-- AFTER RUNNING THIS:
--   - The capture page still works (anon INSERT allowed).
--   - The anon key can NO LONGER read prospects (PII leak closed).
--   - The backend (daily-report, fulfillers, sequence-runner, etc.) currently
--     authenticates with the ANON key and will STOP being able to read. You must
--     switch the backend to the SERVICE_ROLE key (Supabase dashboard ->
--     Project Settings -> API -> service_role secret) stored in
--     sequences/supabase.env as SUPABASE_SERVICE_KEY, and point the scripts'
--     read/write headers at it. The service_role key bypasses RLS and must NEVER
--     be shipped to a browser/page — server-side only.
-- ============================================================================

-- ============================================================================
-- BACKEND MIGRATION (do AFTER running the RLS above + adding the service key)
-- ============================================================================
-- The backend reads SUPABASE_ANON_KEY in ~87 places. Once RLS is on, anon can no
-- longer read, so the backend must use the service_role key. The lowest-risk way
-- (no edit to 87 call-sites): the scripts read the key via env. Set BOTH in
-- sequences/supabase.env:
--     SUPABASE_ANON_KEY=...        (keep; still used by public pages)
--     SUPABASE_SERVICE_KEY=...     (NEW: from Supabase -> Project Settings -> API -> service_role)
-- Then change the key the SERVER scripts pick up to prefer the service key, e.g. in the
-- shared env-read replace `env["SUPABASE_ANON_KEY"]` with
--     env.get("SUPABASE_SERVICE_KEY") or env["SUPABASE_ANON_KEY"]
-- in the server-side scripts (daily-report.py, daily-fill-and-enroll.py, the fulfillers,
-- sequence-runner.py, imap-poll.py, etc.). NEVER put the service key in any docs/ page or
-- anything shipped to a browser. The public capture/unsubscribe pages keep the ANON key
-- (insert-only under RLS), which is correct.
-- ============================================================================
