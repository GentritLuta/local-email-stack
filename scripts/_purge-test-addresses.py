"""Purge test / placeholder / own-domain addresses that should never be
emailed, suppress them, and cancel any queued runs to them. Closes the
'deine-email@domain.de' + 'info+livetest@aureonglobal.de' leak class."""
import json, urllib.request, urllib.parse, sys
from pathlib import Path
from collections import Counter

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from lead_verify import PLACEHOLDER_DOMAINS

env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

def q(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL + p, headers=H), timeout=90).read())
def patch(p, b):
    urllib.request.urlopen(urllib.request.Request(URL + p, data=json.dumps(b).encode(),
        method="PATCH", headers={**H, "Prefer": "return=minimal"}), timeout=30)

# Our OWN sending domains — never cold-email ourselves
OWN = {"aureonglobal.de"}
for p in q("profiles?select=config"):
    for fd in (p.get("config", {}).get("relay", {}).get("from_domains") or []):
        if fd.get("domain"):
            OWN.add(fd["domain"].lower())
            # also the root
            parts = fd["domain"].lower().split(".")
            if len(parts) >= 2:
                OWN.add(".".join(parts[-2:]))

def is_bad(email):
    e = (email or "").lower().strip()
    if "@" not in e: return "no_at"
    local, dom = e.split("@", 1)
    if dom in PLACEHOLDER_DOMAINS: return "placeholder_domain"
    if dom in OWN or any(dom.endswith("." + o) or dom == o for o in OWN): return "own_domain"
    if "+test" in local or "+livetest" in local or "livetest" in local or local in ("test", "livetest"): return "test_tag"
    if local in ("deine-email", "your-email", "ihre-email", "youremail", "name", "email", "muster", "beispiel"): return "placeholder_local"
    return None

rows = q("prospects?select=id,email,profile_slug,verified&limit=10000")
hits = Counter(); ids = []
for p in rows:
    why = is_bad(p["email"])
    if why:
        hits[why] += 1
        if p.get("verified"):
            patch(f"prospects?id=eq.{p['id']}", {"verified": False, "verification_error": f"test_or_placeholder:{why}"})
            ids.append(p["id"])
        print(f"  {why:20s} {p['email']}")

print("\n=== purged test/placeholder/own-domain ===")
for w, n in hits.most_common(): print(f"   {n:4d}  {w}")

# cancel any queued/running runs to these prospects
cancelled = 0
for i in range(0, len(ids), 50):
    batch = ",".join(ids[i:i+50])
    for r in q(f"runs?prospect_id=in.({batch})&status=in.(queued,running)&select=id"):
        patch(f"runs?id=eq.{r['id']}", {"status": "cancelled"}); cancelled += 1
print(f"suppressed {len(ids)} verified rows, cancelled {cancelled} queued runs")
