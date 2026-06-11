# Diraya cold-email campaign — build status & resume notes

_Last updated: 2026-06-02 (todos session)_

## Goal
Stand up a Diraya Inc. cold-outbound campaign. Sending from Spaceship-registered
domains; all in-email links + CTA land on the live brand site **diraya.ca**
(note: "deraya.ca" in the original to-do was a typo — deraya.ca does not resolve;
diraya.ca is the live site).

## ✅ DONE & VERIFIED (content/config side)
- **Profile** `profiles/diraya.json` rebuilt to 5 roots × 12 subdomains = **60
  sending identities**, 60 distinct team personas, Aureon-style rotation/warmup/
  caps, recipient-local Mon–Fri 08:00–17:00. `active: false` (not sending).
  Old profile backed up at `profiles/diraya.json.bak-20260602`.
  - Generator: `out/_gen_diraya_profile.py` (re-run to regenerate; edit DOMAINS/
    SUBLABELS/NAMES there to change the footprint).
- **7-email copy** in `sequences/diraya-default/variants.json` — verbatim match to
  the PDFs (`Desktop/Aureon-Live/Contracts/Diraya/Diraya-Email-Step-1..7.pdf`).
  Days 0/2/4/7/11/18/28. Lead magnets REVIEW + GHOSTS.
- **Template** `sequences/email_template_diraya.py` matches live diraya.ca
  (orange #FF6B00, Kanit, founder voice). Edited so the CTA button →
  `brand.cta_url` (Calendly `calendly.com/amoura-ma-diraya/30min`); wordmark/
  footer stay on diraya.ca.
- **Rendered + proven**: all 7 steps render; steps 2–5 show the Calendly button,
  steps 1/6/7 are reply-only. Output in `out/diraya-render-test/`.

## Footprint decision (2026-06-02)
Settled on **5 Spaceship domains × 2 subdomains = 10 senders** (hello.+team. on
each). Profile regenerated to 10. (Was 60; 60 fights the Resend cap + DNS reality
and exceeds what the client asked for.)

## ✅ RESOLVED 2026-06-02 (later in session): NEW Resend account
- The stack was using the WRONG Resend account (old, capped). The valid account
  is the **g-luta** one. New Full-Access key stored as `RESEND_NEW_ACCOUNT_API_KEY`
  in `sequences/hostinger.env` (old key left in place; live aureon untouched).
- New account has **NO domain cap** — created **all 10 Diraya domains** on it
  successfully (ids in `profiles/diraya.json`). DNS records (DKIM+SPF+MX, 6 per
  root = 30 total) exported to `out/diraya-dns-export/*.txt` + `_all_records.json`.
- **Resend is no longer a blocker.** Only DNS publishing remains.

## ✅ DONE 2026-06-03 (PC-crash recovery session): DNS PUBLISHED
- **All 5 roots are now on Spaceship** (cleardiraya.com, dirayaget.com, diraya.biz,
  diraya-agency.shop, diraya-marketing.shop) — the ClouDNS split no longer applies.
- **Spaceship API key created + saved**: `SPACESHIP_API_KEY` + `SPACESHIP_API_SECRET`
  in `sequences/hostinger.env` (key name "diraya-dns-les", Full access). Verified
  working. NOTE: Spaceship API sits behind Cloudflare → requests MUST send a browser
  User-Agent or you get `403 error 1010`.
- **All 30 Resend records published ADDITIVELY** via `out/_publish_diraya_dns.py`
  (PUT /dns/records is additive — confirmed by test; existing records preserved, so
  diraya.biz's live Webflow site + Google email are intact: 12→18 records).
- **Resend verification triggered** on all 10 senders → status `not_started`→`pending`
  (DNS propagating; SES checks DKIM; flips to `verified` within ~minutes-1h).

## ⏭️ REMAINING to go live (was blocked, now unblocked)
1. **Wait for verify**: re-poll status (RESEND_NEW_ACCOUNT_API_KEY + UA header) until
   the 10 domains read `verified`. (script: list /domains, filter diraya.)
2. **DB-wire** (none exists yet — `sequences?slug=eq.diraya-default` = []):
   create the `sequences` row (profile_slug=diraya, active=true) + push the 7
   `variants` rows from `sequences/diraya-default/variants.json`, THEN
   `scripts/wire-sequence-steps.py diraya`.
3. **Leads**: scrape/import the ICP (seed–Series B SaaS/healthtech/fintech) + enroll.
4. **Activate**: profiles/diraya.json `active: true` + push to DB profiles.
5. **Warmup**: add `LES-warmup-diraya` scheduled task, day-0 = 0 sends.

## ❌ (historical) old-account blocker — superseded by new account above
1. **Resend plan caps CONCURRENT UNVERIFIED domains (effectively 1).** Tested
   definitively: deleted 10 failed domains (37→27), then tried to add 10 Diraya
   domains — only **1** was created, then every further add returned
   `403 "Your plan includes 1 domain. Upgrade to add more."`. Account status was
   `verified:24, pending:3, not_started:1`. **Verified domains do NOT count; the
   plan blocks adding new domains while unverified ones exist.** So new sending
   domains can only be stood up **one at a time: add → publish DNS → verify (frees
   the slot) → add next** — OR upgrade the Resend plan to lift the unverified cap.
   Batch-creating 10 (or 60) is impossible on the current plan.
   - This is circular with blocker #2: verifying needs DNS published, which needs
     DNS API access we don't have. So today neither can complete autonomously.
   - Also note: 3 `pending` domains already sat on the account before this work;
     clearing/verifying those would help free the add-path.
2. **No DNS API access to the 5 roots.** cleardiraya.com + dirayaget.com → ClouDNS;
   diraya-agency.shop + diraya.biz + diraya-marketing.shop → Spaceship. No API token
   for either on this machine. Cloudflare token can't create zones (403). Hostinger
   owns none of them. → DNS records can't be auto-published until a token exists OR
   NS are migrated to a provider we have API access to (Hostinger).

## NEXT STEPS to go live (in order)
1. **Decide footprint** (operator leaning ~10 domains — good fit for plan headroom).
   Likely better: ship on **diraya.ca** root with N subdomains (matches the client's
   onboarding "send under diraya.ca" + the PDF's single-domain ~500/day plan).
2. **Resend room**: upgrade plan, or free slots (delete 10 `failed`; drop unused
   atalsolidrocks.io 12 if that brand isn't sending).
3. **Provision**: `out/_provision_diraya_60.py` creates Resend domains + exports DNS
   per root to `out/diraya-dns-export/`. (Idempotent; edit the profile's domain list
   first to match the chosen footprint.)
4. **DNS**: publish exported records at the registrar (need ClouDNS/Spaceship token,
   or migrate NS to Hostinger), then `provision_subdomain.py verify diraya <sub>`.
5. **Wire + enroll**: push variants (`scripts/wire-sequence-steps.py`), set
   `active: true`, add `LES-warmup-diraya` scheduled task, day-0 warmup = 0 sends.

## Key facts
- Resend full-access key: `RESEND_FULL_ACCESS_API_KEY` in `sequences/hostinger.env` (works).
- Calendly: `https://calendly.com/amoura-ma-diraya/30min`. Notices/replies: `info@diraya.ca`.
- Diraya Inc, reg# 1603166-8, Canada, 500 Sedgebrook Way, founder Mohammed El Amine Amoura.
- ICP: seed–Series B SaaS/healthtech/fintech needing AI engineering.
