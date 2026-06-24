# Legal Lead Sourcing + Enrichment Upgrade

Spec, 2026-06-15. The goal you described: the best lead scraping + enrichment on earth.
The Pegasus idea is off the table (device intrusion is illegal and would torch
deliverability). This is the legal path that actually wins, and it builds on what the
stack already has instead of replacing it.

## Why legal sourcing beats spyware for THIS business

Cold email lives or dies on deliverability. What you need is **published, deliverable
business contacts** that you are allowed to email. Spyware harvests **private personal
data from compromised devices** — unconsented, undeliverable through warmed domains
without spam complaints, and a legal/reputational time bomb. The two are opposites. The
edge is not "more invasive data," it is **more channels + better timing + cleaner
verification** than competitors run.

## What already exists (build on this, do not rebuild)

- `lead_scrape.py` (search-driven), `seed_discover.py` (fresh-seed expansion),
  `impressum_scrape.py` (German Impressum published emails), `places_scrape.py`
  (Google Places), `social_scrape.py`, `youtube_scraper.py`, `tradingview_scrape.py`,
  `diraya-harvest-full.py` (YC published-founder-email harvest).
- `lead_verify.py` (MX/SMTP verification), `compliance.py` (no-solicitation skip),
  21 niche YAMLs, Serper + Brave search backends (`search.env`).
- `daily-fill-and-enroll.py` orchestrates scrape -> verify -> enrich -> enroll per profile.

Three real gaps limit it today: (1) too few **discovery channels** per ICP, (2) thin
**enrichment** (no role/tech/signal layer), (3) no **timing signals** (we email cold,
not when a trigger fires). This spec closes all three.

---

## Phase 1 — More legal discovery channels (breadth)

Each is a new scraper that emits the same prospect shape `lead_scrape` already writes, so
`daily-fill-and-enroll` picks them up with one `PROFILE_CFG` entry. All target PUBLISHED
business contacts only; `compliance.py` still gates every send.

| Channel | Source | Yields | Notes |
|---|---|---|---|
| **Company-site contact harvest** | crawl the prospect domain's /contact, /about, /team, /impressum | published role emails | generalize `impressum_scrape.py` beyond German; highest deliverability (published = ~0 bounce) |
| **Crunchbase / public company pages** | Serper site: queries + page scrape | founder/exec names + company domain (then verify-guess email) | public pages only |
| **GitHub orgs** | GitHub public API (no auth needed for public) | maintainer emails on commits / org public emails | great for dev-tool / SaaS ICPs |
| **Product Hunt makers** | PH public pages / API | makers of newly-launched products in an ICP | strong "they just shipped" timing |
| **Conference / event attendee + speaker lists** | public agendas, speaker pages | name + company, verify-guess email | niche-specific, very warm |
| **Podcast guest pages** | show notes / guest bios | founder + company | guests publish contact; high intent |
| **Directory scrapers** | industry directories (per ICP) | name/company/site | one generic directory scraper, config-driven per niche |
| **Job-board company extraction** | companies actively hiring for a role your client serves | company + hiring signal | doubles as a timing signal (Phase 3) |

**Build pattern:** one `sources/<channel>.py` each, emitting
`{email?, first_name, company, website, role?, source, niche_slug, signals{}}`. Where an
email is not published, write the record WITHOUT an email and let Phase 2 derive+verify it.
Reuse the existing Serper/Brave backends; no new search vendor needed.

## Phase 2 — Enrichment layer (depth)

A new `enrich/` pass that runs after scrape, before verify. Turns a bare
name+company+domain into a contactable, personalizable lead.

1. **Email derivation + verification (free).** When only name+domain is known, generate
   candidate patterns (first@, first.last@, f.last@, etc.), MX-check the domain, then
   SMTP/catch-all probe via the existing `lead_verify.py`. Keep only verified or
   safe-catch-all. This is the single biggest pool multiplier and it is free.
2. **Role + seniority** from the company-site/team-page scrape (Phase 1) or the source
   page — so the sequence can address a founder vs a marketing lead differently.
3. **Tech / category** from the company site (keywords, meta, obvious stack tells) — feeds
   personalization ("saw you run X").
4. **Company size proxy** from the count of distinct emails scraped on that domain (already
   computed in `sequence-runner` for team_size merges) — extend it.

Store enrichment in `prospects.custom_fields.enrichment` (no schema migration). The merge
fields the sequences already support (`geo_clause`, `team_phrase`, etc.) get real data
instead of synthesized fallbacks.

## Phase 3 — Timing signals (the real edge)

Cold outreach converts far better when it lands on a trigger. A new `signals/` pass tags
prospects with recent public events; `daily-fill-and-enroll` prioritizes enrollment of
signal-tagged leads, and the sequence opens with the trigger.

| Signal | Public source | Why it converts |
|---|---|---|
| **Hiring** for a relevant role | job boards / company careers page | they have the budget + pain your client solves |
| **Just launched** | Product Hunt, press, GitHub release | momentum + receptive to tools |
| **Funding / news** | public news search (Serper news) | new budget |
| **New content / talk** | their blog, podcast, conference | concrete personalization hook |
| **Tech change** | site rebuild, new stack tells | switching = buying window |

Each signal becomes a `prospects.custom_fields.signals[]` entry with a date. The runner
already supports inline A/B and merge tags, so a "signal opener" variant is a small add.

## Phase 4 — Paid API fallback (only where free runs dry)

Free sourcing is the default. When a client's pool stalls (you hit this with energ/dorian),
a paid enrichment/contact API is the legal, high-ROI lever — NOT scraping harder. Pluggable
behind one interface (the `source-seller-leads.py` provider pattern already does this):
- **Apollo / Clearbit-style**: verified B2B contacts + firmographics on demand.
- **BatchData** (already slotted, disabled): skip-traced contacts for real-estate ICPs.
Gate by cost-per-lead; only fire when free channels are exhausted for that niche.

## Guardrails (unchanged, non-negotiable)

- `compliance.py` skips any site forbidding marketing email (EN + German Impressum
  anti-Werbung). Applies to EVERY new channel.
- Only verified prospects send (`lead_verify.py`).
- Warmup ramp + bounce/reputation/rate/quiet-hours guards on every send.
- One-click unsubscribe + legal footer on every email.
- No private/credentialed data, ever. Published business contact info only.

## Suggested build order

1. **Company-site contact harvest** (generalize `impressum_scrape.py`) — biggest near-zero-bounce
   win, helps every client immediately.
2. **Email derivation + verify enrichment** (Phase 2.1) — multiplies every channel's yield.
3. **One signal: "hiring"** via job-board extraction — proves the timing edge end to end.
4. Then fan out the remaining Phase 1 channels per the ICPs that need pool growth
   (energ, dorian first — they are the source-constrained ones).
5. Paid API fallback wired but OFF until a pool genuinely stalls.

Close items 1-2 and every client's pool grows on autopilot with near-zero bounce. Add item 3
and you are timing outreach to triggers, which is where the conversion lift is.
