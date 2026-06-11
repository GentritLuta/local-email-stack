"""Remediate: (A) pause any queued run whose prospect has replied (reply-stop
leak sweep), (B) purge non-ICP contamination from aureon (Real Madrid corp
emails, test inboxes, malformed/foreign). Safe: cancels runs + sets
verified=false (stops sends AND re-enrollment); never deletes.

  py scripts/_remediate-quality.py --dry
  py scripts/_remediate-quality.py
"""
import json, sys, urllib.parse, urllib.request
from pathlib import Path

DRY = "--dry" in sys.argv
REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

def get(p):
    return json.loads(urllib.request.urlopen(urllib.request.Request(URL + p, headers=H), timeout=90).read())

def patch(p, body):
    r = urllib.request.Request(URL + p, data=json.dumps(body).encode(), method="PATCH",
                               headers={**H, "Content-Type": "application/json", "Prefer": "return=minimal"})
    urllib.request.urlopen(r, timeout=60).read()

def page(table, select, extra=""):
    out = []
    for off in range(0, 20000, 1000):
        b = get(f"{table}?select={select}{extra}&limit=1000&offset={off}")
        out += b
        if len(b) < 1000: break
    return out

def is_ours(a):
    d = a.split("@")[-1].lower(); return d == "aureonglobal.de" or d.endswith(".aureonglobal.de")

# ---------- A. reply-stop leak sweep ----------
print("A. reply-stop sweep")
replies = page("replies", "from_addr,class", "&class=eq.reply")
repliers = sorted({r["from_addr"].lower() for r in replies if r.get("from_addr") and not is_ours(r["from_addr"])})
swept = []
for addr in repliers:
    ps = get(f"prospects?email=eq.{urllib.parse.quote(addr)}&select=id")
    for p in ps:
        qr = get(f"runs?prospect_id=eq.{p['id']}&status=eq.queued&select=id,current_step")
        for run in qr:
            swept.append((addr, run["current_step"], run["id"]))
            if not DRY:
                patch(f"runs?id=eq.{run['id']}", {"status": "paused_replied"})
print(f"   queued runs for replied prospects -> pause: {len(swept)}")
for a, st, rid in swept[:20]:
    print(f"      {a:34} step {st}  run {rid[:8]}")

# ---------- B. non-ICP contamination purge ----------
print("\nB. non-ICP purge (aureon)")
BAD_DOMAINS = {"realmadrid.com", "corp.realmadrid.com", "weltmonarch.de"}
BAD_NICHES = {"live_test", "deliverability_test", "test_inbox", "fintech_pitch"}
pros = page("prospects", "id,email,company,niche_slug,verified,profile_slug", "&profile_slug=eq.aureon")
purge = []
for p in pros:
    em = (p.get("email") or "").lower()
    dom = em.split("@")[-1]
    bad = (dom in BAD_DOMAINS
           or (p.get("niche_slug") in BAD_NICHES)
           or is_ours(em)                       # our own info@ addresses
           or "+livetest" in em or "%20" in em
           or (p.get("company") or "").strip().lower() == "test inbox")
    if bad:
        purge.append(p)
print(f"   prospects to purge: {len(purge)}")
by_dom = {}
for p in purge:
    by_dom.setdefault((p.get("email") or "").split("@")[-1], 0)
    by_dom[(p.get("email") or "").split("@")[-1]] += 1
print("   by domain:", by_dom)
for p in purge[:30]:
    print(f"      {(p.get('email') or '')[:42]:42} niche={p.get('niche_slug')} verified={p.get('verified')}")

cancelled = 0
if not DRY:
    for p in purge:
        # cancel queued/paused runs + stop re-enrollment
        runs = get(f"runs?prospect_id=eq.{p['id']}&status=in.(queued,paused_replied,paused_bounced)&select=id")
        for run in runs:
            patch(f"runs?id=eq.{run['id']}", {"status": "cancelled"}); cancelled += 1
        patch(f"prospects?id=eq.{p['id']}", {"verified": False})
    print(f"\n   cancelled {cancelled} runs; set verified=false on {len(purge)} prospects.")
else:
    print("\n   [dry] nothing written.")
