# Migrating from Resend to AWS SES

When and how to switch the email backend. Lives here so it's not lost across operator hand-offs.

## Why this might happen

Resend Pro at $20/mo caps the account at **10 verified domains total** across all clients. AWS SES has no domain cap and costs $0.10 per 1,000 emails sent (effectively free at typical cold-outreach volume — even 50k sends/month is $5).

The codebase is provider-agnostic. The send path is the only thing that needs swapping. Everything else — Supabase schema, prospect verification, multi-tenant rotation, warmup, analytics, IMAP reply matching, unsubscribe pages, scraper, context enrichment — works identically.

## Triggers (when to migrate)

Switch the moment **any** of these becomes true:

1. **5th paying client** — at ~2 verified subdomains per client you hit the Resend Pro 10-domain ceiling. Without migrating you'd either share reputation pools across clients (one client's bounces damage another's domain reputation, accepted today as a known trade-off) or upgrade to Resend Scale ($90/mo).
2. **Sustained volume >50k/month across all clients** — at this point SES would cost <$5/mo vs Resend Pro's $20/mo, and Resend's marketing-tier features (dashboards, audiences) aren't being used. Cost crossover.
3. **A specific client refuses shared-domain reputation** — usually the more sophisticated buyers. SES + a dedicated subdomain per client solves this. Resend Pro doesn't.
4. **Need >1000 verified domains** — Resend Scale caps at 1000. SES has no cap.

## What changes in code

Total: ~30–50 lines, 1 day of work.

### 1. Profile schema

Add a `relay.backend` switch (already supported — `"backend": "resend"` is the only current value):

```jsonc
"relay": {
  "backend": "ses",                                 // ← was "resend"
  "ses_region": "eu-west-1",
  "ses_access_key": "(in <slug>.private.json)",    // SES uses an access key + secret pair
  "ses_secret_key": "(in <slug>.private.json)",
  ...
}
```

### 2. The actual send call

In `sequences/resend-pool-send.py` and `sequences/sequence-runner.py`, replace the Resend HTTP POST with a `boto3` SES call. The payload (from `email_render.build_payload`) is the same shape — Resend's JSON maps cleanly onto SES's `SendEmail` API:

```python
# OLD (Resend)
with httpx.Client(timeout=20) as r:
    resp = r.post(RESEND_API,
                  headers={"Authorization": f"Bearer {api_key}"},
                  json=payload)

# NEW (SES)
import boto3
ses = boto3.client("ses", region_name=profile["relay"]["ses_region"],
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key)
resp = ses.send_email(
    Source         = payload["from"],
    Destination    = {"ToAddresses": payload["to"]},
    Message        = {"Subject": {"Data": payload["subject"]},
                       "Body": {"Html": {"Data": payload["html"]},
                                "Text": {"Data": payload["text"]}}},
    ReplyToAddresses = [payload["reply_to"]],
    Tags           = [{"Name": t["name"], "Value": t["value"]} for t in payload["tags"]],
)
# resp["MessageId"] replaces Resend's resend_id throughout downstream code
```

### 3. Domain provisioning

In `sequences/provision_subdomain.py` and `sequences/domain_autoprovision.py`, replace `resend_create_domain` with SES `verify_domain_dkim`. SES returns three DKIM tokens; you publish three `<token>._domainkey.<domain>` CNAME records pointing at `<token>.dkim.amazonses.com`. The DNS-push half (Hostinger PUT to `/api/dns/v1/zones/{domain}`) stays identical.

```python
# OLD (Resend)
created = resend_create_domain(api_key, domain)
records = created["records"]  # SPF + DKIM + return-path MX

# NEW (SES)
ses = boto3.client("ses", region_name=region)
dkim = ses.verify_domain_dkim(Domain=domain)
records = [
    {"name": f"{t}._domainkey.{domain}", "type": "CNAME",
     "value": f"{t}.dkim.amazonses.com", "ttl": 3600}
    for t in dkim["DkimTokens"]
] + [
    {"name": domain, "type": "TXT", "value": "v=spf1 include:amazonses.com ~all", "ttl": 3600},
    {"name": f"_dmarc.{domain}", "type": "TXT",
     "value": f"v=DMARC1; p=none; rua=mailto:dmarc@{domain}", "ttl": 3600},
]
```

### 4. Bounce + complaint webhook

Resend webhook → AWS SNS subscription. SES sends bounce/complaint notifications to an SNS topic; subscribe a Lambda or a public HTTPS endpoint (your existing `resend-webhook.py` FastAPI app can be reused with a small adapter). The notification payload is JSON, structured differently from Resend's. Map:

| Resend field | SES + SNS equivalent |
|---|---|
| `data.email_id` | `mail.messageId` |
| `data.to` | `mail.destination[0]` |
| `event_type=email.bounced` | `notificationType=Bounce` |
| `event_type=email.complained` | `notificationType=Complaint` |
| `event_type=email.delivered` | (SES delivery events optional, opt-in) |

Update `imap-poll.py` not needed — IMAP reply detection works identically regardless of send backend.

### 5. Reply routing

SES doesn't host inboxes. Replies still route to `info@aureonglobal.de` via Hostinger's normal MX (already in place). The `LES-imap-poll` scheduled task keeps catching them. No change.

### 6. Production-access request

Out of the box, SES is in "sandbox mode" — you can only send to verified email addresses. To send to arbitrary cold-outreach recipients, submit a production-access request via the AWS SES console. **AWS scrutinizes cold-email use cases — they sometimes reject.** Plan for this:

- Wait until you have real Aureon client + AlgoAlpha client testimonials and case studies
- Submit the request describing your business model honestly: B2B outreach for verified client campaigns, with explicit consent + unsubscribe handling
- Include the unsubscribe URL pattern you already implement (`gentritluta.github.io/local-email-stack/unsubscribe.html?t=<token>`)
- Cite the bounce + complaint thresholds the system already enforces (>5% bounce → pause domain)
- Approval typically takes 24–48 hrs

If denied: stay on Resend Pro, eventually upgrade to Scale. The migration is not urgent until you genuinely cross one of the triggers above.

## What does NOT change

- Supabase schema (all tables)
- `prospects` verification, deduplication, unsubscribe flow
- The multi-domain warmup pool architecture (still independent per subdomain, just with SES underneath)
- Analytics dashboard
- Variant authoring + HTML rendering (`email_render.py`)
- IMAP reply ingestion + run pausing
- Scraper + context enrichment + brand autofill
- Tray notification daemon
- All the Windows Task Scheduler entries (they just call the same Python scripts that now talk to SES instead of Resend)

## Estimated effort

- Provider swap code: ~4 hours
- DNS provisioning swap: ~2 hours
- Webhook adapter for SES + SNS: ~3 hours
- Testing one client end-to-end: ~2 hours
- Production-access request + waiting: ~1 day calendar

Total: ~1.5 days of focused work, mostly waiting on AWS.

## What's already in place

Everything below the provider line. The current `sequences/email_render.py`, `sequences/profile_lib.py`, `sequences/sequence-runner.py`, and `sequences/resend-pool-send.py` already separate the *send envelope construction* from the *provider call*. The handful of `httpx.post(RESEND_API, ...)` lines are the only thing tightly coupled to Resend. The architecture deliberately routes through a thin provider boundary.

## Migration decision log

Record each future evaluation of the SES question here (date, decision, reasoning) so it's not re-litigated from scratch:

- **2026-05-17** — staying on Resend Pro. Two clients (Aureon + AlgoAlpha) sharing one 10-subdomain pool, ~0 sends/day in production today. SES would save ~$15/mo at projected volumes but the migration cost + AWS approval risk isn't paid back yet.
