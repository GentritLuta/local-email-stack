"""Update the live aureon E1 (DB variant the runner reads) with the Hormozi-
maxed copy: bigger free give + explicit listings/clients promise. Then verify."""
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
def get(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL+p, headers=H), timeout=60).read())
def patch(p, b):
    r = urllib.request.Request(URL+p, data=json.dumps(b).encode(), method="PATCH",
        headers={**H, "Content-Type": "application/json", "Prefer": "return=representation"})
    return json.loads(urllib.request.urlopen(r, timeout=60).read())

SUBJECT = "a seller test for {company}"
BODY = (
    "Hey {greeting},\n\n"
    "Straight offer, free.\n\n"
    "Give me the main zip you work and for 14 days I will run seller outreach "
    "into that area and hand you every home seller lead and listing appointment "
    "it produces. You keep all of them. No card, no contract, and you can stop "
    "any day.\n\n"
    "Why I can do this for free: we are building a small set of case "
    "studies{geo_clause} before we set a price. That is the only catch, one "
    "honest review at the end if it works for you. If it produces nothing, you "
    "are out nothing.\n\n"
    "Most agents are stuck fighting for the same shared Zillow buyers. This puts "
    "motivated home sellers in front of {company} instead, the listings that "
    "actually build a business.\n\n"
    "We only take a few agents per area and there is room near you this week. "
    "Reply with your zip and I will set it up. If you would rather start smaller, "
    "reply LIST and I will send you a free list of 40 to 50 attorneys{geo_clause} "
    "who refer home sellers, no strings either way."
)

seq = get("sequences?profile_slug=eq.aureon&slug=eq.aureon-default&select=id")[0]
step1 = get(f"sequence_steps?sequence_id=eq.{seq['id']}&step_n=eq.1&select=id,variant_id,inline_subject")
st = step1[0]
print("step1:", {k: st.get(k) for k in ("id", "variant_id", "inline_subject")})

if st.get("variant_id"):
    res = patch(f"variants?id=eq.{st['variant_id']}", {"subject": SUBJECT, "body": BODY})
    print("patched variant", st["variant_id"][:8])
else:
    res = patch(f"sequence_steps?id=eq.{st['id']}", {"inline_subject": SUBJECT, "inline_body": BODY})
    print("patched inline on step", st["id"][:8])

# verify
chk = get(f"sequence_steps?sequence_id=eq.{seq['id']}&step_n=eq.1&select=inline_subject,inline_body,variants(subject,body)")[0]
live_s = chk.get("inline_subject") or (chk.get("variants") or {}).get("subject")
live_b = chk.get("inline_body") or (chk.get("variants") or {}).get("body")
print("\n=== LIVE E1 NOW ===\nSUBJECT:", live_s, "\n")
print(live_b)
print("\nchar-rule check:", "OK" if not any(c in (live_s+live_b) for c in "'’—–…“”") else "VIOLATION")
