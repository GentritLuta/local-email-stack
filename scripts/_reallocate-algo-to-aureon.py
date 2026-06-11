"""Replace all algoalpha (crypto) sending with aureon (real estate):
  1. Move algo's 3 warmed subdomains (team/desk/hub) into aureon's from_domains
     (warmup state preserved).
  2. Rebrand algo's 3 personas to Aureon Global + add to aureon's personas.
  3. Deactivate algoalpha (active=false, from_domains/personas emptied so it
     cannot send) and cancel its queued/running runs.
  4. Sync both profile JSON files AND the Supabase profiles table.
Backs up both JSONs to *.bak first. Reversible.
"""
import json, urllib.request, urllib.parse, shutil
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
AUR = REPO / "profiles" / "aureon.json"
ALG = REPO / "profiles" / "algoalpha.json"

env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
def q(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL + p, headers=H), timeout=60).read())
def patch(p, b):
    urllib.request.urlopen(urllib.request.Request(URL + p, data=json.dumps(b).encode(),
        method="PATCH", headers={**H, "Prefer": "return=minimal"}), timeout=30)

# backups
shutil.copy(AUR, AUR.with_suffix(".json.bak"))
shutil.copy(ALG, ALG.with_suffix(".json.bak"))

aur = json.loads(AUR.read_text(encoding="utf-8"))
alg = json.loads(ALG.read_text(encoding="utf-8"))

moved_domains = alg["relay"]["from_domains"]
print(f"moving {len(moved_domains)} subdomains:", [d["domain"] for d in moved_domains])

# 1. move subdomains (skip any aureon already has)
have = {d["domain"] for d in aur["relay"]["from_domains"]}
for d in moved_domains:
    if d["domain"] not in have:
        aur["relay"]["from_domains"].append(d)

# 2. rebrand + move personas
rebranded = []
for p in alg.get("personas", []):
    name = (p.get("from_name", "").split(" from ")[0].strip()
            or p.get("slug", "rep").capitalize())
    np = dict(p)
    np["from_name"] = f"{name} from Aureon Global"
    np["reply_to"] = "info@aureonglobal.de"
    np["title"] = "Growth Partner, Aureon Global"
    np["signature"] = f"{name}\nAureon Global"
    rebranded.append(np)
    print(f"  rebranded persona {p.get('slug')} ({np['from_addr']}) -> Aureon Global")
exist_addrs = {p.get("from_addr") for p in aur.get("personas", [])}
for np in rebranded:
    if np["from_addr"] not in exist_addrs:
        aur.setdefault("personas", []).append(np)

# 3. deactivate algoalpha; empty its senders so it can never send
alg["active"] = False
alg["relay"]["from_domains"] = []
alg["personas"] = []

# 4. write files
AUR.write_text(json.dumps(aur, ensure_ascii=False, indent=2), encoding="utf-8")
ALG.write_text(json.dumps(alg, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\naureon now has {len(aur['relay']['from_domains'])} subdomains, "
      f"{len(aur['personas'])} personas")

# 5. sync DB profiles config + active
db_aur = q("profiles?slug=eq.aureon&select=config")[0]["config"]
db_aur["relay"] = aur["relay"]
db_aur["personas"] = aur["personas"]
patch("profiles?slug=eq.aureon", {"config": db_aur})
db_alg = q("profiles?slug=eq.algoalpha&select=config")[0]["config"]
db_alg["relay"] = {**db_alg.get("relay", {}), "from_domains": []}
db_alg["personas"] = []
patch("profiles?slug=eq.algoalpha", {"config": db_alg, "active": False})
print("DB profiles synced (aureon updated, algoalpha active=false, senders cleared)")

# 6. cancel algoalpha queued/running runs
seq = q("sequences?profile_slug=eq.algoalpha&select=id")
n = 0
for s in seq:
    runs = q(f"runs?sequence_id=eq.{s['id']}&status=in.(queued,running)&select=id&limit=8000")
    for r in runs:
        patch(f"runs?id=eq.{r['id']}", {"status": "cancelled"}); n += 1
print(f"cancelled {n} algoalpha queued/running runs")
print("\nDONE. All sending capacity is now aureon (real estate). Crypto stopped.")
