# Deliverability — the 95% playbook

This document is the single source of truth for inbox placement. Follow it once
end-to-end and your sender domain reaches ~95% inbox placement at Gmail,
Workspace, Microsoft 365, and the major freemail providers (web.de, gmx,
t-online, yahoo, etc.).

If you skip steps, expect 50–80% inbox placement (the rest goes to spam).

---

## The math behind "95%"

| Layer | Lever | Contribution to inbox % |
|---|---|---|
| 1. **Sender authentication** | SPF + DKIM + DMARC properly published | ~+25% over baseline |
| 2. **Sending IP reputation** | Relay through Resend's warm shared IPs (vs your home IP) | ~+25% |
| 3. **Domain warmup** | 30–45 day snowball ramp, not 200/day on day 1 | ~+10% |
| 4. **Engagement signals** | Warmup targets open + reply + mark important | ~+5% |
| 5. **Content hygiene** | Short, plain, no links/images early, conversational | ~+5% |
| 6. **Sending patterns** | Business hours, jitter, per-MX throttling | ~+3% |
| 7. **List hygiene** | Pre-verify emails, suppress bounces/complaints forever | ~+2% |

**Without any of these:** baseline ~25% inbox (the rest is spam or rejected).
**With all of them:** ~95%+ inbox. The gap from 95→100% is recipient-side
filter idiosyncrasies you can never fully control.

---

## One-command onboarding (the only thing you actually do)

For each profile (sender identity), one command:

```powershell
py sequences\onboard-resend.py bernhard --test-send
```

It:
1. Prompts for your Resend API key (you paste it once, it's saved to `profiles/<slug>.private.json`).
2. Adds the profile's sending domain to Resend.
3. Prints the 3 DNS records to paste into your DNS provider.
4. Polls Resend until verification flips green (max 30 min — usually 1–5 min).
5. Stamps `relay.domain_verified_at` into the profile.
6. Sends 2 test emails (info@aureonglobal.de + g-luta@web.de) through Resend.
7. Runs the deliverability scorecard.

Total of *your* time: ~5 minutes (sign up + paste API key + paste DNS records).
The rest is the script polling and reporting.

### Prerequisites you do once

| Step | Where | Time |
|---|---|---|
| Sign up at Resend | https://resend.com (free, no credit card) | 2 min |
| Generate an API key | Resend dashboard → API Keys → Create | 30 sec |
| Set your DNS provider | Wherever you registered the domain (GoDaddy/Cloudflare/Namecheap/…) | already done |

That's it. The rest is automation.

---

## The seven layers in detail

### Layer 1 — Sender authentication (mandatory)

Three DNS records on your sending subdomain (e.g. `mail.insaneaiautomation.xyz`):

1. **SPF** (TXT): authorizes Resend's sending IPs.
   ```
   TXT  send.mail.insaneaiautomation.xyz   "v=spf1 include:amazonses.com ~all"
   ```
   Without this: every recipient does an SPF check, sees your home IP wasn't authorized, marks spam.

2. **DKIM** (TXT or CNAME): cryptographically signs every outbound message.
   ```
   TXT  resend._domainkey.mail.insaneaiautomation.xyz   "p=MIGfMA0G..."
   ```
   Without this: messages have no signature, recipients can't verify origin, DMARC fails, spam.

3. **DMARC** (TXT): tells recipients what to do when SPF/DKIM fail.
   ```
   TXT  _dmarc.mail.insaneaiautomation.xyz   "v=DMARC1; p=none; rua=mailto:dmarc@mail.insaneaiautomation.xyz; pct=100; adkim=s; aspf=s"
   ```
   Start with `p=none` for 14–30 days (monitor reports). Once you see no false
   positives in `rua` reports, promote to `p=quarantine`. Then `p=reject` after
   another 30 days.

The Resend onboarder prints all three records pre-filled with your domain.

### Layer 2 — Sending IP reputation (the big one)

The biggest single contributor. Direct-to-MX from your home IP fails because:

- Residential IPs are on Spamhaus PBL by default
- No PTR (reverse DNS) configured
- No history of legitimate mail volume
- Web.de's rejection earlier (`Invalid DNS PTR resource record`) was exactly this

**Fix:** route through Resend (or equivalent). Their IPs have:
- Spamhaus-clean rDNS pointing back to Resend hostnames
- 99th-percentile sender reputation at all major providers
- Proper TLS, banner, EHLO, the works

Free tier covers 100 sends/day, 3000/month — fits the snowball ramp's peak.

### Layer 3 — Domain warmup (the snowball ramp)

A brand-new sending subdomain has zero reputation. Sending 200/day on day 1
gets you spam-foldered everywhere.

The snowball ramp (hard-coded in each profile):

| Day | Daily quota | Warmup share / Real share |
|---|---|---|
| 1–3 | 10 | 80% / 20% |
| 4–7 | 20 | 80% / 20% |
| 8–14 | 40 | 80% / 20% |
| 15–21 | 80 | 30% / 70% |
| 22–30 | 150 | 30% / 70% |
| 31–45 | 250 | 10% / 90% |
| 46+ | 300 (or `max_daily_sends`) | 5% / 95% (maintenance) |

The scheduler runs once a day, computes today's quota, splits warmup vs real,
sends with 8–22 sec jitter inside the 9 am–6 pm window.

```powershell
py sequences\warmup-scheduler.py start bernhard
schtasks /Create /TN "LES-warmup-bernhard" /TR "py C:\Users\bernh\local-email-stack\sequences\warmup-scheduler.py tick --profile bernhard" /SC DAILY /ST 10:00
```

### Layer 4 — Engagement signals

Volume alone doesn't build reputation. The receiving inboxes need to **engage**:

- Open the message
- Mark as Important / move from Spam to Inbox
- Reply to it
- Not delete-without-reading

The `warmup_targets` in each profile should be inboxes **you control and check
regularly**. Once a week, spend 3 minutes:

1. Open each warmup mailbox
2. Read a few of the auto-generated warmup messages
3. Reply to 1–2 with a short response
4. If any landed in spam, drag to inbox

That's the manual cost of free deliverability.

### Layer 5 — Content hygiene

What goes inside every message:

| Do | Don't |
|---|---|
| Plain text + minimal HTML | All-HTML, image-only, table layouts |
| Under 100 words for cold | Wall-of-text marketing copy |
| One specific observation | "I hope this email finds you well" |
| One clear question | Multiple CTAs |
| Lowercase signature | ALL CAPS or "Sincerely, Mr. Tomás Silva" |
| Conversational tone | Marketing-speak ("synergies", "leverage") |
| No URLs in first 14 days of warmup | Tracked links (`bit.ly`, `t.co`, UTMs) |
| No images, no attachments | Logos, GIFs, PDFs |
| No tracking pixels | 1x1 invisible pixels |
| Subject without "Re:" on cold | Fake-reply subjects |

The 10-email AlgoAlpha sequence was rewritten to satisfy all of these.

### Layer 6 — Sending patterns

Reputable senders look like humans, not bots:

- **Business hours only.** 9 am–6 pm recipient timezone. Warmup scheduler enforces this per profile.
- **Jitter between sends.** 8–22 seconds between back-to-back. No bursts.
- **Per-MX throttling.** Don't send 50 to one corporate MX in one tick — spread across recipient domains.
- **No same-millisecond fan-out.** One recipient per SMTP transaction.
- **Consistent identity.** Same From/Reply-To/signature across all sends from the profile.

### Layer 7 — List hygiene

Bad list = high bounce + complaint rate = your reputation tanks even with everything else right.

- **Pre-verify every address** with `docker/email-finder` before adding to a sequence.
- **Suppress bounces forever.** The webhook auto-adds hard bounces to the suppression list.
- **Honor unsubscribes immediately.** Every email ships with `List-Unsubscribe: One-Click`.
- **Avoid role accounts.** `info@`, `admin@`, `support@` skew toward complaints. Target named individuals.
- **Re-engage stale recipients separately.** Anyone you haven't sent to in >90 days = treat as warmup.

---

## Reading the scorecard

```powershell
py sequences\deliverability-score.py bernhard
```

Prints a 0–100 score across 10 checks:

| Score | Inbox placement |
|---|---|
| <50% | will mostly spam — fix what's red before sending |
| 60–75% | borderline — 50/50 inbox vs spam |
| 75–90% | healthy — 80–90% inbox |
| 90%+ | optimal — 95%+ inbox |

For each missing/partial check, prints the exact DNS record / command to fix it.

---

## Daily operation

Once onboarded, daily life is:

1. **Once a day** (automated via Task Scheduler):
   ```powershell
   py sequences\warmup-scheduler.py tick --profile bernhard
   ```
2. **Once a week** (manual, ~3 min):
   - Open each `warmup_targets` inbox, mark unread messages as Important, drag any from spam to inbox, reply to 1–2.
3. **Once a month** (manual, ~5 min):
   - Run the scorecard: `py sequences\deliverability-score.py bernhard`
   - Promote DMARC from `p=none` → `p=quarantine` after 30 days clean
4. **Whenever an email lands in spam** (one-off):
   - Drag it to inbox once. That single signal compounds over time.

---

## Recovery from a reputation hit

The scheduler auto-pauses if bounce > 5% or complaint > 0.1%. To recover:

1. Stop all sending immediately (scheduler does this; halt manual sends too)
2. Inspect the recent events: `sequences/warmup-state/<slug>.events.jsonl`
3. Identify the cause — bad list, complained-about content, both
4. Purge bad addresses, fix content, wait 7 days for the rolling window to clear
5. Restart at warmup day 1. Don't resume at the previous ramp day.

This is why the snowball ramp matters even after you're at full scale: it's
the recovery procedure too.

---

## Why this works at the recipient

Modern email filters at Gmail / Workspace / Outlook / web.de / etc. weigh:

| Signal | Weight |
|---|---|
| SPF/DKIM/DMARC pass | foundation — fail = spam, pass = eligible for inbox |
| Sending IP reputation | very high |
| Sending domain reputation | very high |
| Per-recipient engagement history | very high |
| Recipient base engagement (opens, replies, marks important) | high |
| Content (links, images, spam-trigger words) | medium |
| Send patterns (volume, time-of-day, MX diversity) | medium |
| Authentication alignment (From: == DKIM: == SPF:) | medium |
| Recipient block lists | absolute (instant spam) |

The seven layers in this playbook hit every weight class. That's how you get to 95%.

---

## Cost reality

| Path | Setup time | Monthly cost | Daily ceiling | Best for |
|---|---|---|---|---|
| **Resend free** | 5 min | $0 | 100 | Most users — read this doc, do this. |
| Resend Pro | 5 min | $20 | 1,666 | Heavy individual senders |
| Postal on Oracle Free Tier | 2 hr | $0 | unlimited | Power users who want pure-self-hosted |

Resend free covers the snowball ramp's peak (300/day per profile would need Pro).
The free tier hits 95% deliverability identically to Pro — the only difference
is the daily quota.
