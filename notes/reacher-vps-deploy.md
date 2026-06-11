# Reacher self-host deploy kit (Diraya verification)

What this is: a step-by-step to stand up your own **Reacher** backend (the
open-source `check-if-email-exists` engine) on a VPS, so `scripts/reacher_verify.py`
can verify guessed founder emails before Diraya sends to them.

Read this honestly before spending a cent: **Reacher cannot verify the ~85% of the
Diraya audience hosted on Google Workspace.** Google answers "yes" to every probe
(accept-all) by design, so Reacher returns `risky/unknown` for them, same as our own
SMTP prober. Reacher only gives clean `safe`/`invalid` verdicts on the **non-Google
slice** (self-hosted, Microsoft-with-leaky-config, some cPanel/Zoho). For the YC
seed-AI niche that slice is roughly **1 in 7 domains**. So this VPS pays off ONLY if
Diraya's audience is re-aimed toward verifiable (non-Google) targets. It is not a way
to crack the Google audience. Nothing is.

---

## 1. Pick a VPS where port 25 OUTBOUND is open

This is the whole game. Most hosts block outbound port 25 to stop spam, and Reacher
needs it to talk to mail servers.

- **Do NOT use Hostinger** — it blocks outbound 25 and will not unblock it for this.
  (Your connected Hostinger account is therefore the wrong tool here.)
- Providers that commonly allow 25 or unblock on request after a short account
  history: Hetzner (unblocks via support ticket once the account looks legit), OVH,
  Contabo, Scaleway. AWS/GCP/Azure/DigitalOcean block 25 and rarely unblock — avoid.
- Smallest box is fine: 1 vCPU / 1-2 GB RAM, any Ubuntu 22.04/24.04 LTS. ~5 EUR/mo.

After provisioning, confirm port 25 actually works from the box:
```
nc -vz alt1.gmail-smtp-in.l.google.com 25     # must connect, not hang
```
If it hangs, open a support ticket asking to unblock outbound SMTP (port 25); say you
run a legitimate double-opt-in mailing operation and need email validation. If they
refuse, the box is useless for this — stop and try another host.

## 2. Install Docker

```
curl -fsSL https://get.docker.com | sh
```

## 3. Run the Reacher backend

```
docker run -d --name reacher --restart unless-stopped -p 8080:8080 \
  -e RUST_LOG=info \
  -e RCH_HELLO_NAME=mail.aureonglobal.de \
  -e RCH_FROM_EMAIL=verify@aureonglobal.de \
  reacherhq/backend:latest
```
`RCH_HELLO_NAME` / `RCH_FROM_EMAIL` should use a domain you control with sane SPF, so
mail servers trust the probe. Check it is up:
```
curl -s -X POST http://localhost:8080/v0/check_email \
  -H 'content-type: application/json' \
  -d '{"to_email":"someone@a-non-google-domain.com"}' | head
```

## 4. Lock it down

Only YOU should reach the API. Either bind it to localhost and SSH-tunnel, or firewall
8080 to your IP:
```
ufw allow from <YOUR_IP> to any port 8080 proto tcp
ufw allow 22/tcp && ufw enable
```
(Reacher's backend has no auth by default. Never expose 8080 to the open internet.)

## 5. Verify a batch from your machine

```
py scripts/reacher_verify.py --backend http://VPS_IP:8080 --in out/diraya_guesses.csv \
   --out out/diraya_verified.csv --workers 4
```
Keep only `safe` (add `--keep-catch-all` to also keep risky-but-catch-all, which will
not hard-bounce). Import the survivors to Diraya exactly like the published leads.

## Slow down to stay unblocked
Hammering port 25 gets the VPS IP blocklisted fast. Keep `--workers` at 3-4, expect a
few hundred checks/day, and spread them out. This is a trickle tool, not a firehose.

---

## The honest bottom line
- This verifies the **non-Google** slice only. Pair it with re-aiming Diraya's audience
  at verifiable targets, or it checks ~1 in 7 and the rest still come back `unknown`.
- It needs a **port-25 VPS you buy and I cannot purchase for you**, and the unblock is
  not guaranteed.
- For a published-email audience (Diraya's current zero-bounce model) you do not need
  this at all — there is nothing to verify, because the address is already public.
