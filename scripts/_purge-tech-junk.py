"""Purge the non-ICP cluster the deep suspect list exposed: tech/SaaS vendors
scraped from microsoft.com marketplace pages, mortgage lenders (not RE agents),
and malformed 'u003e...' emails. Also null the one CRM-tool-as-company lead
(followupboss). verified=false + cancel runs (removes from sending, recoverable).

  py scripts/_purge-tech-junk.py --dry
  py scripts/_purge-tech-junk.py
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
def get(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL+p, headers=H), timeout=90).read())
def patch(p, b):
    r = urllib.request.Request(URL+p, data=json.dumps(b).encode(), method="PATCH",
        headers={**H, "Content-Type": "application/json", "Prefer": "return=minimal"})
    urllib.request.urlopen(r, timeout=60).read()
def page(t,s,e=""):
    out=[]
    for off in range(0,20000,1000):
        b=get(f"{t}?select={s}{e}&limit=1000&offset={off}"); out+=b
        if len(b)<1000: break
    return out

TECH_JUNK = {"cognite.com", "maqsoftware.com", "ema.ai", "cisecurity.org",
             "fivetran.com", "microsoft.com", "independent.com",
             "cnnmortgage.com", "novahomeloans.com"}
NULL_CO = {"followupboss.me"}   # real agent, CRM-tool as company -> null + pause

def dom(e): return (e or "").split("@")[-1].lower()
def local(e): return (e or "").split("@")[0].lower()

pros = page("prospects", "id,email,company,verified", "&profile_slug=eq.aureon")
purge, nullco = [], []
for p in pros:
    d = dom(p.get("email"))
    if d in TECH_JUNK or d.endswith(".ibm.com") or local(p.get("email")).startswith("u003e") or "vnet.ibm" in d:
        purge.append(p)
    elif d in NULL_CO and (p.get("company") or "").strip():
        nullco.append(p)

print(f"PURGE non-ICP (tech/mortgage/malformed): {len(purge)}")
for p in purge: print(f"   {p['email']:42} co={p.get('company')} verified={p.get('verified')}")
print(f"\nNULL company (CRM-as-company, real agent): {len(nullco)}")
for p in nullco: print(f"   {p['email']}  co={p.get('company')}")

if DRY:
    print("\n[dry] nothing written."); sys.exit(0)
for p in purge:
    patch(f"prospects?id=eq.{p['id']}", {"verified": False})
    for r in get(f"runs?prospect_id=eq.{p['id']}&status=in.(queued,paused_replied)&select=id"):
        patch(f"runs?id=eq.{r['id']}", {"status": "cancelled"})
for p in nullco:
    patch(f"prospects?id=eq.{p['id']}", {"company": None})
    for r in get(f"runs?prospect_id=eq.{p['id']}&status=eq.queued&select=id"):
        patch(f"runs?id=eq.{r['id']}", {"status": "cancelled"})
print(f"\npurged {len(purge)} non-ICP; nulled company on {len(nullco)}.")
