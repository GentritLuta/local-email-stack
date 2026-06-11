# Aureon self-hosted tracker — deployment

Resend's `open_tracking` / `click_tracking` flags on the domain config are
set true on every Aureon subdomain but their pipeline does NOT actually
inject the tracking pixel or rewrite click URLs on outbound emails.
Verified empirically with raw HTML probes (see send_log resend_id
`e1b99cbf-ba54-45cc-b123-69fe5671063d`).

Workaround: inject our own pixel + click-rewrite in `email_render.py`
(already done) and serve them from a tiny Cloudflare Worker that updates
`send_log.opened_at` / `clicked_at` directly via Supabase REST.

## 1. Deploy the Worker (~5 min, free tier)

1. Go to https://dash.cloudflare.com → **Workers & Pages → Create application → Create Worker**
2. Name it something like `aureon-tracker`
3. Click **Deploy** (uses default hello-world template — we'll replace it)
4. Click **Edit code**
5. Replace the entire `worker.js` contents with `workers/track-open.worker.js` from this repo
6. Click **Save and deploy**

## 2. Add secret bindings

In the Worker dashboard, go to **Settings → Variables and Secrets → Add variable**.
Add both as **Type: Secret**:

| Name | Value |
|---|---|
| `SUPABASE_URL` | `https://<project-ref>.supabase.co` (from `sequences/supabase.env`) |
| `SUPABASE_SERVICE_KEY` | the **service-role** key (NOT anon) — get it from Supabase dashboard → Project Settings → API → service_role secret |

> Why service-role, not anon? The anon key has RLS policies that may block PATCH operations on `send_log`. Service-role bypasses RLS, which is fine because this Worker only PATCHes `opened_at` and `clicked_at` — read-only fields from the user perspective.

## 3. Point DNS at the Worker

`email_render.py` injects pixels at `https://track.aureonglobal.de/open/{token}`.
Map this subdomain to the Worker:

1. In the Worker, go to **Settings → Triggers → Custom Domains → Add Custom Domain**
2. Enter `track.aureonglobal.de`
3. Cloudflare gives you a CNAME or A record to add. You can:
   - **Option A** (recommended): transfer aureonglobal.de's DNS to Cloudflare (free), then the custom domain works automatically
   - **Option B**: keep DNS at Hostinger, manually add the CNAME from Cloudflare's instructions

## 4. Verify

After DNS propagates (~1-10 min):

```bash
curl https://track.aureonglobal.de/
# expected: "aureon track ok"
```

Then trigger a fresh send via `sequence-runner.py tick`. The HTML body
will contain `<img src="https://track.aureonglobal.de/open/<TOKEN>.gif">`.
When the recipient opens the email, the pixel loads, the Worker logs the
open, `send_log.opened_at` is set, and the reconciler will report it.

## 5. Optional: temporarily disable tracking

If you want to send without tracking (e.g. during testing or if the
Worker is down), set:

```bash
export AUREON_TRACKER_BASE=""
```

The `_inject_tracking` helper in `email_render.py` no-ops when the base
URL is empty.

## What's NOT covered by this

- Resend's `last_event` field (`delivered` / `bounced` / `complained`)
  still comes from their reconciler — we did NOT replace that. Their
  delivery + bounce events work fine; only their **open / click** injection
  is broken on our domains.
- Replies are captured by `imap-poll.py` against Hostinger IMAP. That's
  independent of this tracker.

## Cost

- Cloudflare Workers free tier: 100,000 requests/day
- At 500 sends/day full ramp + ~30% open rate ≈ 150 open events/day = 0.15% of free tier
- No cost.
