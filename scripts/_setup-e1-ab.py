"""Set up the E1 A/B test. Variant A (free seller-lead test) is live. This adds
variant B (give-first attorney list) as a SECOND step-1 row, so the runner's
per-prospect hash splits sends ~50/50. Clones the existing variant + step row
structure so we satisfy whatever columns the schema requires.

  py scripts/_setup-e1-ab.py --dry   # inspect structures, write nothing
  py scripts/_setup-e1-ab.py         # create variant B + step-1 B row
"""
import json, sys, urllib.request, urllib.error
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
def get(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL+p, headers=H), timeout=60).read())
def post(p, b):
    r = urllib.request.Request(URL+p, data=json.dumps(b).encode(), method="POST",
        headers={**H, "Content-Type": "application/json", "Prefer": "return=representation"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read())

SUBJ_B = "a listing source for {company}"
BODY_B = (
    "Hey {greeting},\n\nNo pitch in this email, just something you can use.\n\n"
    "I will build you a ready to use list of 40 to 50 divorce and estate "
    "attorneys{geo_clause}, the exact firms whose clients often have to sell a "
    "home fast. Each entry has the attorney to ask for, a direct phone, and the "
    "office address, so you can start the same day.\n\n"
    "Here is why it matters for {company}. These attorneys are the highest "
    "converting listing source in real estate, motivated sellers and almost no "
    "agent competition. Work five or six of them and you become the agent they "
    "send every client who needs to sell. That is a steady flow of listings "
    "without paying for one shared Zillow lead.\n\n"
    "Reply with the word LIST and it is in your inbox inside 24 hours. No call, "
    "no catch, no cost.\n\n"
    "If you already work that channel, tell me and I will build you a different one."
)

seq = get("sequences?slug=eq.aureon-default&select=id")[0]
steps1 = get(f"sequence_steps?sequence_id=eq.{seq['id']}&step_n=eq.1&select=*")
print(f"step-1 rows currently: {len(steps1)}")
s1 = steps1[0]
vA = get(f"variants?id=eq.{s1['variant_id']}&select=*")[0]
print("variant columns:", list(vA.keys()))
print("step columns   :", list(s1.keys()))
if len(steps1) > 1:
    print("\nstep 1 already has >1 row — A/B likely already set up. Subjects:")
    for s in steps1:
        v = get(f"variants?id=eq.{s['variant_id']}&select=subject")[0]
        print("   ", v["subject"])
    sys.exit(0)
if DRY:
    print("\n[dry] would create variant B + a second step-1 row.")
    sys.exit(0)

# variant B = clone of A, override copy; bump any unique 'n'/'angle'
vB = {k: v for k, v in vA.items() if k != "id"}
vB["subject"] = SUBJ_B; vB["body"] = BODY_B
if "n" in vB and isinstance(vB["n"], int): vB["n"] = 101
if "angle" in vB: vB["angle"] = "give_first_attorney_list_ab"
try:
    created_v = post("variants", vB)[0]
except urllib.error.HTTPError as e:
    sys.exit(f"variant B create failed: {e.code} {e.read().decode()[:300]}")
print("created variant B:", created_v["id"][:8])

# step-1 B row = clone of A's step row, point at variant B
sB = {k: v for k, v in s1.items() if k != "id"}
sB["variant_id"] = created_v["id"]
try:
    created_s = post("sequence_steps", sB)[0]
except urllib.error.HTTPError as e:
    sys.exit(f"step B create failed: {e.code} {e.read().decode()[:300]}\n"
             f"(if this is a unique (sequence_id,step_n) constraint, the A/B needs a different mechanism)")
print("created step-1 B row:", created_s["id"][:8])

after = get(f"sequence_steps?sequence_id=eq.{seq['id']}&step_n=eq.1&select=variant_id")
print(f"\nstep-1 rows now: {len(after)}  -> A/B live (runner splits 50/50 by prospect)")
for s in after:
    v = get(f"variants?id=eq.{s['variant_id']}&select=subject")[0]
    print("   ", v["subject"])
