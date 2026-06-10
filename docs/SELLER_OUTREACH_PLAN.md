# Seller-Outreach Follow-Through — Plan

**What this is:** NOT a separate service or brand. It is the *follow-through layer*
on the existing cold campaigns (Aureon first). When a prospect replies to a cold
email — a realtor sends their zip after the "free seller test" offer, or replies
LIST — the seller-outreach layer **delivers the promised value, then converts the
warm reply into a booked + sold call**, as its own measured, rate-limited stage.

It sits between two things that already exist:
- The cold sequence (variants.json) that earns the reply.
- The fulfillers (`fulfill-referral-requests.py`, `pull-referral-list.py`) that already
  serve the LIST/PROBATE attorney lists.
- The responder I built (`seller-outreach.py`) that drafts a personalized reply to Calendly.

The gap this plan closes: those pieces are ad-hoc. Seller-outreach becomes a defined
stage with **its own lead magnet, its own ICP filter, its own KPIs, and its own daily
limit**, tracked end to end.

---

## 1. The lead magnet (the give that earns the call)

The cold email already promised free seller leads / a test. The follow-through magnet
has to be MORE concrete than the cold give, delivered fast, and lead naturally to a call.

**Proposed magnet: the "Zip Seller Snapshot."**
When a realtor replies with their zip (e.g. "46220"), within 24h they receive a free,
one-page snapshot for that zip:
- 3-5 likely-to-list seller signals in their zip (e.g. expired listings, high-equity
  long-tenure owners, pre-foreclosure/probate counts — sourced from public data + the
  curated attorney/probate lists we already build).
- A short read on listing velocity in that zip (days-on-market band, recent sold pace).
- One clear CTA: "Want the live version running into your pipeline? 15 min ->
  Calendly."

Why this magnet: it is specific to THEIR zip (high open + reply), it proves competence
(we did the work before asking for anything), and the natural next step is the call
where you pitch the Listing Engine. It reuses data we already pull (probate/estate
attorney lists per metro) so fulfillment infra is mostly built.

**Fallback magnet (no zip given / non-real-estate brand):** the existing curated
attorney/probate list for their metro (already fulfilled by
`fulfill-referral-requests.py`) + the personalized call CTA.

---

## 2. ICP filter (who qualifies for the follow-through)

Not every reply deserves the full follow-through. Seller-outreach should fire only for
a GENUINE warm prospect:
- Is a real, enrolled, non-unsubscribed prospect (already gated in seller-outreach.py).
- Replied with intent: a zip, a question, a "yes/interested", or a keyword (LIST/PROBATE).
- NOT: auto-pitch vendors, bounces, opt-outs, our own inboxes, laso.finance (already
  filtered via the SKIP + suppression logic).
- Tighter than the cold ICP: prefer agents/brokerages that gave a zip or asked about
  listings (seller-side intent), since the magnet + pitch are seller-lead focused.

---

## 3. Infrastructure (what gets built / reused)

| Piece | Status | Action |
|---|---|---|
| Reply detection + thread/persona resolution | EXISTS (imap-poll, seller-outreach.py) | reuse |
| Suppression / opt-out / not-a-prospect gates | EXISTS (seller-outreach.py) | reuse |
| Personalized follow-up draft -> Calendly -> approval queue | EXISTS (seller-outreach.py) | reuse |
| Curated attorney/probate list fulfillment | EXISTS (fulfill-referral-requests.py) | reuse for fallback magnet |
| **Zip Seller Snapshot generator** | NEW | build `scripts/build-zip-snapshot.py` (pulls zip signals + velocity, renders 1-pager PDF/HTML) |
| **Per-day limit + KPI tracking** | NEW | add to seller-outreach.py: daily cap + status funnel counts |
| **Scheduled run** | NEW (optional) | `LES-seller-outreach` every 15-30 min, after user OKs |

Status funnel stored in `prospects.custom_fields.seller_outreach`
(replied -> snapshot_sent -> drafted -> sent -> booked -> sold -> returned).

---

## 4. Targets (recommended defaults, from your real data)

Baseline from Aureon cold step-1: 64% open, 5.4% reply. Follow-through to a WARM reply
should beat cold materially. Recommended targets for the seller-outreach stage:

| Metric | Target (conservative) | Target (good) | Why |
|---|---|---|---|
| Follow-up open rate | 55% | 70% | warm + personalized + their zip in subject |
| Follow-up reply rate | 25% | 40% | they already engaged once |
| Reply -> call booked | 15% of replies | 30% | the magnet + 1 clear CTA |
| Call -> sold (your close) | your number | your number | you run the call |

These are tracked per-lead and rolled up so you see the funnel weekly (reuse the
daily-status / volume-report pattern).

---

## 5. Daily limit (own cap, warmup-safe)

Seller-outreach sends from the SAME warmed domains as the cold campaign, so its sends
must NOT blow the per-domain warmup cap. Recommended: a **separate seller-outreach daily
cap of 40/day** to start (well under Aureon's 300 cold cap), drawn from the same pool but
counted and limited independently, so:
- follow-throughs always get priority over net-new cold sends (a warm reply is worth more),
- but they can never exceed 40/day combined, protecting deliverability.
Configurable: `SELLER_OUTREACH_DAILY_CAP=40` in hostinger.env. Raise as reply volume grows.

---

## 6. Build order (phased, each shippable)

1. **Daily cap + KPI tracking** in seller-outreach.py (small, immediate).
2. **Zip Seller Snapshot generator** (`build-zip-snapshot.py`) + wire it as the magnet
   the follow-up references and attaches.
3. **Funnel rollup** in daily-status / a weekly seller-outreach report.
4. **Schedule** `LES-seller-outreach` once you approve the live drafts.
5. Generalize beyond Aureon (ENER-G "Energiekosten-Check" snapshot is the German analog)
   once ENER-G is sending.

---

## Magnet decision (2026-06-09): DONE-FOR-YOU BOOKED LISTING APPOINTMENT

The follow-through give is the full Listing Engine as a trial: when an agent replies
with their zip, we source likely-seller prospects in that zip, run outreach to those
sellers on the agent's behalf, and hand the agent a booked listing appointment. This is
the most valuable give and is exactly what the cold copy already promises. It REQUIRES a
real seller-prospect data source. Research below.

### Seller-prospect data sourcing — researched options (US)

**A. Free public records (zero data cost, high build/maintenance):**
- Pre-foreclosure: county recorder/clerk (Notice of Default, Lis Pendens, Trustee Sale).
  Per-state, per-county, no uniform API; must scrape each county site.
- Probate/estate: county court records + the curated probate-attorney lists we ALREADY build.
- Expired listings: needs MLS access (agent-gated) or a tool like REDX.
- High-equity / long-tenure / absentee: county tax assessor databases (free, messy).
- Verdict: real and $0 in data, but coverage is patchy and the per-county scraping is a
  large, brittle build. Good as a SUPPLEMENT, weak as the sole engine.

**B. BatchData (recommended paid engine):** 155M properties, 1000+ attributes, a
**Seller-Prediction propensity score** (identifies likely-to-list), Property Search by
zip + filters (equity, tenure, absentee, distress), AND skip-tracing (phone+email,
~76% right-party). Pricing: pay-as-you-go skip trace ~$0.02/record (down to ~$0.0066 at
scale); property data plans ~$500/mo (20k records) and up. This single provider covers
find + score + contact = the whole engine.

**C. ATTOM ($95/mo entry):** broad property/tax/deed/AVM data, 158M properties. Cheaper
entry than BatchData but NO native skip trace / propensity; better as a data backbone than
a turnkey seller-lead engine.

**D. Ready-made seller leads marketplace (iSpeedToLead etc.):** $26-$100+ per lead. No
build, but per-lead cost and you don't control quality/zip.

### Recommendation

Start with **BatchData pay-as-you-go**: it is the only single source that does
find-likely-sellers + score + skip-trace, so we can stand up the done-for-you appointment
engine without per-county scraping. Layer in the FREE probate/attorney data we already
have to enrich. Estimate: a 50-lead zip pull + skip trace ~ $1-2 in data per agent trial,
which is trivial against one closed listing (~$9k). Needs the user to open a BatchData
account + API key. Until then, build the engine against the free probate/curated data as a
thinner v1 so it works at $0, and flip to BatchData for full coverage when the key exists.

## FULL INVESTIGATION (2026-06-09): can we get REAL free seller leads?

Tested free web-search sourcing for zip 46220 -> returned only portal pages
(Zillow/Realtor/Redfin/ATTOM), zero contactable sellers. Web search finds pages
ABOUT a zip, not owners IN it. So plain search is a dead end. Investigated every
other free path:

**1. County assessor bulk data (FREE, real owners, NO contact):**
Some counties publish free bulk parcel downloads (e.g. Washoe, Sacramento) with
owner name + address. BUT: per-county only (no national free API), and NO phone/
email — so you can identify a likely-lister's house but cannot email/call them.
Usable for direct-MAIL or door-knock lists, not for email outreach. Build cost:
high (a different format per county).

**2. FSBO / expired listings (FREE, real, WITH self-published contact) — BEST FREE PATH:**
For-sale-by-owner sellers on Zillow-FSBO / Craigslist / ByOwner / FSBO.com are
ALREADY motivated to sell AND frequently publish their own phone/email in the
listing (Zillow routes its buttons to agents, so FSBOs put "contact seller: name,
phone" right in the description). FRBO (for-rent-by-owner) similarly. These are
the one free source that is both real AND contactable. Caveat: scraping those
sites is ToS-gray (the data is self-published, but the platforms restrict
automated collection) and volumes per zip are modest. This is "generating our own
leads for free" done honestly: harvest hand-raisers, not cold-scrape strangers.

**3. Inbound 'Free Home Value Report' funnel (FREE, real, highest-intent) — STRONGEST LONG-TERM:**
Instead of finding sellers, MAKE them raise their hand: a landing page / Facebook
post offering "Free Home Value Report for [zip] in 24h." Homeowners considering a
move opt in with their address + contact. This generates seller leads at $0 data
cost, fully consented, and is exactly the kind of asset the stack can host (we
already build hosted lead-magnet pages, e.g. the Diraya GHOSTS/REVIEW pages). The
agent's branded home-value page becomes the give: we run their inbound seller
funnel for them.

**4. The probate/estate ANGLE we already own (FREE, real referral path):**
We already build curated estate/probate ATTORNEY lists (real names, firms, direct
phones, verified). Those attorneys are the *referral source* to actual sellers
(families settling estates). Not direct seller contacts, but a real, warm,
already-built free give.

### Synthesis / recommendation

There is NO free source that hands you cold, contactable, named sellers at volume.
The honest free options are: harvest hand-raisers (FSBO/expired, #2) or generate
hand-raisers (inbound home-value funnel, #3). So the done-for-you appointment
engine, on free data, becomes:
  - Magnet to the AGENT = a branded "Free Home Value Report" seller-capture funnel
    we set up + run for them (#3), seeded with FSBO/expired hand-raisers in their
    zip (#2) and the probate attorney referral give (#4).
  - We run outreach to those (consented inbound + self-published FSBO) sellers on
    the agent's behalf and book the listing appointment.
This is real, free, and defensible. It is NOT "buy a list of strangers" (that
needs a paid API). It is a smaller funnel but every lead is a genuine hand-raiser,
which converts far better than cold-scraped owners anyway.

If the user later wants VOLUME of cold likely-sellers (high-equity/absentee/
pre-foreclosure with skip-traced phones), that requires a paid API (BatchData,
~$1-2 per agent trial) — no free substitute exists.

## Open questions for the user
- Zip Seller Snapshot: OK as the core magnet, or do you have a specific deliverable in mind?
- Daily cap 40 to start — good, or higher/lower?
- Should follow-throughs draw from the cold cap (shared 300) or be ON TOP of it?
- Snapshot delivery: PDF attachment, hosted link, or inline in the email?
