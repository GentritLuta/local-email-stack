# Free motivated-seller lead engine — architecture + build plan

Grounded in the deep research (2026-06-22, 106-agent harness, adversarially verified).
Built on the existing `scripts/source-seller-leads.py` (already does the assessor +
Craigslist FSBO layers), the home-value funnel, and the seller-outreach pipeline.

---

## 0. The core insight (what the research proved)

The paid tools (BatchData, PropStream, REISkip, PropertyRadar, ...) have **one moat,
and it is not the property data.** Their moat is the **contact append** — turning an
owner + address into a working phone/email. Everything else is free and public:

| Layer | Free + replicable? | Notes |
|---|---|---|
| Property + owner records | YES | county assessor ArcGIS REST, no token |
| Motivation signals (absentee, pre-foreclosure, probate, FSBO, tax-delinquent) | YES | public records + court dockets + FSBO web |
| **Contact append (phone/email)** | **NO — the paid floor** | broker data (credit headers/telco), 60-75% hit even paid, GLBA/DPPA gated |
| Outreach channel | YES | cold email is legal (CAN-SPAM opt-out); mail needs no contact at all |

**So we match the paid tools on the LIST for free, and beat them on COST + COMPLIANCE
by reaching owners via direct mail (the mailing address is free from the assessor — no
skip-trace) and lawful cold email — instead of the TCPA-risky cold-calling they push.**
The only thing we cannot get free at volume is a phone number, and phone is the weakest
compliance channel anyway.

---

## 1. Architecture

```
  DISCOVERY (free)            SCORING (free)        CONTACT (tiered)        OUTREACH (legal)
  ┌─────────────────┐       ┌──────────────┐      ┌──────────────────┐    ┌───────────────┐
  │ assessor ArcGIS │──┐    │ stack signals│      │ T1 mailing addr  │──> │ direct mail   │
  │ clerk/recorder  │  │    │ -> intent    │      │    (FREE, assessr)│    │ (no TCPA)     │
  │ state courts    │  ├──> │ score per    │ ───> │ T2 free email    │──> │ cold email    │
  │ FSBO web        │  │    │ owner+addr   │      │    (people-search)│    │ (CAN-SPAM)    │
  │ tax-delinquent  │──┘    └──────────────┘      │ T3 paid phone    │──> │ call (DNC)    │
  └─────────────────┘                             │    (cents/rec)    │    └───────────────┘
                                                  └──────────────────┘
```

Aureon runs all of it. The agent gets a booked appointment / a handed lead and provides
nothing. (Reconciles with the earlier seller-appointment engine design: this is its
DISCOVERY + CONTACT layer; the funnel is the consented inbound complement.)

---

## 2. Layer 1 — the free motivated-seller LIST (data sources)

For each: what it yields, whether it is free, how to pull it programmatically, and the
motivation signal it carries. **Existing code to extend: `scripts/source-seller-leads.py`.**

### 2a. County assessor / parcel (the spine — already partly built)
- **Yields:** owner name, property (situs) address, **mailing address**, land use, value.
- **Free:** YES. Most counties expose **ArcGIS REST FeatureServer/MapServer** endpoints,
  no token. SQL-92 `WHERE` filters + `resultOffset`/`resultRecordCount` paging (loop on
  `exceededTransferLimit`, ~1000 records/page cap). Source: Esri REST reference; live at
  `gis.mcassessor.maricopa.gov/.../Parcels/MapServer`.
- **Signal:** **absentee owner** = `WHERE situs <> mailing` (the #1 free, derivable signal).
  Out-of-state owner = mailing state ≠ property state.
- **Build:** `source-seller-leads.py` `_county_assessor` already discovers + queries these.
  Extend: persist the full owner+mailing for the direct-mail channel; add the absentee
  filter as a first-class signal; widen the county→layer discovery (`_discover_county_layer`).

### 2b. County clerk / recorder (pre-foreclosure + tax-delinquent)
- **Yields:** lis pendens (pre-foreclosure notice), tax-delinquent rolls, deeds.
- **Free:** YES / cheap. Lis pendens is statutorily public, nominally recorded (e.g. Pasco
  County FL lists judicial sales free at `pasco.realforeclose.com`). Many counties run a
  Realauction / e-recording search portal.
- **Signal:** **pre-foreclosure** (highest-intent distress) + **tax-delinquent**.
- **Build:** NEW per-county scraper (`scripts/source-foreclosure.py`). Jurisdiction-specific
  (Realauction, county recorder e-search). Start with the agent metros' counties.

### 2c. State / county courts (probate, divorce, eviction)
- **Yields:** inherited property (probate), divorce-driven sales, landlord exits (eviction).
- **Free:** YES but jurisdiction-specific. **RECAP/CourtListener is FEDERAL-only and misses
  all of this** (probate/divorce/foreclosure/eviction are state matters). Must scrape each
  state/county court docket portal directly.
- **Signal:** **probate / inherited** + **divorce** + **tired-landlord**.
- **Build:** NEW per-jurisdiction docket scraper. Highest effort, highest-intent leads.
  Phase 2 (start with one state's probate portal as a proof).

### 2d. FSBO web (already built — expand)
- **Yields:** owners actively selling themselves (invited-solicitation, defensible to contact).
- **Free:** YES. Craigslist done in `_craigslist_fsbo`. Expand to **FSBO.com,
  ForSaleByOwner.com, Zillow FSBO, Facebook Marketplace** (the last two are anti-bot —
  harder). FSBO often the only segment with a directly-posted phone (still sparse).
- **Signal:** **active FSBO** (already trying to sell).
- **Build:** add providers to `source-seller-leads.py` (mirror `_craigslist_fsbo`).

---

## 3. Layer 2 — motivation scoring (free)

Each owner+address gets a stacked score. Most signals are free-derivable; high-equity is
the gap (needs mortgage/lien data, not always in free GIS).

| Signal | Free? | Source |
|---|---|---|
| Absentee / out-of-state owner | YES | assessor (situs ≠ mailing) |
| Active FSBO | YES | FSBO scrape |
| Pre-foreclosure (lis pendens) | YES | clerk/recorder |
| Tax-delinquent | YES | clerk tax rolls |
| Probate / inherited | YES (jurisdiction-specific) | court dockets |
| Divorce | YES (jurisdiction-specific) | court dockets |
| Tired landlord (eviction) | YES | court dockets |
| High equity | PARTIAL | needs mortgage/lien from recorder (not always free) |
| USPS-confirmed vacancy | NO (largely gated) | skip or infer |

**Stacking 2+ signals beats any single paid list** (e.g. absentee + tax-delinquent + out-of-
state = very high intent). Score = weighted sum; surface the top N per zip.

---

## 4. Layer 3 — the contact append (the floor, three honest tiers)

| Tier | Channel it unlocks | Free? | Coverage | Compliance |
|---|---|---|---|---|
| **T1 — mailing address** | direct mail | **FREE** (assessor) | ~100% (every parcel has one) | none (mail is unregulated) |
| **T2 — free people-search email** | cold email | free-ish | **UNKNOWN — must test** | ToS/anti-scrape risk |
| **T3 — paid aggregator phone/email** | call/text/email | cents/record | 60-75% valid even paid | DNC scrub (phone) |

- **T1 is the unlock:** the assessor gives the mailing address for free, so **direct mail
  needs no skip-trace at all.** This is the genuinely-better-than-paid free route for the
  highest-intent segments (probate, pre-foreclosure, absentee).
- **T2 is the open question** the research flagged: can free people-search (TruePeopleSearch /
  FastPeopleSearch) append an email at volume? Coverage + ToS unverified. **Test before
  relying on it** (a real probe on 50 owners).
- **T3 is the unavoidable paid floor** for phone at volume: a consumer-grade aggregator
  (BatchData-class, NOT GLBA-gated TLO/Accurint which is illegal for marketing). Only buy
  this if phone is genuinely needed; cents/record.

---

## 5. Layer 4 — outreach + compliance (what is actually legal)

- **Direct mail (T1):** unregulated. Best channel for the free engine. Send a clean letter
  to the owner's mailing address. No contact data, no TCPA, no consent needed.
- **Cold email (T2/T3):** **legal without opt-in under CAN-SPAM** — requires truthful
  headers, non-deceptive subject, ad disclosure, valid physical postal address, working
  unsubscribe honored within 10 business days. Exposure ~$53k PER violating email, so
  compliance is non-negotiable but the channel is open. (Already how the stack sends.)
- **Cold call/text (T3 phone):** TCPA — **$500-$1,500 per violation.** Must scrub National +
  ~11 state + internal DNC lists, re-scrub every 31 days; A2P 10DLC registration for texts;
  honor STOP/HELP. Do NOT rely on the refuted "investors are DNC-exempt" theory — treat as
  telemarketing. Recommend: avoid cold phone; if used, scrub rigorously.
- **Skip-trace data law:** premium broker data (TLO/Accurint) is GLBA/DPPA-gated to
  non-marketing uses — **illegal for cold sales.** Only consumer aggregators (outside that
  licensing) are usable; another reason mail + email beat phone.

---

## 6. Build plan (phased, on the existing stack)

**Phase 1 — the free list, productionized (reuse `source-seller-leads.py`):**
1. Extend the assessor layer: persist owner + mailing address; add the absentee/out-of-state
   filter as a scored signal; widen county→ArcGIS-layer auto-discovery.
2. Expand FSBO providers (FSBO.com, ForSaleByOwner; Zillow/FB later).
3. Output a scored, deduped motivated-seller list per zip/metro to a `seller_leads` store.

**Phase 2 — distress + court layers (new scrapers):**
4. `source-foreclosure.py` — lis pendens + tax-delinquent per county (start: agent metros).
5. `source-probate.py` — one state's probate docket as a proof, then widen.

**Phase 3 — the contact + channel:**
6. **Direct-mail pipeline** (T1): generate a print-ready mailer per lead from the free
   mailing address; export to a mail-merge / postcard service. Highest-intent first.
7. **Test T2** (free email append): probe TruePeopleSearch-class coverage on 50 real owners;
   keep only if coverage + ToS are acceptable. If yes, wire email (CAN-SPAM) outreach.
8. (Optional) T3 paid phone — only if phone volume is needed, with DNC scrubbing.

**Phase 4 — close the loop:** route responders into the existing seller-outreach + the
home-value funnel + the appointment engine (the agent gets a booked meeting / a handed lead).

---

## 7. Honest floor + what to test + realistic output

- **The hard floor:** a working PHONE at volume requires paid data (cents/record). Mailing
  address (free) + email (free people-search, unproven) are the free routes.
- **Biggest unknown to TEST first:** free people-search email-append coverage/accuracy/ToS.
  It is the single biggest free lever; prove or kill it before building the email path.
- **Realistic free output is unproven per metro** (the research left this open). Expect:
  FSBO = a handful per metro; assessor absentee + court distress = larger but mail-only
  (no contact append). Volume comes from mail to the free list, not phone.
- **Where paying a little is genuinely unavoidable:** phone-contactable volume. Everything
  else — the list, the signals, direct mail, legal email — is free and beats the paid tools
  on cost and compliance.

### Refuted / do-not-rely-on (from verification)
- The "Jan 27 2025 one-to-one TCPA consent" rule — vacated/delayed; do not assume it.
- "Real-estate investors are DNC-exempt" — self-serving vendor theory, not law.
- Specific skip-trace per-record prices ($0.12-0.18) — unverified; cost floor is uncertain.

### Key sources
Esri REST reference; Maricopa County Assessor GIS; Pasco County Clerk (foreclosures);
Free Law Project / CourtListener (RECAP federal-only); TransUnion TLO terms (GLBA/DPPA);
FTC CAN-SPAM compliance guide; BatchData (60-75% contact rate, self-reported volume).
