# SaaS Client Dashboard — Architecture & Spec (v1)

Status: **BUILT + LIVE (as of 2026-06-17).** Implemented as the client portal at
portal.aureonglobal.de — the `saas/` Vite+React app (GitHub Pages repo aureon-portal),
Supabase Auth + RLS, the `LES-onboard-pipeline` task running `onboard-pipeline.py` against
`onboarding_submissions`, and the `clients` / `onboarding_submissions` / `provisioning_status`
tables. All 5 screens below exist (Login, Onboard, Status, Dashboard, go-live) plus more that
postdate this spec: contract e-sign (Sign), billing-on-file (Billing), credential handover
(Access), continuation. This doc is kept as the original design record; the open questions in
§7 were all resolved during build (password+invite auth, billing built, guided-manual DNS
fallback, GitHub Pages hosting).
Decisions locked 2026-06-08: (1) new public web app, Supabase-backed; (2) full auto
including DNS, with fallback to manual when the DNS host is not API-reachable;
(3) spec first, build next.

## 1. The problem
Today a client onboards via a Google Apps Script form (docs/aureon-onboarding-form.gs)
that emails responses to info@aureonglobal.de. A human then manually does everything
this stack does per brand: create profile.json, push profile+sequence+variants to
Supabase, provision sending domains (Resend + DNS), source/import leads, start warmup.
Today's session did this by hand for EnerG and AlgoAlpha. The goal: a client signs up,
hands over their info, and the campaign auto-kicks-off.

## 2. What "auto-kickoff" actually means (grounded in today's reality)
The pipeline a submission must trigger, in order:
1. Create the client **profile** (profiles table + profiles/<slug>.json shape).
2. AI-draft the **sequence + variants** (7-email Hormozi) from the client's offer inputs.
   Default the step-1 hook to the proven low-friction "one-number ask" pattern
   ("a seller test for {company}" got 5.4% reply vs 0.3% for "Are you open?" - see
   out/reply-rate-analysis-2026-06-08.md). The ask = one thing only the prospect can
   answer about their own business.
3. Provision **sending domains**: create subdomains in Resend, push DKIM/SPF/MX to DNS,
   verify. THE HARD PART. DNS host varies per client:
   - Hostinger (token owns zone) -> sequences/domain_autoprovision.py path.
   - Cloudflare (token owns zone) -> scripts/_provision-algoalpha-cf.py path. NOTE the
     Resend-record-name-doubling gotcha (name is relative to ZONE ROOT, not the sending
     subdomain) - see [[algoalpha-sending-domain]] memory.
   - Host NOT API-reachable (Wix/GoDaddy, or token absent) -> FALLBACK: generate exact
     records to a file + show in dashboard for the client/operator to paste, then poll verify.
   "Full auto including DNS" = try the API path for the client's host; fall back to
   guided-manual + auto-verify-poll when no token. The app must detect the host
   (NS lookup) and route accordingly.
4. **Reset ramp/warmup to today** so brand-new domains warm from day 1 (today's AlgoAlpha
   bug: stale started_at = full-rate blast on cold domains).
5. **Leads**: either client uploads a CSV (scripts/import-prospects-csv.py path) or picks
   an ICP and we queue sourcing (the LES-lead-scrape-* / seed_discover flow).
6. **Start sending**: enable the client's warmup task + activate the profile. GATE: first
   real send waits behind an operator (or client) "go" confirmation.

## 3. Architecture
- **Frontend**: new Vite + React + react-router app (separate repo/dir, e.g. saas/), reusing
  @supabase/supabase-js. Deploy to Vercel/Netlify (or GitHub Pages for static + Supabase
  Edge Functions for the pipeline). Do NOT bolt onto desktop/frontend (that's the internal
  Tauri admin; keep client + admin separate).
- **Auth**: Supabase Auth (email magic-link or password). This is NEW - the current app uses
  an anon key in localStorage with no per-user auth. Each client = one auth user, mapped to
  one profile_slug. Row-Level Security so a client sees only their own profile/leads/replies.
- **Backend pipeline**: the auto-kickoff steps run server-side, NOT in the browser (they need
  the Resend full key + DNS tokens, which must never reach the client). Two options:
    a) Supabase Edge Functions (Deno) calling Resend/Cloudflare APIs. Cleanest for a hosted SaaS.
    b) A small FastAPI/Flask service on the PC that the existing LES-* scheduler world lives in,
       triggered by a new row in an `onboarding_submissions` table (polled by a LES-onboard task).
  Recommendation: (b) for v1 - reuses all existing Python provisioning code (domain_autoprovision,
  _provision-*-cf, wire-sequence-steps, profile_lib) instead of porting to Deno. A new
  `LES-onboard-pipeline` task watches `onboarding_submissions(status=pending)` and runs the steps,
  writing progress back to a `provisioning_status` the dashboard polls.
- **Secrets stay server-side**: Resend keys, Hostinger/CF tokens live in sequences/hostinger.env
  on the PC, never in the web app. The web app only writes the submission row; the PC pipeline
  does the privileged work.

## 4. New data model (Supabase tables to add)
- `clients` (id, auth_user_id, profile_slug, company, contact_name, contact_position, contact_email, status, created_at)
  - `contact_position` and `contact_email` are always captured from the onboarding form's
    required first question (see screen 5.2); kept as first-class columns so every invited
    client has them queryable, not only inside `onboarding_submissions.raw_answers`.
- `onboarding_submissions` (id, client_id, raw_answers jsonb, status[pending|provisioning|
  needs_dns|ready|live|error], created_at) - the pipeline's work queue.
- `provisioning_status` (client_id, step, state, detail, updated_at) - per-step progress for
  the dashboard's live status view (domain 4/12 verified, etc.).
- RLS policies: client reads own rows; the PC pipeline uses the service key.

## 5. Client dashboard screens (v1)
1. **Sign up / log in** (Supabase Auth).
2. **Onboarding form** - the questions from aureon-onboarding-form.gs, restructured: primary
   contact (name, **position/role**, and **work email**) - REQUIRED and always asked, the first
   question after invite, since it identifies who we're dealing with and where replies go;
   company, offer, ICP, sending-domain (+ where its DNS is hosted), lead source (CSV upload or
   ICP pick), reply-to mailbox. Submitting writes `onboarding_submissions` and back-fills the
   `clients` contact fields below.
3. **Provisioning status** - live view of the pipeline (profile created, copy drafted, domains
   verifying X/N, leads loaded). If a domain needs manual DNS, show the exact records + a
   "re-check" button.
4. **Campaign dashboard** - once live: sends/day, delivered%, reply%, the actual replies
   (from the replies table, RLS-scoped), warmup ramp position. Mirror the internal Analytics
   route but client-scoped.
5. **Go-live gate** - a button the client (or operator) clicks to start real sends after warmup
   prep, honoring the "pause before first real send" rule.

## 6. Reuse map (existing code the pipeline calls)
- profile_lib.load_profile / save_profile / iter_send_domains / daily_target_for_domain
- domain_autoprovision.py (Hostinger), scripts/_provision-algoalpha-cf.py (Cloudflare)
- scripts/wire-sequence-steps.py, the energ-style DB push (scripts/_push-energ-db.py pattern)
- scripts/import-prospects-csv.py (lead upload), seed_discover/lead_scrape (ICP sourcing)
- warmup-scheduler.py (warmup task), sequence-runner.py (sending)

## 7. Open questions for build session
- Auth: magic-link vs password? Self-serve signup or invite-only (you approve each client)?
- Billing: out of scope for v1, or stub a Stripe checkout before campaign goes live?
- DNS auto for arbitrary clients: we only have tokens for OUR Hostinger + the tryalgoalpha
  Cloudflare. For a real external client we'd need THEIR token or guided-manual. v1 likely
  = guided-manual DNS for external clients, full-auto only where we hold the token.
- Hosting: Vercel (easy) vs self-host next to the PC pipeline?

## 8. Suggested build order (next session)
1. Supabase: add tables + RLS + Auth. 2. Scaffold the public Vite app + auth. 3. Onboarding
form -> writes submission. 4. LES-onboard-pipeline (Python) consuming submissions, reusing
the provisioning scripts. 5. Provisioning-status + campaign dashboard screens. 6. Go-live gate.
Ship the form->profile->copy slice first (proves the loop); domain auto + dashboards next.
