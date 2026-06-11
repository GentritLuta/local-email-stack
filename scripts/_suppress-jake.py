"""URGENT: Jake unsubscribed. Suppress jake@cbstiles.com completely — mark
unsubscribed, cancel every run, so no email can ever fire to him again."""
import json, urllib.request, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
def get(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL+p, headers=H), timeout=60).read())
def patch(p, b):
    r = urllib.request.Request(URL+p, data=json.dumps(b).encode(), method="PATCH",
        headers={**H, "Content-Type": "application/json", "Prefer": "return=minimal"})
    urllib.request.urlopen(r, timeout=60).read()

JAKE = "jake@cbstiles.com"
now = datetime.datetime.utcnow().isoformat() + "Z"
ps = get(f"prospects?email=eq.{JAKE}&select=id,unsubscribed,unsubscribed_at")
if not ps:
    print("Jake not found as a prospect."); raise SystemExit
pid = ps[0]["id"]
print("before:", ps[0])

patch(f"prospects?id=eq.{pid}", {"unsubscribed": True, "unsubscribed_at": now})
runs = get(f"runs?prospect_id=eq.{pid}&select=id,status")
for r in runs:
    if r["status"] not in ("cancelled",):
        patch(f"runs?id=eq.{r['id']}", {"status": "cancelled"})

# also mark his reply id fulfilled so the auto-fulfiller never re-serves the list
STATE = REPO / "referral-lists" / ".fulfilled.json"
done = set(json.loads(STATE.read_text())) if STATE.exists() else set()
done.add("1aa6d600-36f9-4f7a-abcd-12018f33bdd5")
STATE.write_text(json.dumps(sorted(done)))

after = get(f"prospects?email=eq.{JAKE}&select=unsubscribed,unsubscribed_at")[0]
runs2 = get(f"runs?prospect_id=eq.{pid}&select=status")
print("after :", after)
print("runs  :", [r["status"] for r in runs2])
print("\nSUPPRESSED — unsubscribed=True, all runs cancelled. No email can fire to Jake.")
