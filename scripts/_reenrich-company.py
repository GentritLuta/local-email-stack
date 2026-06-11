"""Re-enrich aureon agents with NO company by assigning the brokerage of their
SOURCE page — but only for pages that are a SINGLE brokerage's own team site
(every agent there is that brokerage). Names are the audit-VERIFIED brokerages,
not scraped titles. Multi-brokerage referral pages (whitestagrealty lists agents
from Trueblood/KW/etc.) and directories (fastexpert) are skipped — their agents'
real firm is ambiguous, so we never guess.

  py scripts/_reenrich-company.py --dry
  py scripts/_reenrich-company.py
"""
import json, sys, urllib.parse, urllib.request
from collections import Counter
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

# domain -> audit-verified brokerage name (single-brokerage team pages only)
SOURCE_BROKERAGE = {
    "edpricetriad.com":             "Price REALTORS",
    "equitycoloradorealestate.com": "Equity Colorado Real Estate",
    "justlistedrealestateoh.com":   "Just Listed Real Estate",
    "colo-realty.com":              "Colorado Realty & Land",
    "mymetrocity.com":              "Metro City Realty",
    "raynorrealtync.com":           "Raynor Realty",
    "mcneelyrealestate.com":        "McNeely Real Estate Group",
    "thestacygroup.com":            "The Stacy Group",
}
# explicitly DO NOT assign for these (ambiguous / multi-brokerage)
SKIP = {"whitestagrealty.com", "fastexpert.com"}

def dom(u): return urllib.parse.urlparse(u or "").netloc.replace("www.", "")

rows = page("prospects", "id,email,company,source_url", "&profile_slug=eq.aureon")
co_none = [r for r in rows if not (r.get("company") or "").strip() and (r.get("source_url") or "").strip()]
print(f"aureon co=None with a source: {len(co_none)}\n")
src_counts = Counter(dom(r["source_url"]) for r in co_none)
for d, c in src_counts.most_common():
    tag = SOURCE_BROKERAGE.get(d) or ("SKIP" if d in SKIP else "(no map)")
    print(f"  {c:4}  {d:30} -> {tag}")

targets = [r for r in co_none if dom(r["source_url"]) in SOURCE_BROKERAGE]
print(f"\nassignable: {len(targets)}")
if DRY:
    print("[dry] nothing written."); sys.exit(0)
for r in targets:
    patch(f"prospects?id=eq.{r['id']}", {"company": SOURCE_BROKERAGE[dom(r['source_url'])]})
print(f"re-enriched company on {len(targets)} agents (now sendable).")
