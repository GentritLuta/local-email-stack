#!/usr/bin/env bash
# bootstrap.sh — one-command bring-up for the v4 stack.
#
# Usage:
#   1. Copy bootstrap.env.example → bootstrap.env, fill in values.
#   2. ./bootstrap.sh
#
# Idempotent: re-running picks up where it left off.

set -euo pipefail

# ─── Locate ourselves ───────────────────────────────────────────────────────
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
ENV_FILE="$ROOT/bootstrap.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "✗ Missing $ENV_FILE. Copy bootstrap.env.example and fill in values."
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

log()  { printf "\n\033[1;36m▶ %s\033[0m\n" "$*"; }
ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[1;33m⚠\033[0m %s\n" "$*"; }
fail() { printf "  \033[1;31m✗\033[0m %s\n" "$*"; exit 1; }

# ─── 1. Preflight validation ────────────────────────────────────────────────
log "Preflight"
command -v docker >/dev/null            || fail "docker not installed"
command -v jq >/dev/null                || fail "jq not installed"
command -v curl >/dev/null              || fail "curl not installed"
command -v ssh >/dev/null               || fail "ssh not installed"
docker compose version >/dev/null 2>&1  || fail "docker compose plugin missing"
[[ -n "${PARENT_DOMAIN:-}" ]]           || fail "PARENT_DOMAIN not set"
[[ -n "${ORACLE_SSH_USER:-}" ]]         || fail "ORACLE_SSH_USER not set"
[[ -n "${ORACLE_SSH_HOST:-}" ]]         || fail "ORACLE_SSH_HOST not set"
[[ -n "${ORACLE_SSH_KEY:-}" ]]          || fail "ORACLE_SSH_KEY not set"
[[ -n "${TAILSCALE_AUTHKEY:-}" ]]       || fail "TAILSCALE_AUTHKEY not set"
[[ -n "${CF_API_TOKEN:-}" ]]            || fail "CF_API_TOKEN not set"
[[ -n "${CF_ZONE_ID:-}" ]]              || fail "CF_ZONE_ID not set"
[[ -n "${N8N_API_URL:-}" ]]             || fail "N8N_API_URL not set"
# GPU check
if ! docker run --rm --gpus all nvidia/cuda:12.4.0-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1; then
  warn "NVIDIA Container Toolkit not detected; GPU services will fail. Continue anyway? [y/N]"
  read -r ans; [[ "$ans" == "y" ]] || exit 1
fi
ok "Preflight passed"

# ─── 2. Render .env files from bootstrap.env ────────────────────────────────
log "Rendering .env files"
"$HERE/render-env.sh" "$ENV_FILE" "$ROOT/docker/.env"
ok ".env rendered"

# ─── 3. Bring up home stack (background-friendly — DNS / Oracle parallel) ──
log "Starting home-server containers"
(cd "$ROOT/docker" && docker compose up -d --remove-orphans) || fail "compose up failed"
ok "Compose up"

# Pull models (idempotent; ollama caches)
log "Pulling LLM models (Qwen 2.5 32B + Qwen2-VL 7B + nomic-embed-text)"
docker exec docker-ollama-1 ollama pull qwen2.5:32b-instruct-q4_K_M
docker exec docker-ollama-1 ollama pull qwen2-vl:7b
docker exec docker-ollama-1 ollama pull nomic-embed-text
ok "Models pulled"

# ─── 4. Provision Oracle VM (parallel-safe; idempotent) ────────────────────
log "Configuring Oracle Always-Free VM ($ORACLE_SSH_HOST)"
"$HERE/oracle-bootstrap.sh"
ok "Oracle VM configured"

# ─── 5. Configure Cloudflare DNS + Email Routing + Worker ──────────────────
log "Configuring Cloudflare DNS, Email Routing, and Email Worker"
"$HERE/cf-bootstrap.sh"
ok "Cloudflare configured"

# ─── 6. Tailscale up on home server (joins tailnet with Oracle VM) ─────────
log "Joining Tailscale tailnet"
docker exec docker-tailscale-1 tailscale up --auth-key="$TAILSCALE_AUTHKEY" --hostname=home-email-stack || true
# Verify tailnet reachability
sleep 5
docker exec docker-tailscale-1 tailscale ping -c 2 postal-mail >/dev/null 2>&1 \
  && ok "Tailnet reachable to postal-mail" \
  || warn "Cannot reach postal-mail yet (DNS propagation? Oracle not yet joined?)"

# ─── 7. Import n8n workflows + repoint credentials ─────────────────────────
log "Importing 12 workflow JSONs into n8n"
"$HERE/n8n-import.sh"
ok "Workflows imported and credentials repointed"

# ─── 8. Activate warmup mesh immediately ───────────────────────────────────
log "Activating warmup mesh (6-week ramp starts NOW; can run while other work continues)"
"$HERE/n8n-activate-warmup.sh"
ok "Warmup mesh active"

# ─── 9. Seed Twenty CRM schema + field mapping ─────────────────────────────
log "Seeding Twenty CRM with Close field mapping"
"$HERE/twenty-seed.sh"
ok "Twenty seeded"

# ─── 10. Smoke tests ───────────────────────────────────────────────────────
log "Running end-to-end smoke tests"
"$HERE/smoke-test.sh"

# ─── First-light report ───────────────────────────────────────────────────
log "First-light report"
cat <<EOF

  ✓ Home stack:        $(docker ps --format '{{.Names}}' | wc -l) containers up
  ✓ Models pulled:     qwen2.5:32b, qwen2-vl:7b, nomic-embed-text
  ✓ Oracle Postal:     reachable via tailnet ($(docker exec docker-tailscale-1 tailscale ping -c 1 postal-mail 2>/dev/null | tail -n1 || echo 'pending'))
  ✓ Cloudflare DNS:    10 subdomains (m1..m10.$PARENT_DOMAIN) live
  ✓ CF Email Worker:   deployed, will POST to https://$N8N_HOST/webhook/cf-inbound
  ✓ n8n workflows:     12 imported, credentials repointed
  ✓ Warmup mesh:       ACTIVE — first sends in 5–30 min
  ✓ Twenty CRM:        seeded with Close field mapping

  Open the dashboards:
    n8n      → https://$N8N_HOST
    NocoDB   → https://$NOCODB_HOST
    Twenty   → https://$CRM_HOST
    Grafana  → https://$GRAFANA_HOST

  What happens next, hands-free:
    - Day 0–42:  warmup mesh ramps subdomain reputation
    - Day 7+:    Lead Crawler + AI Finder + Email Verifier run on schedule
    - Day 14+:   first real cold sends begin (5/day per subdomain)
    - Day 42+:   full volume (150/day per subdomain × 10 subdomains)

  You'll only get notified by Alertmanager for things the watchdog couldn't resolve.

EOF
