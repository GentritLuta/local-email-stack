"""Hard-delete the non-ICP junk leads (Real Madrid corp inboxes, test inboxes,
malformed/foreign) from aureon, child-rows first so FKs are satisfied.

  py scripts/_delete-junk.py --dry
  py scripts/_delete-junk.py
"""
import json, sys, urllib.request
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

def delete(p):
    r = urllib.request.Request(URL + p, method="DELETE", headers={**H, "Prefer": "return=minimal"})
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

BAD_DOMAINS = {"realmadrid.com", "corp.realmadrid.com", "weltmonarch.de"}
BAD_NICHES = {"live_test", "deliverability_test", "test_inbox", "fintech_pitch"}
pros = page("prospects", "id,email,niche_slug,company", "&profile_slug=eq.aureon")
junk = []
for p in pros:
    em = (p.get("email") or "").lower()
    if ((em.split("@")[-1] in BAD_DOMAINS) or (p.get("niche_slug") in BAD_NICHES)
            or is_ours(em) or "+livetest" in em or "%20" in em
            or (p.get("company") or "").strip().lower() == "test inbox"):
        junk.append(p)
pids = [p["id"] for p in junk]
print(f"junk prospects to DELETE: {len(junk)}")
for p in junk:
    print(f"   {(p.get('email') or '')[:44]:44} niche={p.get('niche_slug')}")

if not pids:
    sys.exit(0)

# collect run ids for these prospects
run_ids = []
for pid in pids:
    run_ids += [r["id"] for r in get(f"runs?prospect_id=eq.{pid}&select=id")]
print(f"\nassociated runs: {len(run_ids)}")

def chunks(xs, n=30):
    for i in range(0, len(xs), n):
        yield xs[i:i+n]

if DRY:
    print("[dry] nothing deleted."); sys.exit(0)

# child-first: send_log -> replies -> runs -> prospects
sl = rp = 0
for ch in chunks(run_ids):
    inlist = ",".join(ch)
    try:
        n = len(get(f"send_log?run_id=in.({inlist})&select=id")); delete(f"send_log?run_id=in.({inlist})"); sl += n
    except Exception as e:
        print("  send_log del:", str(e)[:80])
    try:
        n = len(get(f"replies?run_id=in.({inlist})&select=id")); delete(f"replies?run_id=in.({inlist})"); rp += n
    except Exception as e:
        print("  replies del:", str(e)[:80])
for ch in chunks(run_ids):
    delete(f"runs?id=in.({','.join(ch)})")
for ch in chunks(pids):
    delete(f"prospects?id=in.({','.join(ch)})")
print(f"deleted: {sl} send_log, {rp} replies, {len(run_ids)} runs, {len(pids)} prospects.")
left = get("prospects?email=like.*realmadrid*&select=id")
print(f"verify: realmadrid prospects remaining = {len(left)}")
