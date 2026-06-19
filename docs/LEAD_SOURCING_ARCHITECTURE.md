# Lead-sourcing architecture: plan, decision, and what shipped

Prepared 2026-06-14. The operation had pool-starvation across several brands. This is the source map, the options considered, the option picked, and what was built.

## The problem, stated honestly

Every brand's volume is gated by one thing: how many fresh, verified, on-ICP leads land in the pool per day. The diraya research already proved the ceiling on the only high-volume source we had:

- The shared scraper (`lead_scrape.py`) finds leads by Google web search (Serper `/search`) for company "team" pages, then visits each page and extracts a mailto. This works for companies that publish a team page with emails (B2B SaaS, agencies, crypto research).
- It does NOT fit **local businesses**, which is what the local-business brands target: aureon (US real estate), lk-advertising (US real estate), energ (German industrial KMU), mark-eting (US service trades: plumbing, HVAC, roofing, law, CPA). A plumber or a broker rarely has a "team page" with a mailto, so team-page SERP scraping starves these pools.
- Local businesses DO all have a Google Business Profile with a website, and the website has a contact email.

## Sources that exist today

| Source | File | Fits | Status |
|---|---|---|---|
| Team-page web SERP | `lead_scrape.py` + `seed_discover.py` (Serper `/search`) | B2B / SaaS / agencies | Works; low yield for local |
| German Impressum | `impressum_scrape.py` | DACH B2B (law-mandated contact) | Works |
| YC / startup sites | `diraya-site-scrape.py` | diraya | Works, ~100 ceiling |
| YouTube | `youtube_scraper.py` | algoalpha, dorian | Works (API key) |
| TradingView | `tradingview_scrape.py` | algoalpha | Works |
| Social (IG/X/TikTok/Twitch) | `social_scrape.py` | dorian, algoalpha | IG ~25%, X ~20%, TikTok <5% |
| Crypto projects | `crypto_projects_scrape.py` | algoalpha | Works (free APIs) |
| CSV import | `import-prospects-csv.py` | any bulk list | Works |

Search backend chain (in `seed_discover.py`): Serper.dev -> Brave -> Google CSE (dead) -> keyless scrapers (Startpage, Mojeek) -> ddgs. **Serper is only ever called on `/search`. Its `/places` endpoint is never used. There is no Maps/Places/Yelp/directory source anywhere.**

## Options considered

1. **Google Maps/Places via Serper `/places`** (NEW). Query "<category> in <city>" -> each business's website -> scrape email. Reuses the existing Serper key (no new spend) and the whole extract/verify/upsert pipeline. Serves the local-business brands, which is where the starvation is. Bonus: Places returns the business NAME and CITY directly, which fixes the city-required brands (atalsolidrocks) that team-page scraping leaves cityless.
2. **Bulk B2B data (Apify Lead Finder)**, ~$45/mo. Guaranteed high volume for the B2B brands (diraya). Researched, costed, ready to wire. Needs the operator to fund an account. Pending the operator's go-ahead.
3. **More keyless SERP sources / tune `seed_discover`.** Marginal; the keyless engines are already wired and the limit is yield-per-query, not the engine.
4. **LinkedIn bot.** High yield for B2B contacts, but ToS-hostile, needs login, fragile, ban risk. Not worth building in-house.
5. **Yelp / BBB / industry directory scrapers.** Viable, but Google Places already aggregates these businesses with a website link, so a Places source covers most of the value with one bot.

## Decision

**Build option 1 (Google Places via Serper) now.** It is the highest leverage per hour of work and per dollar: zero new spend, serves the majority of brands, reuses ~80% of the existing pipeline, and directly fixes the local-business starvation that no current source addresses. Keep option 2 (Apify) as the optional paid backbone for the B2B brands, to wire the moment the operator funds it. Options 3-5 are not worth the effort given 1 and 2 cover the field.

## What shipped (full rollout — every client)

- `sequences/places_scrape.py` — new source. `run <niche>` reads a `places:` block in the niche YAML (categories x cities, or explicit queries), calls Serper `/places`, visits each business website (home + /contact + /about), extracts + verifies the email, and upserts with `company` = business name and `city` = the queried city. A `.places.done` cursor rotates through the query space across runs. Honors `filter` (exclude locals/domains), a per-block `require_first_name`, the same-domain email rule (the lead's email must be on the business's own domain, which blocks third-party/spam addresses), and the shared no-solicitation compliance gate. SMTP probe off by default (port 25 blocked) -> MX-only verification.

- `places:` blocks now on all eight niches, localized per market:
  - aureon -> `real_estate_us` (US, 60 queries)
  - lk-advertising -> `real_estate_us_lk` (US, different cities, 60)
  - mark-eting -> `mark_eting_us_service` (US trades + pro services, 280)
  - energ -> `energ_gewerbe_nrw` (DE, energy-intensive sectors, 240)
  - atalsolidrocks -> `atal_dach_b2b` (DE high-sick-leave sectors, named-only, 120)
  - diraya -> `diraya_b2b_saas` (US tech/software, supplementary, 75)

- `pool-monitor.py` — now covers every brand and runs each one's correct source hourly:
  - Local brands: team-page scrape + Places, run ALONGSIDE each other (restructured so an extra scraper is never blocked by a team-page scrape still running; the running-check is niche-specific so brands sharing `places_scrape.py` do not block one another).
  - algoalpha: YouTube + TradingView creator scrapers (Places does not fit crypto creators).
  - dorian: creator-only (niche = None) -> YouTube discover/run + Instagram/X, wired into pool-monitor so it auto-refills like the rest.

Throughput / cost note: Places (and `/search`) burn Serper credits (2,500 free one-time, then a paid plan ~$50/mo for 50k). pool-monitor only scrapes a brand while it is below its 2x buffer, so the burn is front-loaded to FILL the pools, then drops to steady-state refill. The free credits will build a large pool fast; sustaining many brands long-term will want a Serper paid plan. For a brand that must guarantee a high fixed daily number (diraya at 180/day), the Apify bulk backbone (option 2) remains the only guarantee; Places is the no-spend workhorse for the local brands.
