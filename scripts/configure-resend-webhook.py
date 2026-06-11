"""Configure the Resend -> Cloudflare webhook once the Worker is deployed.

Usage:
    py scripts/configure-resend-webhook.py https://aureon-resend-webhook.<acct>.workers.dev

Steps it does:
  1. GET the Worker URL to confirm it is live.
  2. Try to create the webhook via the Resend API (POST /webhooks) subscribed
     to email.delivered / email.bounced / email.complained / email.delivery_delayed.
  3. If the API path is not available, print exact dashboard instructions.
"""
import sys, json, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
host = {}
for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); host[k.strip()] = v.strip().strip('"').strip("'")
RK = host.get("RESEND_FULL_ACCESS_API_KEY", "")
UA = "local-email-stack/1.0"
EVENTS = ["email.delivered", "email.bounced", "email.complained", "email.delivery_delayed"]

if len(sys.argv) < 2:
    print("usage: py scripts/configure-resend-webhook.py <worker_url>"); sys.exit(2)
url = sys.argv[1].rstrip("/")

# 1. confirm worker is live
try:
    r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15)
    body = r.read().decode()[:60]
    print(f"[1] Worker is live: GET {url} -> {body!r}")
except Exception as e:
    print(f"[1] Worker not reachable at {url}: {e}\n    Deploy it first (workers/resend-webhook.worker.js)."); sys.exit(1)

# 2. try Resend webhook API
print("[2] Creating Resend webhook via API...")
payload = {"endpoint": url, "events": EVENTS}
req = urllib.request.Request("https://api.resend.com/webhooks",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {RK}", "Content-Type": "application/json", "User-Agent": UA})
try:
    resp = json.loads(urllib.request.urlopen(req, timeout=20).read())
    print("    SUCCESS:", json.dumps(resp)[:200])
    sec = resp.get("signing_secret") or resp.get("secret")
    if sec:
        print(f"\n    >>> Add this to the Worker secret RESEND_WEBHOOK_SECRET: {sec}")
except urllib.error.HTTPError as e:
    code = e.code
    print(f"    Resend webhook API returned HTTP {code} (likely dashboard-only).")
    print("\n=== DASHBOARD STEPS (2 min) ===")
    print("  1. https://resend.com/webhooks -> Add Endpoint")
    print(f"  2. Endpoint URL: {url}")
    print(f"  3. Events: {', '.join(EVENTS)}")
    print("  4. Save, then copy the Signing Secret (whsec_...) into the Worker")
    print("     secret RESEND_WEBHOOK_SECRET (Cloudflare -> Settings -> Variables).")
except Exception as e:
    print(f"    error: {e}")
