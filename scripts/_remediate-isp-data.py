"""Fix the data-quality damage the targeting audit found:
  - DELETE hard junk (registrar/parked/non-US non-RE: godaddy filler, iglobe.dk).
  - NULL the wrong company+website on ISP-email leads (comcast.net / *.rr.com /
    verizon / att ...). Those are REAL agents whose brokerage was on the source
    page, but the scraper made a fake company from the ISP domain ("Comcast",
    "Triad.rr"). Nulling pauses them (fails the {company} merge) instead of
    sending "for Comcast"; they can be re-enriched from source_url later.

  py scripts/_remediate-isp-data.py --dry
  py scripts/_remediate-isp-data.py
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
def delete(p):
    urllib.request.urlopen(urllib.request.Request(URL+p, method="DELETE", headers={**H, "Prefer": "return=minimal"}), timeout=60).read()
def page(t, s, e=""):
    out=[]
    for off in range(0,20000,1000):
        b=get(f"{t}?select={s}{e}&limit=1000&offset={off}"); out+=b
        if len(b)<1000: break
    return out

DELETE_DOMAINS = {"godaddy.com", "secureserver.net", "iglobe.dk", "wixsite.com",
                  "weebly.com", "parkingcrew.net", "mysite.com", "sentry.io"}
NULL_DOMAINS = {"comcast.net", "comcast.com", "verizon.net", "att.net",
                "sbcglobal.net", "bellsouth.net", "cox.net", "charter.net",
                "spectrum.net", "earthlink.net", "juno.com", "optonline.net",
                "windstream.net", "frontier.com", "frontiernet.net",
                "centurylink.net", "roadrunner.com", "twc.com", "ptd.net"}
def dom(e): return (e or "").split("@")[-1].lower()
def is_null_dom(d): return d in NULL_DOMAINS or d.endswith(".rr.com")

pros = page("prospects", "id,email,company,website", "&profile_slug=eq.aureon")
to_delete = [p for p in pros if dom(p.get("email")) in DELETE_DOMAINS]
to_null = [p for p in pros if is_null_dom(dom(p.get("email"))) and (p.get("company") or p.get("website"))]

print(f"aureon: {len(pros)}")
print(f"\nDELETE (hard junk): {len(to_delete)}")
for p in to_delete: print(f"   {p['email']}  co={p.get('company')}")
print(f"\nNULL company/website (ISP real-agents, pause for re-enrich): {len(to_null)}")
for p in to_null: print(f"   {p['email']}  co={p.get('company')} site={p.get('website')}")

if DRY:
    print("\n[dry] nothing written."); sys.exit(0)

# delete junk (child rows first)
for p in to_delete:
    rids = [r["id"] for r in get(f"runs?prospect_id=eq.{p['id']}&select=id")]
    for rid in rids:
        try: delete(f"send_log?run_id=eq.{rid}")
        except Exception: pass
        try: delete(f"replies?run_id=eq.{rid}")
        except Exception: pass
        delete(f"runs?id=eq.{rid}")
    delete(f"prospects?id=eq.{p['id']}")
# null wrong company+website + cancel their queued runs (missing-merge would cancel anyway)
for p in to_null:
    patch(f"prospects?id=eq.{p['id']}", {"company": None, "website": None})
    for r in get(f"runs?prospect_id=eq.{p['id']}&status=eq.queued&select=id"):
        patch(f"runs?id=eq.{r['id']}", {"status": "cancelled"})
print(f"\ndeleted {len(to_delete)} junk; nulled company/website on {len(to_null)} ISP leads.")
