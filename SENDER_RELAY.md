# Sender Relay — how to make emails actually land in the inbox

The default direct-to-MX path from a residential IP (no SPF/DKIM/DMARC) lands in spam folders or gets rate-limited mid-sequence — exactly what happened with the algoalpha → aureonglobal test (1 of 10 delivered, then `mx2.hostinger.com` froze us out).

To fix inbox placement, send through a **sender relay** that has clean IPs and handles DKIM signing for you. Three real paths, ordered by setup time.

---

## Path 1 — Resend free tier (fastest, ~5 min)

**Result:** All 10 emails reach the inbox at any major provider (Gmail, Workspace, Outlook, Hostinger). Resend handles the IP reputation; you handle the domain.

**Steps:**

1. **Sign up** at <https://resend.com> (free, no credit card, no phone).
2. **Add your sending domain** (the one in `From:`). For the algoalpha test, that's `algoalpha.io` — but you only have authority over `insaneaiautomation.xyz`, so use a subdomain there: e.g. `mail.insaneaiautomation.xyz`, and update `sequence.json`'s `sender.from_addr` to `tomas@mail.insaneaiautomation.xyz`.
3. Resend generates 3 DNS records (SPF TXT, DKIM CNAME or TXT, MX). Paste them into Cloudflare DNS.
4. Wait ~5 min for verification.
5. **Create an API key** (Dashboard → API Keys → Create).
6. In the LocalEmailStack app: **Settings → Sender → Resend** → paste the key → **Save**.
7. Click **Download relay.env** → drop the file into `sequences/`.
8. In PowerShell:
   ```powershell
   py sequences\relay-send.py sequences\algoalpha-aureon-2026-05-17\sequence.json --backend resend --resume-from 2
   ```
9. Done — emails 2–10 go through Resend's clean infrastructure, with `mail.insaneaiautomation.xyz` properly authenticated.

**Free tier limits:** 100 emails/day, 3,000/month — plenty for cold sequences.

**TOS note:** Resend permits "transactional and marketing emails to opt-in recipients." For a sequence to your own test inbox (`info@aureonglobal.de` if you own Aureon), this is squarely transactional. For cold outreach to non-opted-in recipients at scale, you should move to Path 3 (Postal self-host) eventually.

---

## Path 2 — Your existing Gmail / Outlook account (~2 min, no domain setup)

**Result:** Emails go through Gmail's or Outlook's SMTP relay. Inbox placement is excellent at most domains because Gmail/MS have stellar IP reputation. `From:` will be your personal email, not `tomas@algoalpha.io`.

**Trade-off:** the recipient sees mail from your personal Gmail/Outlook, not your company domain. Good for ~500 sends/day.

**Steps (Gmail):**

1. Enable 2-Step Verification on your Google account if you haven't.
2. Go to <https://myaccount.google.com/apppasswords>.
3. Create an App Password named "LocalEmailStack". Copy the 16-character password.
4. In the app: **Settings → Sender → SMTP relay**:
   - Host: `smtp.gmail.com`
   - Port: `587`
   - User: `you@gmail.com`
   - Password: <paste the App Password>
   - Update **From address** to `you@gmail.com` (must match the authenticated user for Gmail).
5. **Save** → **Download relay.env** → drop in `sequences/`.
6. PowerShell:
   ```powershell
   py sequences\relay-send.py sequences\algoalpha-aureon-2026-05-17\sequence.json --backend smtp --resume-from 2
   ```

**For Outlook:** same flow, but Host = `smtp-mail.outlook.com`, app password at <https://account.microsoft.com/security>.

**Daily limit:** Gmail allows ~500 cold sends/day from a personal account before rate-limiting; Workspace allows ~2,000. Beyond that, switch to Path 1 or 3.

---

## Path 3 — Self-hosted Postal on Oracle Free Tier (~2 hr setup, $0/mo forever)

**Result:** Fully self-hosted, $0/mo recurring, designed for cold-email scale. This is the architecture this whole stack was built for — see [`SENDER_INFRA.md`](./SENDER_INFRA.md) and [`WARMUP_PLAYBOOK.md`](./WARMUP_PLAYBOOK.md).

Once provisioned: every send goes through Postal on a clean Oracle Cloud IP with proper DKIM signing, after a 4–6 week warmup. Inbox placement is comparable to Resend at zero ongoing cost.

**Use this when:** you've decided cold email is a permanent operation and the 2-hour setup pays off vs $0–10/mo recurring elsewhere.

---

## Why the original send failed (root cause, plain English)

The 10 emails to `info@aureonglobal.de` left this Windows machine and tried to connect directly to Hostinger's mail servers (the MX for aureonglobal.de). Hostinger's anti-spam logic looked at the connection and saw:

- **Sending IP:** a residential subnet (your home ISP). Residential ranges are on Spamhaus PBL by default.
- **No SPF:** the IP wasn't listed as authorized to send for `algoalpha.io` (because we don't control that domain's DNS).
- **No DKIM signature:** the mail had no cryptographic proof of origin.
- **No DMARC alignment:** From: claimed `tomas@algoalpha.io` but had no way to prove it.

The first email got a "let's see if this turns into abuse" pass — it was accepted, almost certainly to spam. After that, mx2 silently dropped further connections for ~30 minutes (a standard "tarpit" defense). The other 9 emails timed out.

All three relay paths above fix this by routing your mail through an IP that's **authorized** to send for your domain, **cryptographically signs** it, and has **good reputation history** with Gmail/Outlook/Workspace. None of those properties exist when you send direct from a home IP.

---

## After the relay send: how to verify inbox placement

1. Send the test sequence through any of the three paths.
2. Open `info@aureonglobal.de` (the test inbox). Check **Inbox** first, then **Spam**.
3. If it's in inbox, the relay is working. If in spam, the **domain reputation is still warming up** — let it sit 24 hours and try again. The Resend / SMTP-relay routes mostly avoid this; Postal self-host requires the documented 4–6 week warmup.
4. Reply to any email from the test inbox → reply lands at your Reply-To address → in the LocalEmailStack app, the **Replies** view will populate (once the Cloudflare Email Worker is deployed), and the **Sequences** view will mark the sequence as paused.
