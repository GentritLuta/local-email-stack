"""Read-only: Aureon prospect geography (state + phone area code + city coverage)
so we know which metros to pre-curate, plus any pending LIST/PROBATE replies."""
import json, re, urllib.request, urllib.parse
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")

def get(path, count=False):
    req = urllib.request.Request(URL + path, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                                 **({"Prefer": "count=exact", "Range": "0-0"} if count else {})})
    with urllib.request.urlopen(req, timeout=90) as r:
        if count:
            cr = r.headers.get("Content-Range", "*/?")
            return cr.split("/")[-1]
        return json.loads(r.read())

# area code -> metro label (US, the ones aureon is likely in)
AC = {"317": "Indianapolis IN", "463": "Indianapolis IN", "812": "S. Indiana",
      "765": "C. Indiana", "574": "N. Indiana", "260": "Fort Wayne IN"}

total = get("prospects?profile_slug=eq.aureon&select=id", count=True)
print(f"aureon prospects total: {total}\n")

rows = []
for off in range(0, 20000, 1000):
    batch = get(f"prospects?profile_slug=eq.aureon&select=phone,city,state&limit=1000&offset={off}")
    rows += batch
    if len(batch) < 1000:
        break
print(f"pulled {len(rows)} rows for aggregation")

st = Counter((r.get("state") or "?").upper() or "?" for r in rows)
have_city = sum(1 for r in rows if (r.get("city") or "").strip())
have_state = sum(1 for r in rows if (r.get("state") or "").strip())
have_phone = sum(1 for r in rows if (r.get("phone") or "").strip())

def area(p):
    d = re.sub(r"\D", "", p or "")
    d = d[1:] if len(d) == 11 and d.startswith("1") else d
    return d[:3] if len(d) >= 10 else ""
ac = Counter(area(r.get("phone")) for r in rows if area(r.get("phone")))

print(f"\ncity present : {have_city}/{len(rows)} ({100*have_city//max(len(rows),1)}%)")
print(f"state present: {have_state}/{len(rows)}")
print(f"phone present: {have_phone}/{len(rows)} ({100*have_phone//max(len(rows),1)}%)")
print("\ntop states:")
for s, c in st.most_common(12):
    print(f"   {s:4} {c}")
print("\ntop phone area codes (metro proxy):")
for a, c in ac.most_common(15):
    print(f"   {a}  {c:5}  {AC.get(a,'')}")
print("\ntop cities (where present):")
cic = Counter((r.get("city") or "").strip() for r in rows if (r.get("city") or "").strip())
for c, n in cic.most_common(15):
    print(f"   {n:4}  {c}")

# pending LIST/PROBATE replies
print("\n=== pending LIST/PROBATE replies ===")
STATE = REPO / "referral-lists" / ".fulfilled.json"
done = set(json.loads(STATE.read_text())) if STATE.exists() else set()
reps = get("replies?select=id,profile_slug,from_addr,body_snippet,received_at&order=received_at.desc&limit=500")
def kw(b):
    low = (b or "").lower()
    if re.search(r"\bprobate\b", low): return "probate"
    if re.search(r"\blist\b", low): return "list"
    return None
pend = [r for r in reps if kw(r.get("body_snippet")) and r["id"] not in done]
print(f"replies scanned: {len(reps)} | LIST/PROBATE not yet fulfilled: {len(pend)}")
for r in pend[:20]:
    em = r["from_addr"].lower()
    ps = get(f"prospects?email=eq.{urllib.parse.quote(em)}&select=city,state,phone&limit=1")
    loc = ""
    if ps:
        loc = f"{ps[0].get('city') or '?'},{ps[0].get('state') or '?'} ac={area(ps[0].get('phone'))}"
    print(f"   {kw(r['body_snippet']).upper():8} {em:34} [{loc}] {r['received_at'][:10]} prof={r.get('profile_slug')}")
