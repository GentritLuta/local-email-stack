# Client Onboarding: the modular process

The goal: a new client is **config, not custom code**. Every client is assembled
from the same building blocks. You fill in one spec, the blocks run in order, and
the guardrails are identical for everyone. This is the path to a real SaaS.

There are two ways to run it:

- **Self-serve (SaaS path):** the client fills the public form in `saas/`, which
  writes an `onboarding_submissions` row. `sequences/onboard-pipeline.py` picks it
  up and provisions everything automatically.
- **Operator path:** you run the same building blocks by hand for full control
  (what we have done for aureon, diraya, energ, lk, dorian, etc.).

Both paths use the SAME blocks below. Nothing about a client should require new code.

---

## The client spec (the only thing that changes per client)

One object describes a client. In the SaaS path it is the onboarding form answers
(`onboarding_submissions.raw_answers`); in the operator path it is `profiles/<slug>.json`
plus a niche YAML. The fields that drive everything:

| Field | Drives | Example |
|---|---|---|
| `company`, `website` | profile name, brand wordmark, slug | "Mercury Scales", mercuryscales.com |
| `offer`, `proof`, `cta` | the AI sequence copy | pay-on-results client acquisition |
| `icp` | the niche / lead sourcing | self-made B2B founders, US/UK + DE |
| `sending_root` | the sending subdomains | mercuryscales.com |
| `dns_host` | how DNS gets provisioned | hostinger / cloudflare / netlify / other |
| `reply_to` | where replies land | skiljodorian@gmail.com |
| `lead_source` | csv import vs auto-scrape | scrape / csv |
| brand colors (optional) | the email look | indigo accent |
| booking URL (optional) | reply-autodraft auto-booking | calendly.com/.../30min |

Everything else is shared infrastructure.

---

## The building blocks

Each is a standalone, reusable script. Same input shape for every client.

| Block | File | Input -> Output |
|---|---|---|
| Profile builder | `onboard-pipeline.py::build_profile` | spec -> `profiles/<slug>.json` (domains, personas, warmup, send window, brand) |
| Sequence writer (AI) | `onboard-pipeline.py::draft_sequence` | offer + ICP + proof -> 7-email give-first sequence (no em dashes, one ask) |
| DB push | `sequences/supabase_sync.py push` (or the targeted variant upsert) | profile + variants -> Supabase `profiles` / `variants` |
| Step wiring | `scripts/wire-sequence-steps.py <slug>` | variants -> `sequence_steps` (cadence 0,2,2,3,4,7,10) |
| Domain provisioning | `sequences/provision_subdomain.py` (routed by `dns_host`) | sending_root -> Resend domains + DNS records |
| Branded email render | `sequences/email_render.py` | brand block -> per-send HTML (wordmark, colors, legal footer, one-click unsubscribe) |
| Lead sourcing | `sequences/lead_scrape.py` + a niche YAML, or `scripts/import-prospects-csv.py` | ICP -> verified prospects |
| Published-email harvest | `scripts/diraya-site-scrape.py` (generalize per ICP) | company domains -> ~0-bounce published founder emails |
| Daily fill + enroll | `sequences/daily-fill-and-enroll.py` (one `PROFILE_CFG` entry) | pool -> enrolled runs up to the warmup cap |
| Sequence runner | `sequences/sequence-runner.py` (5-min tick) | due runs -> sends, with all guardrails |
| Reply handling | `sequences/imap-poll.py` + `reply-autodraft.py` | inbound -> classify, pause, auto-draft/auto-book |
| Client deliverable | `scripts/build-client-sequence-pdf.py --profile <slug>` | profile + sequence -> branded PDF + HTML |
| Report | `scripts/daily-report.py --profile <slug> --to <client>` | sends -> daily client report email |

---

## Guardrails baked in for EVERY client (no per-client work)

These run for any profile automatically. They are why a new client is safe on day one:

- **No-solicitation compliance** (`sequences/compliance.py`): any scraped page that
  forbids marketing/outreach email (EN notices or the German Impressum anti-Werbung
  clause) is skipped at scrape time; a flagged prospect is also blocked at send time
  by `safeguards.check_no_solicitation`.
- **Calendar-based warmup ramp** (`profile_lib.warmup_day`): new domains ramp
  15 -> 25 -> 35 -> 50/day by real calendar age, never open cold at 50.
- **Bounce / reputation, rate, quiet-hours, dedup guards** (`sequences/safeguards.py`):
  checked on every send.
- **Recipient-local send window** 08:00-17:00 weekdays (`send_window`).
- **Cross-brand dedup** (opt-in `dedupe_cross_brand` in `PROFILE_CFG`): a brand that
  shares an audience with another never double-emails the same person.
- **SMTP/MX verification** (`sequences/lead_verify.py`): only verified prospects send.
- **One-click unsubscribe + legal/Impressum footer** on every email (`email_render.py`).

---

## Onboard a new client (the runbook)

### Automatic (SaaS path)
1. Client submits the form in `saas/` -> `onboarding_submissions` row (`status=pending`).
2. `LES-onboard-pipeline` (or `py sequences/onboard-pipeline.py once`) runs:
   profile -> AI copy -> domains -> leads -> warmup -> golive, writing live progress
   to `provisioning_status` for the dashboard.
3. The client pastes the DNS records the pipeline hands back (the one unavoidable
   manual step unless we hold their DNS token).
4. Domains verify -> operator (or the client) confirms go-live -> warmup starts.

### Operator path (full control)
```
# 1. profile + sequence from the spec
py sequences/onboard-pipeline.py once --id <submission_id>     # or hand-write profiles/<slug>.json
# 2. push copy + wire steps
py sequences/supabase_sync.py push
py scripts/wire-sequence-steps.py <slug>
# 3. provision sending domains (routed by dns_host; needs that account's token)
py sequences/provision_subdomain.py <slug>
# 4. ICP -> leads: create niches/<icp>.yaml (copy an existing one), add a PROFILE_CFG
#    entry in daily-fill-and-enroll.py, then:
py sequences/lead_scrape.py run <icp>          # or import-prospects-csv.py <slug> <file>
# 5. client deliverable
py scripts/build-client-sequence-pdf.py --profile <slug>
# 6. go live: set send_ramp.started_at + warmup.enabled, create LES-warmup-<slug>
```

### The DB row every client needs (easy to forget)
A client needs a `profiles` table row AND a `sequences` row, not just local JSON.
`supabase_sync push` writes profiles + variants; create the `sequences` row and run
`wire-sequence-steps.py` so steps link to variants. Prospect upserts fail until the
`profiles` row exists (FK).

---

## What is automatic vs needs a human

| Step | Automatic | Needs input |
|---|---|---|
| Profile + personas + warmup config | yes | sending_root |
| 7-email sequence copy | yes (AI, give-first) | offer / proof / ICP in the spec |
| Branded email HTML | yes (brand colors -> template) | brand colors (optional) |
| Sending domains created in Resend | yes | DNS records pasted (unless we hold the token) |
| Lead sourcing | yes once the niche YAML + PROFILE_CFG exist | the ICP + seed/search scope |
| Compliance, warmup, bounce, dedup guards | yes | none |
| Reply auto-draft | yes | booking URL for auto-booking (optional) |
| Client PDF/HTML deliverable | yes (`build-client-sequence-pdf.py`) | none |
| Fulfillment of any "free give" offer | NO | a fulfiller per give, or the client delivers manually |
| Go-live | gated | operator confirm |

---

## Known gaps on the road to full self-serve SaaS

1. **ICP -> niche YAML + PROFILE_CFG is still semi-manual.** `onboard-pipeline.setup_leads`
   queues sourcing but does not yet generate the niche YAML or the `PROFILE_CFG`
   entry. Next: a block that writes `niches/<slug>.yaml` (from a template + the ICP
   search scope) and appends the `PROFILE_CFG` entry, so scraping starts with zero
   hand-editing.
2. **Per-client DNS tokens.** Auto-DNS only works for zones we hold a token for.
   Self-serve clients paste records, or grant a delegated token.
3. **Fulfillment of give-first offers.** Each "reply KEYWORD for X" needs a fulfiller
   (see `scripts/fulfill-*.py`) or a manual promise. The sequence writer must only
   promise what can be delivered.
4. **Bespoke email templates** are still hand-built per brand. The default template
   already applies the brand's colors + wordmark + legal footer, which is enough for
   v1; a template generator is a later polish.
5. **Booking URLs** for reply-autodraft auto-booking must be provided per client.

Close gap 1 and the operator path collapses to: fill the spec, paste DNS, confirm
go-live. That is the SaaS.
