"""Read-only: pull Jake's prospect + reply + recent send_log so we can reply
from the correct aureon mailbox, in-thread."""
import json, urllib.parse, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")

def get(path):
    req = urllib.request.Request(URL + path, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

JAKE = "jake@cbstiles.com"
print("=== prospect ===")
pr = get(f"prospects?email=eq.{urllib.parse.quote(JAKE)}&select=*&limit=2")
print(json.dumps(pr, indent=2, default=str)[:1500])

print("\n=== replies (any profile) ===")
try:
    rp = get(f"replies?from_addr=eq.{urllib.parse.quote(JAKE)}&select=id,profile_slug,from_addr,to_addr,subject,body_snippet,received_at&order=received_at.desc&limit=5")
    print(json.dumps(rp, indent=2, default=str)[:1500])
except Exception as e:
    print("replies err:", e)

print("\n=== send_log (to Jake) ===")
try:
    sl = get(f"send_log?to_addr=eq.{urllib.parse.quote(JAKE)}&select=id,from_addr,to_addr,subject,resend_id,sent_at,delivered,bounced,error,step&order=sent_at.desc&limit=10")
    print(json.dumps(sl, indent=2, default=str)[:2500])
except Exception as e:
    print("send_log err:", e)
