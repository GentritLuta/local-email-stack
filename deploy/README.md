# Deploying local-email-stack to a VPS

The Windows laptop setup uses Task Scheduler. The VPS setup uses Linux cron
inside Docker. Same Python code, same Resend / Supabase backends, same
profiles + niches — only the scheduler changes.

## Recommended VPS spec

| Resource | Why |
|---|---|
| 2 CPU / 4 GB RAM | Playwright (Chromium headless) for lead_scrape needs ~1 GB during a run. Cron jobs are cheap when idle. |
| 20 GB disk | Code + Chromium + state. Send logs live in Supabase, not on disk. |
| Static IP (any region) | Resend handles all outbound sending; the VPS IP doesn't touch recipient inboxes. Pick what's cheap. |
| Ubuntu 22.04+ or Debian 12+ | Anything with Docker engine ≥24. |

Hetzner CX21 (~€5/mo) or DigitalOcean Basic ($6/mo) is enough.

## One-time setup

```bash
# On your laptop, push to a private repo (or rsync the directory).
# Then on the VPS:

sudo apt-get update && sudo apt-get install -y docker.io docker-compose-plugin git
sudo systemctl enable --now docker
sudo usermod -aG docker $USER && newgrp docker

git clone git@github.com:youraccount/local-email-stack.git ~/les
cd ~/les

# Place the three env files (gitignored on the host repo) under deploy/secrets/
mkdir -p deploy/secrets
cp /path/to/laptop/sequences/supabase.env  deploy/secrets/
cp /path/to/laptop/sequences/hostinger.env deploy/secrets/
cp /path/to/laptop/sequences/youtube.env   deploy/secrets/

cd deploy
docker compose up -d --build
```

That's it. Cron runs inside the container; the watchdog runs hourly inside
the same container; nothing on the VPS host needs to know about the
schedule.

## What you give up moving to a VPS

| Lost | Workaround |
|---|---|
| Keep-awake daemon | Not needed — Linux servers don't sleep |
| WakeToRun task hardening | Not needed — same reason |
| Windows Task Scheduler GUI | Use `crontab -l` inside the container instead |
| Hostinger MCP browser automation | Not needed at runtime — DNS already provisioned |

## Day-to-day commands

```bash
# Tail the cron log
docker compose logs -f les
docker compose exec les tail -f /app/warmup-state/cron.log

# Run a one-shot task interactively (e.g. force pool-monitor)
docker compose exec les python scripts/pool-monitor.py

# Watchdog ad-hoc
docker compose exec les python scripts/watchdog.py

# Update code: rsync the repo, then
docker compose up -d --build

# Edit profile JSON live (no restart needed)
vim profiles/aureon.json
```

## Migration from Windows laptop

When ready to cut over:

1. **Pause the laptop**: open Task Scheduler, disable all `LES-*` tasks.
2. **Sync state once**: `rsync -av warmup-state/ vps:~/les/warmup-state/` (so day counters carry over).
3. **Sync profiles**: `rsync -av profiles/ vps:~/les/profiles/` (in case any local edits).
4. **Bring VPS up**: `cd ~/les/deploy && docker compose up -d --build`.
5. **Verify a tick fires**: `docker compose exec les python sequences/sequence-runner.py tick`.
6. **Watch first day**: `tail -f` the cron log; confirm send_log starts populating from VPS sends.
7. **Decommission the laptop**: leave LES tasks disabled. The laptop can sleep freely.

## Watchdog over MX

The Resend webhook for bounce/complaint events should be repointed at the
VPS's public IP if you want push-based reconciliation. Until then, the
hourly poll-based `resend-status-reconcile.py` covers it.

## DNS push from the VPS

`provision_subdomain.py` already takes a `HOSTINGER_API_TOKEN` from the
env file. As long as `deploy/secrets/hostinger.env` is mounted, you can
provision new subdomains from the VPS exactly like on the laptop:

```bash
docker compose exec les python sequences/provision_subdomain.py add aureon foo.aureonglobal.de
```

## Cost & resource ceiling

At today's send volume (~150/day across 4 profiles), a CX21 sits at ~5% CPU
and 200 MB RAM. The bottleneck if you 10× volume will be Chromium launches
during lead_scrape — switch to longer-spread daily-fill-and-enroll passes
or pool-monitor schedule before upgrading the VPS.
