"""E1 A/B readout: compare the two step-1 subjects (A = free seller test,
B = give-first attorney list) on sent / delivered / reply rate. Run any time;
the winner becomes clear as volume builds.

  py scripts/ab-results.py
"""
import json, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
def get(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL+p, headers=H), timeout=90).read())

rows = []
for off in range(0, 20000, 1000):
    b = get(f"send_log?step_n=eq.1&select=subject,delivered,bounced,replied,opened_at&limit=1000&offset={off}")
    rows += b
    if len(b) < 1000: break

def side(s):
    s = (s or "").lower()
    if "seller test" in s: return "A seller-test"
    if "listing source" in s or "a list for" in s: return "B give-first-list"
    return "(other/legacy)"

agg = {}
for r in rows:
    k = side(r.get("subject"))
    a = agg.setdefault(k, {"sent": 0, "delivered": 0, "bounced": 0, "opened": 0, "replied": 0})
    a["sent"] += 1
    if r.get("delivered") and not r.get("bounced"): a["delivered"] += 1
    if r.get("bounced"): a["bounced"] += 1
    if r.get("opened_at"): a["opened"] += 1
    if r.get("replied"): a["replied"] += 1

def pct(n, d): return f"{100*n/d:.1f}%" if d else "-"
print(f"{'variant':20} {'sent':>6} {'deliv':>6} {'open%':>7} {'reply':>6} {'reply%':>7} {'bounce%':>8}")
for k in sorted(agg):
    a = agg[k]
    print(f"{k:20} {a['sent']:>6} {a['delivered']:>6} {pct(a['opened'],a['delivered']):>7} "
          f"{a['replied']:>6} {pct(a['replied'],a['delivered']):>7} {pct(a['bounced'],a['sent']):>8}")
print("\n(reply% is of delivered. Let it run a few days for a fair read; keep the higher reply%.)")
