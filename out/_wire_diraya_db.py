# -*- coding: utf-8 -*-
"""DB-wire Diraya: create the variants rows + the sequence row in Supabase from
sequences/diraya-default/variants.json. Idempotent. After this, run
scripts/wire-sequence-steps.py diraya to link sequence_steps.
"""
import json, urllib.request
from pathlib import Path

REPO = Path(r"C:\Users\bernh\local-email-stack")
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
U = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
K = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": K, "Authorization": "Bearer " + K, "Content-Type": "application/json"}

def get(p):
    return json.loads(urllib.request.urlopen(urllib.request.Request(U + p, headers=H), timeout=30).read())
def post(p, body):
    r = urllib.request.Request(U + p, data=json.dumps(body).encode(), method="POST",
                               headers={**H, "Prefer": "return=representation"})
    return json.loads(urllib.request.urlopen(r, timeout=30).read())

data = json.loads((REPO / "sequences" / "diraya-default" / "variants.json").read_text(encoding="utf-8"))
vs = data["variants"]

# 0) profiles row — FK target for variants + sequences. active=False (domains
#    still verifying; no leads yet). config = the diraya.json profile file.
if not get("profiles?slug=eq.diraya&select=slug"):
    pconf = json.loads((REPO / "profiles" / "diraya.json").read_text(encoding="utf-8"))
    pconf["active"] = False
    post("profiles", {"slug": "diraya", "name": pconf.get("name", "Diraya"),
                      "config": pconf, "active": False})
    print("profiles row created for diraya (active=False)")
else:
    print("profiles row exists")

# 1) variants rows
have = {v["n"] for v in get("variants?profile_slug=eq.diraya&select=n")}
created = 0
for v in vs:
    if v["n"] in have:
        continue
    post("variants", {"profile_slug": "diraya", "n": v["n"], "angle": v.get("angle", ""),
                      "subject": v["subject"], "body": v["body"]})
    created += 1
print(f"variants: {len(have)} existed, +{created} created (total should be {len(vs)})")

# 2) sequence row
seq = get("sequences?profile_slug=eq.diraya&select=id,slug,active")
if not seq:
    s = post("sequences", {"profile_slug": "diraya", "slug": data["slug"],
                           "name": data["name"], "active": True})
    print("sequence created:", s[0]["id"][:8], s[0]["slug"], "active=True")
else:
    print("sequence exists:", seq[0]["id"][:8], seq[0]["slug"], "active=", seq[0].get("active"))
    if not seq[0].get("active"):
        urllib.request.urlopen(urllib.request.Request(
            U + f"sequences?id=eq.{seq[0]['id']}", data=json.dumps({"active": True}).encode(),
            method="PATCH", headers={**H, "Prefer": "return=minimal"}), timeout=30)
        print("  -> set active=True")
print("DONE. Next: scripts/wire-sequence-steps.py diraya")
