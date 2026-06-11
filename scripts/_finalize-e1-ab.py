"""Finalize E1 A/B: put variant B (give-first list) into step-1's inline fields
(variant A / seller-test stays in the linked variant). Delete the orphan variant
I created earlier. Verify the runner's per-prospect split is ~50/50."""
import hashlib, json, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
def get(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL+p, headers=H), timeout=60).read())
def patch(p, b):
    r = urllib.request.Request(URL+p, data=json.dumps(b).encode(), method="PATCH",
        headers={**H, "Content-Type": "application/json", "Prefer": "return=minimal"})
    urllib.request.urlopen(r, timeout=60).read()
def delete(p):
    urllib.request.urlopen(urllib.request.Request(URL+p, method="DELETE", headers={**H, "Prefer":"return=minimal"}), timeout=60).read()

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
s1 = get(f"sequence_steps?sequence_id=eq.{seq['id']}&step_n=eq.1&select=id,variant_id")[0]
patch(f"sequence_steps?id=eq.{s1['id']}", {"inline_subject": SUBJ_B, "inline_body": BODY_B})
# delete the orphan variant created in the failed step-row attempt
orphans = get("variants?profile_slug=eq.aureon&angle=eq.give_first_attorney_list_ab&select=id")
for o in orphans:
    if o["id"] != s1["variant_id"]:
        delete(f"variants?id=eq.{o['id']}")
        print("deleted orphan variant", o["id"][:8])

# verify
chk = get(f"sequence_steps?sequence_id=eq.{seq['id']}&step_n=eq.1&select=inline_subject,variants(subject)")[0]
print("\nE1 A/B now live on step 1:")
print("  B (inline) :", chk["inline_subject"])
print("  A (variant):", (chk.get("variants") or {}).get("subject"))

# simulate the runner split over real prospect ids
ids = [p["id"] for p in get("prospects?profile_slug=eq.aureon&select=id&limit=400")]
a = sum(1 for i in ids if int(hashlib.md5(str(i).encode()).hexdigest(), 16) % 2 != 0)
b = len(ids) - a
print(f"\nsplit over {len(ids)} prospects: A(seller-test)={a}  B(list)={b}  "
      f"({100*a//max(len(ids),1)}/{100*b//max(len(ids),1)})")
