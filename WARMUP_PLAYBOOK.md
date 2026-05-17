# Warmup Playbook — Private Mesh, $0/mo

The single thing that decides whether self-hosted cold email lands in the inbox or the spam folder is **sender reputation**. Without warmup, your first 50 sends from a brand-new subdomain go straight to spam at Gmail and Workspace. With a 4–6-week warmup mesh, the same subdomain can comfortably do 150+/day with inbox placement comparable to a paid relay.

This document is the mechanic for a fully self-hosted warmup mesh. No paid warmup network, no paid SaaS.

---

## 1. What "warmup" actually does

Mailbox providers (Gmail, Outlook, Workspace, Yahoo) score the **sending IP + domain pair** on three rolling signals:

1. **Engagement** — recipients opening, replying, marking-as-important, dragging-out-of-spam.
2. **Volume curve** — gradual ramp looks human; sudden 500/day from a 7-day-old domain looks spammy.
3. **Authentication consistency** — SPF + DKIM + DMARC pass every time, From: aligns with the signing domain, no header oddities.

A warmup mesh manufactures (1) and (2) on a controlled schedule, while the mail-server config makes (3) bulletproof.

---

## 2. Mesh topology

```
        m1.insaneaiautomation.xyz          m2.insaneaiautomation.xyz
        warmup-m1@m1.insane…               warmup-m2@m2.insane…
                    │                                    │
                    └────────────── SMTP ────────────────┘
                                  │
                  Each pair exchanges 5–15 emails per day
                                  │
                    n8n IMAP-trigger workflow on each mailbox:
                       open → mark-important → reply (5–60 min jitter)
```

**Minimum mesh size:** 5 sending subdomains, 5 mailboxes. **Recommended:** 10. More mailboxes → more cross-traffic → reputation builds faster and is more resilient to one mailbox going quiet.

All mailboxes live **on the Oracle Free Tier Postal VM** in IMAP-enabled accounts. Zero additional cost.

---

## 3. Setup checklist

### 3.1 DNS for each subdomain
For `m1.insaneaiautomation.xyz` (repeat for m2..m10):

| Record | Type | Value |
|---|---|---|
| `m1` | A | <Oracle VM public IP> |
| `m1` | MX | 10 m1.insaneaiautomation.xyz |
| `m1` | TXT (SPF) | `v=spf1 ip4:<Oracle IP> ~all` |
| `default._domainkey.m1` | TXT | `v=DKIM1; k=rsa; p=<from OpenDKIM>` |
| `_dmarc.m1` | TXT | `v=DMARC1; p=quarantine; rua=mailto:dmarc@m1.insaneaiautomation.xyz; pct=100` |
| `m1` (PTR / rDNS) | — | set via Oracle console: `<Oracle IP>` → `m1.insaneaiautomation.xyz` |

After each subdomain is configured, send a test message to `test@mail-tester.com` from `warmup-m1@m1.insaneaiautomation.xyz`. Required score: **9.0+/10**. If you score lower, fix the failing items before any warmup begins. Common gotchas: missing rDNS, DKIM key not propagated yet (wait 1 hour), DMARC `p=reject` too aggressive at first (use `p=quarantine` for 30 days then promote).

### 3.2 Postal mailbox provisioning
On the Oracle VM:
```bash
# Each mailbox needs IMAP access
postal mailbox:create warmup-m1@m1.insaneaiautomation.xyz --password=$(openssl rand -hex 16)
postal mailbox:create warmup-m2@m2.insaneaiautomation.xyz --password=$(openssl rand -hex 16)
# ... m3..m10
```

Store the IMAP credentials in n8n Credentials (one `imapEmail` credential per mailbox).

### 3.3 n8n workflows

Three workflows make the mesh run:

#### Workflow A — `warmup_sender` (cron, every 30 min during ramp; every 2 hours at steady-state)
1. Fetch warmup config from NocoDB `warmup_state` (which subdomain is on which ramp day; daily quota per subdomain).
2. For each subdomain `mN`:
   - Pick a *peer* subdomain `mK` (K ≠ N) using weighted random.
   - Decide whether to send now based on daily quota and time-of-day distribution (humans send during business hours; mesh mimics that with 70% of sends between 9am–6pm sender's TZ).
   - Generate a realistic email:
     - Subject from a pool of ~200 templates ("Quick question", "Following up on yesterday", "Q3 numbers", "Thoughts on this?", …)
     - Body 30–80 words, varying tone, no links in the first 2 weeks (links slightly hurt reputation early). Use Qwen 2.5 32B to generate fresh content per send so they don't look templated to content classifiers.
   - SMTP send from `warmup-mN@mN…` to `warmup-mK@mK…` via Postal.
3. Insert row into `warmup_log` for tracking.

#### Workflow B — `warmup_receiver_<mailbox>` (one per mailbox, IMAP trigger)
1. Triggered when a new mail arrives in `warmup-mN@mN…`.
2. If From: matches one of the mesh peers:
   - Mark as Read.
   - Star / mark as Important.
   - **Move out of Spam folder if it landed there** (this is the single highest-value engagement signal).
   - With 60% probability, queue a reply (insert into `warmup_replies` table) with delay `random(5min, 60min)`.
3. Insert row into `warmup_log` (`event=received`, `was_spam=…`).

#### Workflow C — `warmup_reply_dispatcher` (cron, every 5 min)
1. Pick queued rows from `warmup_replies` where `due_at <= now()`.
2. Generate a short, contextually-plausible reply via Qwen 2.5 32B:
   > System: "You are replying to a casual work email from a colleague. Write 1–3 sentences. Sometimes short. Sometimes ask a follow-up question. Tone: relaxed, professional."
3. SMTP send back through Postal as the original recipient mailbox.
4. Mark `warmup_replies.sent_at = now()`.

> **Why generate replies with the LLM:** modern spam filters can detect templated warmup traffic because identical reply text appears across many domains. Per-reply LLM generation defeats this. Costs zero extra (local Qwen).

### 3.4 Ramp schedule

Per sending subdomain, default ramp:

| Day range | Warmup sends/day (each direction) | Mesh peer count | Real production sends from this subdomain |
|---|---|---|---|
| 1–7 | 5 | 4 | 0 |
| 8–14 | 10 | 6 | 0 |
| 15–21 | 20 | 9 | 5/day (start of real outbound, tiny volume) |
| 22–28 | 30 | 9 | 20/day |
| 29–42 | 40 | 9 | 80/day |
| 43+ | 25 (maintenance only) | 9 | 150/day |

Warmup never fully stops — it drops to maintenance-mode (25/day) after the ramp completes so that quiet days don't erode reputation.

---

## 4. Monitoring

Grafana panels you'll want:

- **Warmup volume per subdomain** (sends, receives, replies, marked-as-spam-by-peer)
- **Spam-folder rate** (computed: of mails the receiver workflow processed, what fraction came from Spam) — should trend to ~0% by week 3
- **DMARC report ingest** — Postal parses incoming DMARC aggregate reports; any `p=quarantine` or `p=reject` line is an immediate flag
- **Mail-tester score history** — weekly automated run via the scraper service, hits `mail-tester.com` for each subdomain
- **Postal queue depth** — should stay near zero

Alert on:
- Spam-folder rate > 5% on any subdomain for 24 h → pause that subdomain's production sends, increase warmup intensity by 50%.
- Postal queue depth > 100 for > 5 min → SMTP delivery issue.
- DMARC failures > 1% → investigate before doing anything else.

---

## 5. Common failure modes and fixes

| Symptom | Likely cause | Fix |
|---|---|---|
| Spam rate stays > 20% after 4 weeks | rDNS not set, DKIM not aligned, or IP previously blacklisted | Check `https://multirbl.valli.org/lookup/` for the Oracle IP. Verify rDNS resolves. If IP is on a list, request delisting; if it's repeatedly listed, rebuild the VM (Oracle assigns a new IP). |
| All mail to one peer subdomain bounces | DKIM TXT record not yet propagated, or syntax error | `dig +short TXT default._domainkey.mN.insaneaiautomation.xyz` should return the public key. |
| Replies look obviously LLM-generated to humans | Qwen output too verbose or formal | Tighten the system prompt; add 3–5 in-context examples of "real" short replies. |
| Daily mesh volume keeps drifting upward | Reply chains running too long | Cap reply depth at 3 (track `in_reply_to` chain length). |

---

## 6. When you can stop reading and just trust the system

The mesh is **autonomous** after initial provisioning. After 6 weeks of clean warmup data with stable < 2% spam-rate and DMARC compliance:

1. Promote DMARC from `p=quarantine` to `p=reject`.
2. Cut maintenance warmup volume in half (it's there to prevent reputation decay during quiet periods).
3. Stop checking it daily. Grafana alerts you if anything changes.

At that point your $0/mo SMTP stack is reputationally equivalent to what Instantly's warmup gives a paid subscriber.
