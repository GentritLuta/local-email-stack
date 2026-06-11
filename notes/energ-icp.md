# ENER-G Beratung — ICP & Campaign Brief

Source: onboarding response (Philipp Loisha, submitted 2026-06-01) + ener-g-beratung.de.
Built 2026-06-07. Mirrors the Diraya campaign structure.

## Company

- **Legal name:** ENER G LLC
- **Brand / wordmark:** ENER-G Beratung
- **Website / brand site:** https://ener-g-beratung.de
- **Office:** Rincklakeweg 9, 48153 Münster
- **Contact:** info@ener-g-beratung.de · +49 15679 543705
- **Signer / intro calls:** Philipp Loisha
- **Notices email:** philipp.loisha@gmail.com
- **Positive replies route to:** loisha@energieberatung-schwabenland.de
- **Best call slot:** every evening from 19:00 CET; 15-minute kickoff

### What they do (from the live site)
Energieberatung for KMU & Gewerbe. Services:
- Strom & Gas optimization (Strombeschaffung / contract optimization)
- Solarlösungen (contracting model)
- Ganzheitliche Kostenoptimierung
- Stromsteuerrückerstattung (electricity tax refunds)

Brand promise: **"100 % transparent. 100 % auf Ihrer Seite."** — "Garantiert ohne
Überraschungen." Trust + transparency + no hidden fees is the core positioning.

## Ideal Customer Profile

| Dimension | Target |
|---|---|
| **Electricity usage** | 100,000 – 500,000 kWh / year |
| **Decision making** | ONE decision maker (do not over-compare vs other offers) |
| **Company size** | Does not matter |
| **Geography** | Germany only. Best: within ~100 km of Neuss / Düsseldorf |
| **Best-case timing** | Renting a new building / being founded in the next month / contract ending end-of-year (must act now) |

### Buyer titles (best converting)
Founder · Prokurist · Geschäftsführer (GF) · Inhaber

### Sectors to exclude
None.

## Buying signals (highest intent first)
1. **New business registration** — a just-founded company needs energy contracts immediately.
2. **Commercial lease signed / building permit filed** — moving into new premises, energy supply not yet arranged.
3. **Relocation announcement** (LinkedIn, local registry, new Google Maps listing) — high urgency, one DM handling everything.
4. **Change of ownership (Handelsregister update)** — new owner renegotiates all supplier contracts.
5. **Existing energy contract expiry** — buying window is 3–6 months before end date.

## Messaging angles (for the 7-email sequence)
- Dream outcome: lower energy cost, locked in before the contract/lease deadline, with zero surprises.
- Perceived likelihood: concrete savings framing + "100 % transparent, auf Ihrer Seite".
- Low effort: one 15-minute call, ENER-G does the procurement legwork.
- Low sacrifice: no switching headache, no hidden fees, independent (not a reseller pushing one tariff).
- Urgency hook: contract expiry / new lease / new founding = act now or lose the window.

## Sourcing plan (German market)
Same class as atalsolidrocks: German Impressum scraping is the reliable channel
(GF name + email + city are legally mandated on every German business site).
Geo-filter to the Neuss/Düsseldorf 100 km radius. Buying-signal sources:
Handelsregister updates, new Gewerbeanmeldungen, commercial lease / Bauantrag
filings, relocation posts. Port 25 is blocked on all boxes -> MX-verify only,
Resend bounce webhook is the post-send safety net.

## Sending setup
- **Brand / click site:** ener-g-beratung.de
- **Sending roots (all 4):** ener-g-beratung.de, .org, .com, .store
- **Subdomain pattern:** hello.<root> + team.<root> (8 sending subdomains, Diraya-style)
- **Reply-to (all personas):** loisha@energieberatung-schwabenland.de
- **Language:** German (proper umlauts, no em-dashes, no exclamation marks)
- **CTA:** 15-minute kickoff call (evenings 19:00 CET) — booking link TBD; falls back to reply-to-book.
- **DNS:** in-house, temporary access granted to Aureon, handover from June 3rd.
