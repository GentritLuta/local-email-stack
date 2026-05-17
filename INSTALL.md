# Install — clone to running in ~15 minutes

Everything in this repo is the *code* + the *config templates*. Three services
provide the live runtime: **Hostinger** (DNS for your sending domain),
**Resend** (free outbound mail) and **Supabase** (free cross-PC state). All three
have permanent free tiers that cover normal personal use.

This guide assumes a fresh clone on a new machine, no prior context.

---

## 1. Prerequisites

| Tool | Why | How |
|---|---|---|
| **Git** | clone the repo | https://git-scm.com/ |
| **Python 3.10+** | all sender / sync / warmup scripts | https://www.python.org/ |
| **Node 20+** | desktop app frontend | https://nodejs.org/ |
| (optional) **Rust** | build the desktop app as a native `.exe` | https://rustup.rs/ |

After install, in a terminal:

```bash
pip install httpx asyncpg pydantic dnspython
```

---

## 2. Clone

```bash
git clone https://github.com/<your-username>/local-email-stack.git
cd local-email-stack
```

---

## 3. Set up Supabase (cross-PC state, free)

1. https://supabase.com → sign up (GitHub auth is fastest)
2. **New project** → name `local-email-stack` → Europe region → strong DB password
3. Wait ~60 s for provisioning
4. **SQL Editor → New query** → paste contents of [`supabase/schema.sql`](./supabase/schema.sql) → **Run**.
   Expected result: `Success. No rows returned`.
5. **Settings → API Keys → Legacy anon, service_role API keys**:
   - copy **Project URL** (`https://<id>.supabase.co`)
   - copy **anon public** key (long JWT starting with `eyJ…`)
6. Create `sequences/supabase.env`:
   ```
   SUPABASE_URL=https://<your-id>.supabase.co
   SUPABASE_ANON_KEY=eyJ...
   ```

---

## 4. Set up Resend (outbound mail, free)

1. https://resend.com → sign up
2. **API Keys → Create API Key** → permission **Full access** → copy `re_…`
3. Pick a **dedicated sending subdomain** of a domain you own
   (e.g. `mail.example.com`). Don't use your primary domain.
4. **Domains → Add domain** → enter the subdomain → Resend gives you DNS records.
5. Add those records at your DNS provider.
   - If your domain is on **Hostinger**: use [`sequences/resend-setup.py`](./sequences/resend-setup.py)
     to call Hostinger's DNS API and push them automatically. Requires a Hostinger MCP
     setup, or paste manually in hPanel.
   - Otherwise: paste them in your DNS provider's UI (Cloudflare, GoDaddy, etc.)
6. Resend verifies in ~5 min.

Once verified, edit `profiles/<your-profile>.json`:
- set `identity.from_addr` to a sender address on your verified subdomain
  (e.g. `daniel@mail.example.com`)
- set `relay.from_domains[0]` to the subdomain

Create `profiles/<your-profile>.private.json` (gitignored):
```json
{ "relay": { "resend_api_key": "re_..." } }
```

---

## 5. (Optional) Set up Hostinger SMTP (alternative sender)

If you have a Hostinger mailbox and want to send through it directly instead of Resend:

Create `sequences/hostinger.env` from `sequences/hostinger.env.example`:
```
SMTP_HOST=smtp.hostinger.com
SMTP_PORT=465
SMTP_USER=you@yourdomain.com
SMTP_PASS=<your app password>
FROM_NAME=Your Name
FROM_ADDR=you@yourdomain.com
```

Test:
```bash
py sequences/hostinger-smtp-send.py \
   --variants sequences/aureon-20-variants/variants.json \
   --variant-n 1 \
   --to <your-test-inbox>
```

---

## 6. Push your local state to Supabase

```bash
py sequences/supabase_sync.py push
py sequences/supabase_sync.py status
```

Expected: 1+ profiles, 20+ variants, plus any send history.

---

## 7. Send a test through Resend

```bash
py sequences/resend-pool-send.py <profile-slug> \
   --variants sequences/aureon-20-variants/variants.json \
   --variant-n 1 \
   --to <recipient-address>
```

If a `200 OK` comes back with a Resend message id, you're live.

---

## 8. Start the warmup ramp (optional but recommended)

```bash
py sequences/warmup-scheduler.py start <profile-slug>
```

Then schedule the daily tick (Windows example):
```powershell
schtasks /Create /TN "LES-warmup" `
  /TR "py C:\path\to\local-email-stack\sequences\warmup-scheduler.py tick" `
  /SC DAILY /ST 10:00
```

---

## 9. (Optional) Run the desktop app

```bash
cd desktop/frontend
npm install
npm run dev
```

In a second terminal:
```bash
cd desktop
.\Generate-Icon.ps1            # Windows only — generates icon.ico
.\Create-DesktopShortcut.ps1   # Windows only — adds shortcut
.\Launch-LocalEmailStack.ps1   # opens app in Edge app-mode against the dev server
```

Once running, open **Settings → Cross-PC sync** in the app and paste your
Supabase URL + anon key. The app now reads live state. Repeat on any other PC.

For a native `.exe` build (Tauri):
```bash
cd desktop/src-tauri
cargo tauri build
```
Produces `target/release/local-email-stack.exe` + an NSIS installer.

---

## 10. Recommended reading order

1. [`DELIVERABILITY.md`](./DELIVERABILITY.md) — the 95% playbook for inbox placement
2. [`ARCHITECTURE.md`](./ARCHITECTURE.md) — full system design
3. [`SOURCING_AND_NICHES.md`](./SOURCING_AND_NICHES.md) — 12-platform lead sourcing
4. [`WARMUP_PLAYBOOK.md`](./WARMUP_PLAYBOOK.md) — warmup mechanic + ramp curve
5. [`SENDER_INFRA.md`](./SENDER_INFRA.md) — self-hosted Postal alternative
6. [`SENDER_RELAY.md`](./SENDER_RELAY.md) — switching backends
7. [`DESKTOP_APP.md`](./DESKTOP_APP.md) — Tauri app build + transfer guide

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `supabase_sync.py` says "missing SUPABASE_URL" | `supabase.env` has UTF-8 BOM | Re-save the file as **UTF-8 without BOM**. |
| Resend send returns `401 restricted_api_key` | API key was created with "Sending access" | Create a new key with **Full access** for domain ops; the sending-only key works fine for `POST /emails` once a domain is verified. |
| `web.de` rejects with `Invalid DNS PTR` | Sending direct-to-MX from your home IP | Switch to Resend or any other relay. The PTR check fails on residential IPs. |
| `mx2.hostinger.com: timed out` after first send | Recipient MX rate-limited residential sender | Same fix as above. |
| Desktop app shows "Stack not connected" | Backend not running or no `supabase.env` | Either start the local Docker stack OR wire up Supabase as described above. |

---

## Costs

Recurring spend with all features enabled:

| Service | Tier | Cost |
|---|---|---|
| Supabase | Free | $0 |
| Resend | Free (100/day, 3000/mo) | $0 |
| Hostinger | Whatever plan hosts your domain | already paying |
| Domain | Yearly renewal | ~$10/yr amortized |

Total monthly recurring: **$0** for a personal-scale cold-email stack with cross-PC
state, automated warmup, multi-persona sending, and full deliverability infrastructure.
