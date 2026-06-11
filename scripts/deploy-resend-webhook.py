"""Deploy the Resend bounce webhook end-to-end via the Cloudflare API + Resend
API. ONE command, no dashboard clicking.

Needs (one-time, add to bootstrap.env or sequences/hostinger.env):
    CF_API_TOKEN     Cloudflare token with "Account > Workers Scripts > Edit"
                     (https://dash.cloudflare.com/profile/api-tokens)
    CF_ACCOUNT_ID    Cloudflare account id (dash URL or token page)

Uses values already in the repo:
    SUPABASE_URL + SUPABASE_ANON_KEY  (sequences/supabase.env) — the anon key can
        already PATCH send_log (all pipeline writes use it), so no service-role
        key needed.
    RESEND_FULL_ACCESS_API_KEY        (sequences/hostinger.env) — to register the
        Resend webhook.

Run:
    py scripts/deploy-resend-webhook.py
"""
import json, sys
from pathlib import Path
import httpx

REPO = Path(__file__).resolve().parent.parent
WORKER = REPO / "workers" / "resend-webhook.worker.js"
SCRIPT_NAME = "aureon-resend-webhook"
EVENTS = ["email.delivered", "email.bounced", "email.complained", "email.delivery_delayed"]

def load(*paths):
    d = {}
    for p in paths:
        fp = REPO / p
        if not fp.exists():
            continue
        for line in fp.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1); d[k.strip()] = v.strip().strip('"').strip("'")
    return d

env = load("bootstrap.env", "sequences/hostinger.env", "sequences/supabase.env")
CF_TOKEN = env.get("CF_API_TOKEN", "")
CF_ACCT = env.get("CF_ACCOUNT_ID", "")
SUPA_URL = env.get("SUPABASE_URL", "")
SUPA_KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY", "")
RESEND_KEY = env.get("RESEND_FULL_ACCESS_API_KEY", "")
WEBHOOK_SECRET = env.get("RESEND_WEBHOOK_SECRET", "")  # optional first run

missing = [n for n, v in [("CF_API_TOKEN", CF_TOKEN), ("CF_ACCOUNT_ID", CF_ACCT),
                          ("SUPABASE_URL", SUPA_URL), ("SUPABASE_ANON_KEY", SUPA_KEY)] if not v]
if missing:
    print("MISSING env values:", ", ".join(missing))
    print("Add CF_API_TOKEN + CF_ACCOUNT_ID to bootstrap.env, then re-run.")
    print("Token: https://dash.cloudflare.com/profile/api-tokens  (Account > Workers Scripts > Edit)")
    sys.exit(1)

cf = "https://api.cloudflare.com/client/v4"
hdr = {"Authorization": f"Bearer {CF_TOKEN}"}
code = WORKER.read_text(encoding="utf-8")

# 1. Upload the ES-module Worker with secret bindings baked in
metadata = {
    "main_module": "worker.js",
    "compatibility_date": "2024-11-01",
    "bindings": [
        {"type": "secret_text", "name": "SUPABASE_URL", "text": SUPA_URL},
        {"type": "secret_text", "name": "SUPABASE_SERVICE_KEY", "text": SUPA_KEY},
        {"type": "secret_text", "name": "RESEND_WEBHOOK_SECRET", "text": WEBHOOK_SECRET},
    ],
}
print(f"[1] uploading Worker '{SCRIPT_NAME}'...")
r = httpx.put(
    f"{cf}/accounts/{CF_ACCT}/workers/scripts/{SCRIPT_NAME}",
    headers=hdr,
    data={"metadata": json.dumps(metadata)},
    files={"worker.js": ("worker.js", code, "application/javascript+module")},
    timeout=40,
)
print("    ", r.status_code, r.text[:200])
if r.status_code not in (200, 201):
    sys.exit("Worker upload failed.")

# 2. Enable the workers.dev subdomain route
print("[2] enabling workers.dev route...")
httpx.post(f"{cf}/accounts/{CF_ACCT}/workers/scripts/{SCRIPT_NAME}/subdomain",
           headers=hdr, json={"enabled": True}, timeout=20)
# fetch the account's workers.dev subdomain
sub = httpx.get(f"{cf}/accounts/{CF_ACCT}/workers/subdomain", headers=hdr, timeout=20).json()
subdomain = (sub.get("result") or {}).get("subdomain", "")
worker_url = f"https://{SCRIPT_NAME}.{subdomain}.workers.dev" if subdomain else "(check dashboard)"
print("    Worker URL:", worker_url)

# 3. Register the Resend webhook (idempotent: skip once the secret is set, so a
#    re-run just re-uploads the Worker WITH the signing secret = verification on)
if WEBHOOK_SECRET:
    print("[3] RESEND_WEBHOOK_SECRET set — webhook already registered; Worker "
          "now has the secret, signature verification ENABLED.")
    print(f"\nDONE. Test:  curl {worker_url}")
    sys.exit(0)
print("[3] registering Resend webhook...")
try:
    rr = httpx.post("https://api.resend.com/webhooks",
                    headers={"Authorization": f"Bearer {RESEND_KEY}"},
                    json={"endpoint": worker_url, "events": EVENTS}, timeout=30)
    if rr.status_code in (200, 201):
        body = rr.json()
        print("    registered:", json.dumps(body)[:160])
        sec = body.get("signing_secret") or body.get("secret")
        if sec:
            print(f"\n[4] re-run with RESEND_WEBHOOK_SECRET={sec} in bootstrap.env to enable")
            print("    signature verification (worker accepts unsigned until then).")
    else:
        print(f"    Resend webhook API HTTP {rr.status_code} — add it in the Resend")
        print(f"    dashboard instead: endpoint={worker_url}  events={EVENTS}")
except Exception as e:
    print("    resend webhook error:", e)

print(f"\nDONE. Test:  curl {worker_url}")
