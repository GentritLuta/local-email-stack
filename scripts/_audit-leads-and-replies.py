"""Audit: (A) does a reply actually stop the sequence? (B) is the Aureon lead
base real-estate ICP / good quality? Read-only."""
import json, re, urllib.parse, urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

def get(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(URL + path, headers=H), timeout=90).read())

def page(table, select, extra=""):
    out = []
    for off in range(0, 20000, 1000):
        b = get(f"{table}?select={select}{extra}&limit=1000&offset={off}")
        out += b
        if len(b) < 1000: break
    return out

def is_ours(a):
    d = a.split("@")[-1].lower(); return d == "aureonglobal.de" or d.endswith(".aureonglobal.de")

print("="*70)
print("A.  REPLY  ->  SEQUENCE STOP  integrity")
print("="*70)
replies = page("replies", "id,run_id,from_addr,subject,class,received_at", "&class=eq.reply&order=received_at.desc")
ext = [r for r in replies if r.get("from_addr") and not is_ours(r["from_addr"])]
matched = [r for r in ext if r.get("run_id")]
print(f"reply-class rows: {len(replies)} | external (real prospects): {len(ext)} | "
      f"matched to a run: {len(matched)} ({100*len(matched)//max(len(ext),1)}%)")

# run status distribution
runs = page("runs", "id,status,prospect_id,sequence_id,current_step")
print("\nrun status distribution:")
for s, c in Counter(r.get("status") for r in runs).most_common():
    print(f"   {s or '(null)':18} {c}")

# LEAK CHECK: a distinct external replier who STILL has a queued run = sequence not stopped
repliers = sorted({r["from_addr"].lower() for r in ext})
print(f"\ndistinct external repliers: {len(repliers)}  — checking each for a still-queued run...")
leaks, matched_prospect, no_prospect = [], 0, 0
for addr in repliers:
    ps = get(f"prospects?email=eq.{urllib.parse.quote(addr)}&select=id,profile_slug")
    if not ps:
        no_prospect += 1; continue
    matched_prospect += 1
    pid = ps[0]["id"]
    qr = get(f"runs?prospect_id=eq.{pid}&status=eq.queued&select=id,current_step,sequence_id")
    if qr:
        leaks.append((addr, ps[0].get("profile_slug"), qr[0]["current_step"], qr[0]["id"]))
print(f"   repliers matched to a prospect: {matched_prospect} | not a prospect (3rd party): {no_prospect}")
if leaks:
    print(f"   !! LEAKS — replied but STILL queued (would keep emailing): {len(leaks)}")
    for a, pr, st, rid in leaks[:20]:
        print(f"      {a:34} [{pr}] step {st}  run {rid[:8]}")
else:
    print("   OK — every replier's run is paused/cancelled/completed. No sequence continues after a reply.")

# Jake spot-check
jp = get("prospects?email=eq.jake@cbstiles.com&select=id")
if jp:
    jr = get(f"runs?prospect_id=eq.{jp[0]['id']}&select=status,current_step")
    print(f"\n   Jake spot-check: runs = {[ (x['status'], x['current_step']) for x in jr ]}")

print("\n" + "="*70)
print("B.  LEAD QUALITY  /  ICP  (Aureon = US real-estate agents/brokerages)")
print("="*70)
pros = page("prospects", "email,first_name,last_name,company,title,website,source_url,niche_slug,quality_score,verified,unsubscribed,enriched_context", "&profile_slug=eq.aureon")
n = len(pros)
print(f"aureon prospects: {n}")

RE = ["realty","realtor","real estate","realestate","real-estate","homes","properties",
      "property","broker","remax","re/max","kw.com","kwrealty","keller","century21","c21",
      "coldwell","banker","cbhomes","exp realty","exprealty","compass","sotheby","berkshire",
      "hathaway","bhhs","weichert","howardhanna","redfin","listing","mls","homesmart",
      "realestat","sells","soldby","grouprealty","homegroup"]
def re_signal(p):
    hay = " ".join([(p.get("email") or ""), (p.get("company") or ""), (p.get("website") or ""),
                    (p.get("source_url") or "")]).lower()
    return any(k in hay for k in RE)

with_re = [p for p in pros if re_signal(p)]
print(f"\nreal-estate signal in email/company/website/source: {len(with_re)}/{n} "
      f"({100*len(with_re)//max(n,1)}%)")

# niche
print("niche_slug:", dict(Counter(p.get("niche_slug") for p in pros).most_common()))
# verified / unsub
print(f"verified: {sum(1 for p in pros if p.get('verified'))}/{n} | "
      f"unsubscribed: {sum(1 for p in pros if p.get('unsubscribed'))}")
# quality score buckets
qs = [p.get("quality_score") for p in pros if p.get("quality_score") is not None]
if qs:
    b = Counter(("none" if s is None else ("0-19" if s<20 else "20-39" if s<40 else "40-59" if s<60 else "60-79" if s<80 else "80+")) for s in qs)
    print("quality_score buckets:", dict(b), f"(avg {sum(qs)//len(qs)})")
# generic local parts
gen = Counter()
for p in pros:
    lp = (p.get("email") or "").split("@")[0].lower()
    if lp in {"info","office","contact","team","admin","hello","sales","broker","realtor","homes","listings"}:
        gen[lp]+=1
print(f"generic role-localpart emails: {sum(gen.values())} {dict(gen.most_common(8))}")
# top email domains (concentration)
dom = Counter((p.get("email") or "").split("@")[-1].lower() for p in pros if p.get("email"))
print("\ntop email domains (concentration):")
for d, c in dom.most_common(12):
    print(f"   {c:4}  {d}")
# top source URLs (where scraped from)
src = Counter((p.get("source_url") or "—") for p in pros)
print("top source_url (scrape origin):")
for s, c in src.most_common(8):
    print(f"   {c:4}  {s[:70]}")
# titles
ti = Counter((p.get("title") or "").strip().lower() for p in pros if (p.get("title") or "").strip())
if ti:
    print("top titles:", dict(ti.most_common(10)))

# NON-RE sample (potential non-ICP) to eyeball
print("\nNON-real-estate-signal sample (potential non-ICP):")
nonre = [p for p in pros if not re_signal(p)]
print(f"   total without RE signal: {len(nonre)}")
for p in nonre[:18]:
    print(f"   {(p.get('email') or '')[:38]:38} | co={(p.get('company') or '')[:22]:22} | site={(p.get('website') or '')[:28]}")
