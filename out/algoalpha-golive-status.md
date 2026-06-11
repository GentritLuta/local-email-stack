# AlgoAlpha go-live — LIVE (all 12 tryalgoalpha.com domains verified, warmup day 1)

## STATUS 2026-06-08: LAUNCHED
- 12/12 tryalgoalpha.com subdomains VERIFIED in Resend, synced to DB.
- send_ramp + warmup reset to 2026-06-08 (day 1) so brand-new domains warm safely
  (was stale May 18 = would have blasted full-rate on cold domains; fixed).
- Profile active=true. Next LES-sequence-runner tick begins sending at day-1 warmup
  (~15/domain cap, 80% warmup traffic so ~36 real prospect sends/day, ramping up).
- 313 verified leads, 140 already enrolled; rest enroll as cap rises.
- Watch deliverability over first 2 weeks (LES-warmup-algoalpha advances the ramp daily).

---
# (history) DNS provisioned on tryalgoalpha.com

Sending identity = subdomains of **tryalgoalpha.com** (Cloudflare zone db590d15...,
token in hostinger.env as CF_API_TOKEN_ALGOALPHA / CF_ZONE_ID_ALGOALPHA).

Done 2026-06-08:
- Pivot: the old algoalpha.* / getalgoalpha guesses were wrong. Real domain = tryalgoalpha.com.
  Deleted 12 mis-named *.algoalpha.* Resend domains.
- Profile: 12 subdomains of tryalgoalpha.com (hello/team/mail/hi/reach/connect/partners/growth/
  desk/hub/news/send) + 12 personas, reply_to=info@aureonglobal.de (the monitored mailbox).
- Resend: 12 domains created (eu-west-1), domain_ids saved to profile.
- Cloudflare DNS: 36 records pushed correctly (DKIM TXT, SPF TXT, MX per subdomain). NOTE: first
  push had a doubled-name bug (hello.hello.tryalgoalpha.com); 36 bad records deleted, re-pushed clean.
- DB: profile active=true (safe: iter_send_domains only_verified=True -> 0 verified = 0 sends).
  Sequence algoalpha-default active, 7 variants, 7 steps. 313 verified leads, 140 already enrolled.
- Scheduler: LES-warmup-algoalpha already exists + enabled (warmup-scheduler.py tick --profile algoalpha).

IN PROGRESS: Resend verification polling (DNS just pushed, needs propagation). Re-run:
  py scripts/_provision-algoalpha-cf.py   (idempotent: re-triggers verify, stamps verified_at)

## After all 12 verify
1. verified_at stamps into profile from_domains[] (sync to DB profiles.config).
2. send_ramp.started_at: confirm stamped on first runner tick so per-persona ramp begins.
3. Enrollment: daily-fill-and-enroll already has 140/313 enrolled; the rest enroll as warmup cap rises.
4. PAUSE for user OK before first real send (warmup day 1 = 15/domain cap, mostly warmup-targeted).

## Helper scripts created
- scripts/_setup-algoalpha-senders.py   (rebuild 12 subdomains + personas)
- scripts/_provision-algoalpha-cf.py     (Resend create + CF DNS push + verify)
- scripts/_fix-algoalpha-replyto.py       (force reply_to to monitored mailbox)
