"""Dump the COMPLETE Resend GET /emails/{id} response for a bounced email, to
confirm whether any bounce-reason field exists (vs needing webhooks)."""
import json, urllib.request, urllib.parse, datetime as dt
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
def load(p):
    d = {}
    for line in (REPO / "sequences" / p).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1); d[k.strip()] = v.strip().strip('"').strip("'")
    return d
env = load("supabase.env"); host = load("hostinger.env")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"; KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
RK = host["RESEND_FULL_ACCESS_API_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123 Safari/537.36"
since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
b = json.loads(urllib.request.urlopen(urllib.request.Request(
    URL + "send_log?sent_at=gte." + urllib.parse.quote(since) +
    "&bounced=eq.true&select=resend_id,to_addr&limit=3", headers=H), timeout=60).read())
for r in b:
    rid = r.get("resend_id")
    if not rid: continue
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://api.resend.com/emails/" + rid,
            headers={"Authorization": f"Bearer {RK}", "User-Agent": UA}), timeout=20).read())
        print(f"=== {r['to_addr']} ===")
        print(json.dumps(d, indent=2)[:1500])
        print()
    except Exception as e:
        print(rid, "err", e)
