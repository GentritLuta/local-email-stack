# ENER-G go-live — remaining steps (blocked on Hostinger token)

Done 2026-06-08:
- Copy: kWh range changed to "ab 30.000 kWh, skaliert bis Millionen" across variants.json + profile target + proof point + value_note. JSON valid, 0 old-range refs.
- DB: profile `energ` pushed, sequence `energ-default` created (active), 7 variants upserted, 7 sequence_steps wired (delays 0,2,2,3,4,7,10).
- Scheduler: `LES-warmup-energ` created, DISABLED (mirrors LES-warmup-aureon: pyw warmup-scheduler.py tick --profile energ, daily 10:00).

BLOCKED — needs Hostinger API token for the philipp.loisha@gmail.com account
(the 8 ener-g-beratung.* subdomains live in a DIFFERENT Hostinger account than
the default HOSTINGER_API_TOKEN; existing token returns 403 "Customer does not
own ener-g-beratung.de").

## When you have the token

1. Generate token: hPanel (philipp.loisha@gmail.com) -> Account -> API -> Generate token.
2. Add to `sequences/hostinger.env`:  `HOSTINGER_API_TOKEN_ENERG=<token>`
3. Resend account = NEW (RESEND_NEW_ACCOUNT_API_KEY). 0 energ domains exist yet.
   Create + publish + verify ONE subdomain at a time (Resend unverified cap):
   8 subdomains: hello/team x .de/.org/.com/.store
4. Run autoprovision per domain (creates in Resend, pushes DNS via the energ token,
   verifies): `py sequences/domain_autoprovision.py --slug energ` (confirm it picks
   the per-profile token; else provision_subdomain.py per domain).
5. As each verifies, its resend_domain_id fills in profiles/energ.json from_domains[].
6. Source leads (currently 0): energ ICP = KMU/Gewerbe ab 30.000 kWh, ~100km around
   Neuss/Düsseldorf. Wire a lead source / import a list.
7. Enable warmup: `schtasks /change /tn LES-warmup-energ /enable`
8. PAUSE for user OK before first real send.
