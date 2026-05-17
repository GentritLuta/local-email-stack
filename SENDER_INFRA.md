# Sender Infrastructure — Oracle Cloud Always-Free + Postal

The one off-box piece of the $0/mo stack. This document is the bring-up runbook.

---

## 1. Why this needs to live off-box

Residential ISPs block port 25 outbound (every major one — Comcast, Spectrum, AT&T, Vodafone, Deutsche Telekom, BT, etc.). Even when they don't, residential IP ranges are on every blocklist that matters (Spamhaus PBL, etc.) by default.

The fix is a small VPS with:
- Clean IP not on any blocklist.
- Port 25 in/out actually working.
- Static IP that can have rDNS set.
- Always-on so DKIM signing and reply IMAP keep working.

Oracle Cloud Always-Free gives all of this. Forever-free, no charge unless you opt in to paid tiers.

---

## 2. Oracle account + VM provisioning

### 2.1 Sign up
- https://signup.oraclecloud.com/
- Account name: anything personal.
- Home region: pick the one geographically closest with capacity (some regions are perpetually full for Always-Free ARM). Recommended: **Frankfurt, London, Phoenix, San Jose, Mumbai, Tokyo**.
- Credit card required for verification. **You will not be charged** unless you upgrade. Set up a payment alert ($0.01 threshold) for paranoia.

### 2.2 Create the always-free ARM VM
- Compute → Instances → Create Instance.
- Name: `postal-mail`
- Image: **Canonical Ubuntu 22.04** (ARM build).
- Shape: **VM.Standard.A1.Flex**, 4 OCPU / 24 GB RAM (the full free allocation).
- Networking: Public IPv4 attached. Note the **public IP**.
- SSH keys: paste your public key.
- Boot volume: 200 GB (the full free allocation; only Postal + warmup mailboxes will live here).

> **Capacity gotcha:** "Out of capacity for shape" is common in some regions. Re-try every 30–60 minutes; capacity opens up. Or use the `oci-capacity-checker` script.

---

## 3. Get port 25 unblocked

Oracle Always-Free blocks port 25 outbound by default. They unblock it on request for personal mail servers.

### 3.1 Submit the request
- My Oracle Support → Create Service Request.
- Service Type: "Cloud Infrastructure"
- Problem Type: "Networking" → "Outbound Port 25 Block"
- Body template:

> Subject: Request to unblock outbound port 25 for personal mail server
>
> Hello,
>
> I would like to request that outbound port 25 be unblocked on my Always Free tenancy for the following compartment / region / IP:
>
> Tenancy: <name>
> Region: <e.g. eu-frankfurt-1>
> Compartment: <name>
> Instance: postal-mail
> Public IP: <a.b.c.d>
>
> Purpose: personal email automation for my own domain (insaneaiautomation.xyz). I will be running Postal MTA with full SPF/DKIM/DMARC configured. I will not send unsolicited bulk mail.
>
> Thank you.

Approval is usually 24–72 hours. **Submit this on day one** so it's done by the time you finish the rest of the bring-up.

### 3.2 What if they deny it
Some recent reports indicate Oracle has tightened approvals. If denied:
- **Plan B:** Hetzner CX11 (€4.51/mo) — same shape of VM, port 25 works out of the box, clean IPs. This breaks the $0/mo promise by less than the cost of a coffee. Document why you accepted the trade-off in the project README.
- **Plan C:** Use a free smarthost relay (Brevo free 300/day, MailerSend 3000/mo) as the SMTP backend instead of Postal. Strictly $0 but watch their TOS — most prohibit cold outbound, so this is only viable for transactional/warm follow-ups, not the main pipeline.

---

## 4. VM hardening

```bash
ssh ubuntu@<oracle-public-ip>

# Updates
sudo apt update && sudo apt full-upgrade -y && sudo apt autoremove -y

# Firewall — only what we need
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp       # SSH
sudo ufw allow 25/tcp       # SMTP
sudo ufw allow 587/tcp      # Submission (for n8n → Postal)
sudo ufw allow 993/tcp      # IMAPS (for n8n IMAP triggers)
sudo ufw allow 443/tcp      # Postal admin UI behind Caddy
sudo ufw enable

# Oracle has its own security list in the console — open the same ports there too:
#   25, 587, 993, 443, 22

# fail2ban
sudo apt install -y fail2ban
sudo systemctl enable --now fail2ban

# Unattended security updates
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure --priority=low unattended-upgrades
```

---

## 5. Install Postal

Postal has a Docker compose deployment that's the simplest path.

```bash
sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker ubuntu
newgrp docker

git clone https://github.com/postalserver/install
cd install/examples/docker
cp postal.yml.example postal.yml
# Edit postal.yml:
#   - postal.web_hostname → postal.insaneaiautomation.xyz
#   - postal.smtp_hostname → m.insaneaiautomation.xyz (any sender subdomain works as HELO)
#   - dns.mx_records → [postal.insaneaiautomation.xyz]
#   - dns.spf_include → spf.insaneaiautomation.xyz (the actual SPF record will reference the Oracle IP)

docker compose up -d
```

Postal exposes a web UI on `postal.insaneaiautomation.xyz` (front it with Caddy + Let's Encrypt for HTTPS).

### 5.1 Create the organization + servers in Postal
- Log in to the Postal UI.
- New Organization → "Cold Email Stack".
- For each sending subdomain `m1..m10`:
  - New Mail Server inside the org → name "m1", domain "m1.insaneaiautomation.xyz".
  - Postal generates the DKIM key — copy it.
  - Set the DNS records Postal tells you to (MX, SPF, DKIM TXT, DMARC). Verify with the "Check DNS" button in the UI.

### 5.2 Bounce + DMARC handling
- Each Postal mail server has a "Webhook" tab — point bounce webhooks at `https://n8n.your-tunnel.tld/webhook/postal-bounce`.
- For DMARC reports: set `dmarc@m1.insaneaiautomation.xyz` etc. as the `rua` address. Postal parses incoming DMARC aggregate reports and writes them to its DB; an n8n cron pulls and surfaces in Grafana.

---

## 6. Tailscale tunnel back to home server

Postal listens for outbound submissions on port 587. n8n on the home server submits messages to Postal at `oracle.tailnet:587`. The submission stays inside the encrypted tailnet — no public exposure of port 587.

On the Oracle VM:
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up --auth-key=tskey-auth-... --hostname=postal-mail
```

On the home server (already in the compose):
```bash
docker compose up -d tailscale
docker exec tailscale tailscale status
```

In n8n, configure SMTP credential:
- Host: `postal-mail` (Tailscale MagicDNS resolves it)
- Port: 587
- User/pass: from Postal credentials page
- TLS: STARTTLS

---

## 7. DNS for all sender subdomains

For each of `m1..m10`:

| Record | Type | Value |
|---|---|---|
| `m1` | A | <Oracle public IP> |
| `m1` | MX | 10 m1.insaneaiautomation.xyz |
| `m1` | TXT (SPF) | `v=spf1 ip4:<Oracle IP> ~all` |
| `default._domainkey.m1` | TXT | `v=DKIM1; k=rsa; p=<from Postal>` |
| `_dmarc.m1` | TXT | `v=DMARC1; p=quarantine; rua=mailto:dmarc@m1.insaneaiautomation.xyz; pct=100` |

For the parent `insaneaiautomation.xyz`, no changes required.

**rDNS (PTR record):** set in Oracle console → Networking → Public IPs → your IP → Edit → Hostname → `m.insaneaiautomation.xyz` (use one canonical HELO name even though multiple subdomains send via this IP).

**Verification:** for each subdomain, send a test to `test@mail-tester.com` from `warmup-mN@mN…`. Required score: 9.0+/10. Lower means a DNS record is wrong or rDNS isn't propagated.

---

## 8. Bring-up checklist

- [ ] Oracle account created, ARM VM running.
- [ ] Port 25 unblock request submitted.
- [ ] Postal installed, web UI reachable.
- [ ] Tailscale up on both ends, `tailscale ping postal-mail` from home server succeeds.
- [ ] 10 sender subdomains in DNS with SPF/DKIM/DMARC + rDNS set.
- [ ] mail-tester.com 9.0+/10 for each subdomain.
- [ ] 10 warmup mailboxes provisioned in Postal.
- [ ] n8n SMTP credential configured against `postal-mail:587` via Tailscale.
- [ ] n8n bounce-webhook endpoint receiving Postal POSTs.
- [ ] `WARMUP_PLAYBOOK.md` ramp started.

After 4–6 weeks of clean warmup, this stack is production-ready for ~150 cold sends/day per subdomain (1,500/day total on a 10-subdomain mesh) at $0/mo.
