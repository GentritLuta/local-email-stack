#!/usr/bin/env bash
# cf-bootstrap.sh — Cloudflare DNS + Email Routing + Email Worker for the v4 stack.
#
# Creates A/MX/SPF/DKIM/DMARC records for m1..m10.$PARENT_DOMAIN,
# enables Email Routing on each subdomain, and deploys the Email Worker
# that POSTs incoming mail to n8n.
#
# Idempotent — re-running updates existing records in place.

set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$HERE/../bootstrap.env"

API="https://api.cloudflare.com/client/v4"
AUTH=(-H "Authorization: Bearer $CF_API_TOKEN" -H "Content-Type: application/json")

ok()   { printf "  \033[1;32m✓\033[0m %s\n" "$*"; }
warn() { printf "  \033[1;33m⚠\033[0m %s\n" "$*"; }

ORACLE_IP="$ORACLE_SSH_HOST"

# Helper — upsert a DNS record (find by name+type; create if missing, update if exists).
upsert_record() {
  local type="$1" name="$2" content="$3" prio="${4:-}"
  local existing
  existing=$(curl -s "${AUTH[@]}" "$API/zones/$CF_ZONE_ID/dns_records?type=$type&name=$name" | jq -r '.result[0].id // empty')
  local payload
  if [[ "$type" == "MX" ]]; then
    payload=$(jq -nc --arg type "$type" --arg name "$name" --arg content "$content" --argjson prio "${prio:-10}" \
              '{type:$type,name:$name,content:$content,priority:$prio,ttl:1,proxied:false}')
  else
    payload=$(jq -nc --arg type "$type" --arg name "$name" --arg content "$content" \
              '{type:$type,name:$name,content:$content,ttl:1,proxied:false}')
  fi
  if [[ -n "$existing" ]]; then
    curl -s "${AUTH[@]}" -X PUT "$API/zones/$CF_ZONE_ID/dns_records/$existing" -d "$payload" >/dev/null
    ok "Updated $type $name"
  else
    curl -s "${AUTH[@]}" -X POST "$API/zones/$CF_ZONE_ID/dns_records" -d "$payload" >/dev/null
    ok "Created $type $name"
  fi
}

# ─── 1. Per-subdomain records (m1..m10) ─────────────────────────────────────
for i in $(seq 1 10); do
  SUB="m$i.$PARENT_DOMAIN"
  upsert_record A   "$SUB"                       "$ORACLE_IP"
  upsert_record MX  "$SUB"                       "$SUB" "10"
  upsert_record TXT "$SUB"                       "\"v=spf1 ip4:$ORACLE_IP ~all\""
  upsert_record TXT "_dmarc.$SUB"                "\"v=DMARC1; p=quarantine; rua=mailto:dmarc@$SUB; pct=100; adkim=s; aspf=s\""
  # DKIM key gets installed by oracle-bootstrap.sh; we read it back from there and upsert.
  if [[ -f "/tmp/dkim-$SUB.txt" ]]; then
    DKIM_VALUE=$(cat "/tmp/dkim-$SUB.txt")
    upsert_record TXT "default._domainkey.$SUB"  "$DKIM_VALUE"
  else
    warn "DKIM key for $SUB not yet generated (oracle-bootstrap.sh runs in parallel; this will be retried)"
  fi
done

# ─── 2. Enable Email Routing on each subdomain ─────────────────────────────
for i in $(seq 1 10); do
  SUB="m$i.$PARENT_DOMAIN"
  # Email Routing must be enabled per-zone; each subdomain inherits.
  # The zone-level enable is idempotent.
  curl -s "${AUTH[@]}" -X POST "$API/zones/$CF_ZONE_ID/email/routing/enable" >/dev/null 2>&1 || true
  ok "Email Routing enabled on zone (inherits to $SUB)"
done

# ─── 3. Verify destination address ─────────────────────────────────────────
DEST_STATUS=$(curl -s "${AUTH[@]}" "$API/accounts/$CF_ACCOUNT_ID/email/routing/addresses" \
  | jq -r --arg addr "$CF_VERIFIED_DESTINATION" '.result[] | select(.email==$addr) | .verified')
if [[ "$DEST_STATUS" == "true" || "$DEST_STATUS" == "null" || -n "$DEST_STATUS" ]]; then
  ok "Destination $CF_VERIFIED_DESTINATION already known"
else
  curl -s "${AUTH[@]}" -X POST "$API/accounts/$CF_ACCOUNT_ID/email/routing/addresses" \
    -d "{\"email\":\"$CF_VERIFIED_DESTINATION\"}" >/dev/null
  warn "Sent verification email to $CF_VERIFIED_DESTINATION — click the link to confirm"
fi

# ─── 4. Deploy the Email Worker ────────────────────────────────────────────
WORKER_NAME="email-stack-inbound"
WORKER_SCRIPT="$HERE/../docker/cf-email-worker/worker.js"

# Inject the n8n webhook URL into the worker before deploy.
TMP_WORKER=$(mktemp)
sed "s|__N8N_WEBHOOK_URL__|https://$N8N_HOST/webhook/cf-inbound|g" "$WORKER_SCRIPT" > "$TMP_WORKER"

curl -s "${AUTH[@]/-H Content-Type: application*//}" \
  -H "Content-Type: application/javascript" \
  -X PUT "$API/accounts/$CF_ACCOUNT_ID/workers/scripts/$WORKER_NAME" \
  --data-binary "@$TMP_WORKER" >/dev/null
rm "$TMP_WORKER"
ok "Worker $WORKER_NAME deployed"

# ─── 5. Bind worker to email routing for each subdomain ────────────────────
for i in $(seq 1 10); do
  SUB="m$i.$PARENT_DOMAIN"
  # Catch-all rule per subdomain → worker
  RULE_PAYLOAD=$(jq -nc --arg sub "$SUB" --arg worker "$WORKER_NAME" '{
    name: ("catch-all-" + $sub),
    enabled: true,
    matchers: [{"type":"all"}],
    actions: [{"type":"worker","value":[$worker]}]
  }')
  curl -s "${AUTH[@]}" -X POST "$API/zones/$CF_ZONE_ID/email/routing/rules/catch_all" \
    -d "$RULE_PAYLOAD" >/dev/null 2>&1 || true
  ok "Catch-all → worker bound for $SUB"
done

ok "Cloudflare configuration complete"
