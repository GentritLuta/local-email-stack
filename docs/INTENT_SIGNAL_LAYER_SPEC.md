# Intent-Signal Enrichment Layer — Specification

Status: planned. This document is both (a) a section to fold into `AUREON_ARCHITECTURE.md`
and (b) the build blueprint for the engine.

## 1. Purpose

Add a standardized, per-client layer that detects research-based **intent signals** for each
prospect (for real estate: divorce, probate, pre-foreclosure, tax lien, etc.) from legitimate
public sources, scores them, and writes the result into the existing intent layer
(`migration_004_lead_intent`). Reaching a prospect at the moment a life or business event has
already made them a seller/buyer is the single highest-leverage point in outreach.

**Primary business focus: B2C consumer acquisition for business clients.** The product helps the
client win consumer customers, so the signals identify in-market CONSUMERS. This makes the channel
decision the make-or-break, because consumer cold email is illegal in the EU (opt-in required) and
deliverability-poison in the US. Therefore the engine's output does NOT feed a consumer cold-email
queue. It feeds legal consumer channels: opt-in funnels / lead magnets (the existing
`build-home-value-funnel.py` model), paid-ad audience targeting and lookalikes, local SEO / Google
Business presence, direct mail or call for real-estate distressed sellers, and prioritization of the
client's own opted-in lists. Cold email remains the B2B tool for signing business clients only.

The hard requirement: the AI must never freelance. Quality must be identical for every prospect.
We achieve this with **config-driven, deterministic instructions plus constrained structured
output** — the AI only ever fills a fixed schema, it never decides what to look for.

## 1a. Objective: seller appointments for agent-clients

The concrete deliverable. The B2B layer cold-emails real-estate AGENTS to sign them as clients (what
the cold-email stack already does). For each signed agent, the B2C layer must produce booked SELLER
APPOINTMENTS in that agent's local area, the listings that are the agent's lifeblood.

End-to-end seller-appointment flow (legal, consent-gated):

```
likely-seller signals (per agent's metro)
  public records: pre-foreclosure, probate, divorce, absentee, high-equity, expired listings
  social listening: public "thinking of selling" posts
       │
       ▼
targeting: geo + lookalike ad audiences (Meta/Google)  +  direct mail to likely-seller lists
       │
       ▼
home-value OPT-IN funnel (build-home-value-funnel.py)  ──►  consent captured
       │
       ▼
nurture sequence (email/SMS, lawful because opted in)
       │
       ▼
booked seller appointment on agent calendar (seller-outreach.py / meeting-followup.py / Calendly)
       │
       ▼
agent runs the listing appointment
```

The homeowner is emailed only after opting into the funnel. Cold signals drive targeting and the
funnel; they never cold-email the homeowner. Per-agent geo scoping uses the existing
`referral-lists/metros/` and geo-backfill tools. Much of this machine already exists (home-value
funnel, `seller-outreach.py`, meeting-followup/Calendly, sequence engine, per-metro lists); the
intent-signal layer is the front-end that feeds qualified likely-sellers into it per agent.

## 2. Placement in the stack

Additive, not a rebuild. It plugs into existing components:

```
niches/*.yaml ──► signal pack (new) ──► intent orchestrator (new) ──► Serper (search.env)
                                                │
                                                ▼
                                   lead_intent table (migration_004)
                                                │
                                                ▼
                               sequence-runner / copy angle selection
```

- Input: prospects already in the pool (enriched with owner name, address, county, company).
- Search backend: Serper via `search.env` (and `research-dispatcher.py` patterns).
- Output sink: `lead_intent` rows + an evidence bundle per prospect.
- Consumer: the sequence engine uses the intent score to gate send/timing and pick the copy angle.

## 3. Design principles

1. **Config defines, code executes, AI fills.** Signals live in YAML. The orchestrator expands
   each signal into a fixed instruction. The AI returns a rigid JSON schema only.
2. **Jurisdiction-aware by construction.** Each pack declares a `jurisdiction`. The engine refuses
   to run a US-distress pack against an EU client and vice versa.
3. **Evidence-required.** A signal only counts as "found" if the AI returns a concrete source URL +
   snippet + date meeting the pack's `evidence_criteria`. No evidence, no hit. This kills
   hallucinated intent.
4. **Source allowlist is the control point.** Only sources in `public_sources[]` are searched.
   Clean list in, clean pipeline out.
5. **Deterministic scoring.** Score = weighted sum of confirmed signals, decayed by recency. Same
   inputs always yield the same score.

## 3a. Source strategy: where social media fits

Social media is the richest, freshest source for many signals, and the stack already runs
public-social sourcing (`docker/sourcing/engines/`: twitter, instagram, tiktok, youtube, reddit,
linkedin_via_google, bluesky, farcaster, producthunt, github; plus `social_scrape.py`,
`youtube_scraper.py`, `tradingview_scrape.py`). The rule is **match the source to the signal type**.

**Social as a PRIMARY source (public, intended-to-be-seen, legitimate):**
- B2B / company intent: hiring, funding, expansion, launches, leadership changes.
- Creator / influencer intent (crypto, YouTube, TradingView clients): public follower counts,
  posting cadence, engagement, topic focus. Already core to the stack and fully defensible.

**Social NOT primary (individual life-event distress, e.g. real estate):**
- Divorce, death/probate, foreclosure on a named individual: the authoritative AND legal source is
  PUBLIC RECORDS (county courts, recorders, tax rolls, PACER). Social detection of these on
  individuals is a four-way problem: most platforms (Meta, LinkedIn, X, TikTok) ban scraping in ToS;
  it is GDPR-unlawful on EU individuals; profile-to-owner matching is noisy and harmful when wrong;
  and any hint in outreach that a feed was watched gets reported and destroys sender reputation.
  For the distress pack, public records stay primary and social is corroboration-only, ToS-clean
  access only, and never used on EU individuals.

**Social listening for public buying-intent (PRIMARY for B2C, clean, highest-converting):** the
strongest social signal is not detected misfortune but VOLUNTARY public solicitation, people who post
in public asking for exactly what the client sells: "recommend a realtor", "relocating, need to sell
fast", "just inherited a house, what now", "AC died, who do I call". They are pre-qualified,
in-market, and want contact because they raised their hand publicly. This is the focus for B2C
social. The line:

- Voluntary public solicitation a person broadcast seeking help = fair game (build it). A life event
  qualifies when they posted it AS a request ("just inherited a property, looking for an agent").
- Involuntary private misfortune they did NOT broadcast as a request (digging a divorce or foreclosure
  out of their feed) = out of scope, because it is GDPR-illegal for EU clients, ad platforms ban
  sensitive-category targeting so it cannot be acted on there, and acting on it openly is the
  creepiness that gets the client's brand reported.

Surfaces for listening: Reddit, public X/keyword search, public groups, Nextdoor, forums, review
sites, YouTube comments, via APIs and public search.

**Access pattern:** prefer public/API/indexed access (the `linkedin_via_google` pattern of searching
the public index) over direct mass scraping that gets IP-banned and creates contract/legal exposure.
Each `public_sources[]` entry is tagged with its `access_method` (api | public_index | public_page).

## 4. Signal-pack config schema (YAML)

Lives next to `niches/` as `niches/signals/<pack>.yaml`.

```yaml
pack: us_real_estate_distress
jurisdiction: US            # engine enforces this against the client profile
channel_default: enrich     # enrich existing leads vs. source-new; per-signal override allowed
tone: |
  Respectful, helpful, never predatory. Reference the situation only obliquely.
  Lead with usefulness, not with the person's distress.
signals:
  - id: divorce
    description: Active or recent divorce filing for the property owner
    public_sources: [county_court_records, public_legal_notices]
    query_templates:
      - '"{owner_name}" divorce filing {county} county'
    evidence_criteria: A court/legal-notice page naming the owner and a divorce/dissolution case
    confidence_weight: 0.9
    recency_days: 540
    email_eligible: false      # typically worked via mail/call, not cold email
    output_schema: standard_signal_result
```

`output_schema: standard_signal_result` =
`{ found: bool, evidence_url: string, evidence_snippet: string, event_date: string|null, confidence: 0-1 }`

## 5. Orchestrator flow (Python)

`sequences/intent_signals.py` (new):

1. Load the prospect and resolve the client's pack via the client profile's `jurisdiction` + niche.
2. For each signal in the pack, render `query_templates` with prospect fields
   (`{owner_name}`, `{address}`, `{county}`, `{company}`).
3. Build the fixed instruction: "Search only these sources, with this query, return ONLY this JSON."
4. Dispatch to Serper / the research dispatcher; capture structured results.
5. Validate evidence against `evidence_criteria`; discard hits with no qualifying source.
6. Score: `intent_score = Σ (confidence_weight * confidence * recency_decay(event_date, recency_days))`.
7. Upsert into `lead_intent`: score, top signal, full evidence bundle (JSON), `email_eligible` flag.
8. Never auto-send on a non-`email_eligible` signal; route those to a separate channel/flag.

The build step will read `migration_004_lead_intent.sql` and align to the real columns, adding a
migration only if an `evidence` JSONB column or `signal_pack` column is missing.

## 6. US real-estate distress pack (first instance)

Priority vertical (confirmed). This is the first pack built.

| Signal | Public source | Weight | Recency | B2C channel |
|---|---|---|---|---|
| Divorce filing | County court / legal notices | 0.9 | 18 mo | direct_mail |
| Probate / inherited | Probate court, obituary↔ownership | 0.85 | 24 mo | direct_mail |
| Pre-foreclosure / NOD / lis pendens | County recorder | 0.95 | 12 mo | direct_mail |
| Tax lien / delinquency | County tax rolls | 0.7 | 24 mo | direct_mail |
| Sheriff / auction notice | Public legal notices | 0.95 | 6 mo | direct_mail |
| Code violations | Municipal records | 0.5 | 18 mo | direct_mail / ad_audience |
| Absentee / vacant | Mailing≠property addr, USPS vacancy | 0.55 | n/a | direct_mail |
| Expired / withdrawn listing | MLS-adjacent | 0.6 | 6 mo | direct_mail / optin_funnel |
| Eviction filings (tired landlord) | County court | 0.6 | 18 mo | direct_mail |
| Bankruptcy | PACER | 0.75 | 24 mo | direct_mail |

Channel routing: distress signals route primarily to legal direct mail, the established channel for
distressed-seller outreach. The existing home-value opt-in funnel (`build-home-value-funnel.py`) and
geo/lookalike ad audiences capture the broader in-market seller pool with consent. No distress signal
ever routes to consumer cold email. The agent client receives a prioritized, evidence-backed list per
signal with the recommended channel attached.

### 6a. Public-intent listening signals (real estate)

Complementing the public-records distress signals, the social-listening engine surfaces VOLUNTARY
public posts that solicit the service. These are highest-intent and the person wants contact.

| Signal (public post) | Surface | Weight | Channel |
|---|---|---|---|
| "Recommend a realtor / agent" | Reddit, Nextdoor, public groups, X | 0.9 | reply / DM where permitted, then optin_funnel |
| "Relocating, need to sell" | Reddit, X, forums | 0.85 | optin_funnel / agent follow-up |
| "Just inherited a house, what now" | Reddit, forums | 0.8 | optin_funnel |
| "Thinking of downsizing / selling" | public groups, X | 0.7 | optin_funnel / ad_audience |
| "FSBO frustration / can't sell" | Reddit, groups | 0.7 | agent follow-up |

These are voluntary public solicitations, so engaging them is clean and welcome. The engine returns
the post URL as evidence and the recommended response channel. It never fabricates intent: no
qualifying public post, no signal.

## 7. EU GDPR-safe B2B pack (second instance)

For German/Swiss/EU clients (ENER-G, f2, etc.), individual life-event signals are off-limits under
GDPR. The same engine runs a company-level pack instead:

| Signal | Public source | Weight |
|---|---|---|
| Hiring / open roles | Company careers page, public job boards | 0.7 |
| Funding / investment | Press, public registers | 0.8 |
| Expansion / new location | News, company site | 0.7 |
| Tech-stack change | Public site/tech fingerprint | 0.5 |
| Leadership change | Press, company site | 0.6 |
| Public reviews / complaints | Public review platforms | 0.5 |

All company-level, all public, no special-category personal data, lawful basis = legitimate
interest for B2B. Jurisdiction tag `EU` blocks any distress-signal pack from running on these clients.

## 8. Hard guardrails (enforced in code)

1. **Jurisdiction gate.** Pack `jurisdiction` must match the client profile; mismatch raises and aborts.
   US-distress packs never run on EU clients.
2. **Source allowlist + social ToS rule.** Only `public_sources[]` are queried, each tagged with an
   `access_method`. No behind-login scraping, no ToS-violating mass scraping of social platforms, no
   illegal brokers. Social is primary only for B2B/creator signals; for individual distress signals
   public records are primary, social is corroboration-only, and social is never used on EU
   individuals.
3. **Fair Housing / protected classes.** Signals may key on events and financial status only. The
   engine rejects any signal defined on a protected class (race, religion, sex, disability,
   familial status, national origin) and avoids age/health.
4. **Humane tone.** Each pack carries a mandatory `tone` block injected into copy generation. Distress
   is never weaponized in the message — both an ethics rule and a deliverability one (complaint
   reports torch sender reputation).
5. **Channel/consent fit.** `email_eligible` per signal. Non-eligible signals route to a separate
   channel/flag and are never cold-emailed to an individual without a lawful basis.
6. **No consumer cold email.** For B2C signals the engine NEVER emits a cold-email-to-consumer action.
   Each signal carries a `channel` routing: `optin_funnel`, `ad_audience`, `local_seo`, `direct_mail`,
   or `prioritize_existing`. Consumer email is permitted only to addresses with a recorded opt-in.
   Cold email is reserved for B2B prospecting to businesses.

## 9. Module layout

```
niches/signals/us_real_estate_distress.yaml   # signal pack (US)
niches/signals/eu_b2b.yaml                     # signal pack (EU)
sequences/intent_signals.py                    # orchestrator
sequences/signal_pack_lib.py                   # config loader + schema validation + jurisdiction gate
sequences/intent_score.py                      # deterministic scoring + recency decay
(supabase/migration_009_intent_evidence.sql)   # only if lead_intent lacks evidence/signal_pack cols
```

## 10. Build plan

1. Read `migration_004_lead_intent.sql` to align to the real schema.
2. `signal_pack_lib.py`: load + validate packs, enforce jurisdiction + protected-class + allowlist rules.
3. `intent_signals.py`: orchestrate per-prospect, dispatch to Serper, validate evidence.
4. `intent_score.py`: deterministic weighted+decayed score.
5. Author `us_real_estate_distress.yaml` and `eu_b2b.yaml`.
6. Wire intent score into `sequence-runner` gating + copy-angle selection.
7. Migration 009 only if needed for evidence/signal_pack columns.
8. Dry-run on a sample of existing prospects; verify evidence is real and scores are stable.
