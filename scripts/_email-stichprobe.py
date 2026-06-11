"""Stichprobe of the emails: (A) scan historical sent subjects for the
contamination we have been purging, (B) render the LIVE E1 A/B copy for a fresh
random sample of sendable prospects to see exactly what goes out now."""
import hashlib, json, sys, urllib.request
from collections import Counter
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sequences"))
from name_derive import _is_initial_plus_last  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
def get(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL+p, headers=H), timeout=90).read())
def page(t,s,e=""):
    out=[]
    for off in range(0,40000,1000):
        b=get(f"{t}?select={s}{e}&limit=1000&offset={off}"); out+=b
        if len(b)<1000: break
    return out

BAD = ["comcast","microsoft","cognite","fivetran"," ibm","realmadrid","iglobe",
       "sbcglobal","triad.rr","godaddy","novahomeloan","cnnmortgage","maqsoftware",
       "cisecurity","ema "," ema,","followupboss","independent","weltmonarch","jbasker",
       "vsanniota","veracase","mcneely real estate ","jlitten","kboyte"]

print("="*68)
print("A. HISTORICAL sent subjects (what actually went out)")
print("="*68)
sl = page("send_log", "subject,sent_at", "&order=sent_at.desc")
print(f"total send_log rows: {len(sl)}")
bad_sent = [r for r in sl if any(b in (r.get('subject') or '').lower() for b in BAD)]
print(f"subjects containing purged-junk tokens: {len(bad_sent)}")
for r in bad_sent[:20]:
    print(f"   {r.get('sent_at','')[:10]}  {r.get('subject')}")
if not bad_sent:
    print("   none — no contaminated subjects in the send history.")

print("\n" + "="*68)
print("B. LIVE render of E1 A/B for a fresh sendable sample")
print("="*68)
seq = get("sequences?slug=eq.aureon-default&select=id")[0]
s1 = get(f"sequence_steps?sequence_id=eq.{seq['id']}&step_n=eq.1&select=inline_subject,inline_body,variants(subject,body)")[0]
A = (s1.get("variants") or {})          # variant = side A (seller test)
B = {"subject": s1.get("inline_subject"), "body": s1.get("inline_body")}  # inline = side B (list)

def greeting(p):
    fn = (p.get("first_name") or "").strip()
    if fn: return fn
    co = (p.get("company") or "").strip()
    return f"{co} team" if co else "there"
def geo(p):
    c=(p.get("city") or "").strip(); s=(p.get("state") or "").strip()
    return f" in {c}, {s}" if c and s else (f" in {c}" if c else "")
def render(t,p):
    return (t or "").replace("{greeting}",greeting(p)).replace("{company}",(p.get("company") or "")).replace("{geo_clause}",geo(p))
def bad_greet(g):
    if any(c.isdigit() for c in g): return True
    if " " not in g and len(g)>=2 and _is_initial_plus_last(g.lower()): return True
    return False

pros = page("prospects","id,email,first_name,company,city,state",
            "&profile_slug=eq.aureon&verified=eq.true&unsubscribed=eq.false&company=not.is.null")
# deterministic spread: every Nth
sample = pros[::max(1,len(pros)//25)][:25]
flags = 0
for p in sample:
    even = int(hashlib.md5(str(p["id"]).encode()).hexdigest(),16) % 2 == 0
    v = B if even else A
    subj = render(v["subject"], p); g = greeting(p)
    bad = bad_greet(g) or "{" in subj or any(b in subj.lower() for b in BAD)
    if bad: flags += 1
    print(f"   [{'B' if even else 'A'}] {('FLAG ' if bad else '     ')}greet={g[:24]:24} | {subj}")
print(f"\nsendable sample: {len(sample)} | flagged: {flags}")
print(f"total sendable (verified+company+not-unsub): {len(pros)}")
