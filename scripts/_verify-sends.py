"""Verify the send pipeline: when did emails last go out, how many, from which
subdomains/profiles, are queued runs ready, and is the (post-reallocation)
aureon persona+subdomain config actually valid to send."""
import json, urllib.request, urllib.parse, datetime as dt
from pathlib import Path
from collections import Counter, defaultdict

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
def q(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL + p, headers=H), timeout=90).read())

now = dt.datetime.now(dt.timezone.utc)
print("now:", now.strftime("%A %Y-%m-%d %H:%MZ"))

# 1. sends per day, last 12 days
since = (now - dt.timedelta(days=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
sl = q("send_log?sent_at=gte." + urllib.parse.quote(since) + "&select=sent_at,from_addr,bounced,delivered&limit=8000")
byday = defaultdict(lambda: [0, 0, 0])  # sent, delivered, bounced
for r in sl:
    d = (r.get("sent_at") or "")[:10]
    byday[d][0] += 1
    if r.get("delivered"): byday[d][1] += 1
    if r.get("bounced"): byday[d][2] += 1
print("\n=== SENDS PER DAY (last 12d) ===")
for d in sorted(byday)[-12:]:
    s, dl, b = byday[d]
    print(f"  {d}  sent={s:4d}  delivered={dl:4d}  bounced={b:2d}  ({100*b/s if s else 0:.1f}%)")

# 2. last send timestamp
if sl:
    last = max(r["sent_at"] for r in sl if r.get("sent_at"))
    print(f"\nLAST SEND: {last}  ({(now - dt.datetime.fromisoformat(last.replace('Z','+00:00'))).total_seconds()/3600:.1f}h ago)")

# 3. queued runs ready to fire
runs = q("runs?status=eq.queued&select=next_send_at,sequence_id&limit=8000")
seqs = {s["id"]: s["profile_slug"] for s in q("sequences?select=id,profile_slug")}
due = sum(1 for r in runs if r.get("next_send_at") and r["next_send_at"] <= now.isoformat())
byprof = Counter(seqs.get(r["sequence_id"], "?") for r in runs)
print(f"\n=== QUEUED RUNS: {len(runs)} total, {due} due now ===")
for p, n in byprof.most_common(): print(f"  {p}: {n} queued")

# 4. validate aureon senders (post-reallocation): each persona from_addr must be
#    on a verified subdomain in the same profile
aur = json.loads((REPO / "profiles" / "aureon.json").read_text(encoding="utf-8"))
verified_subs = {fd["domain"] for fd in aur["relay"]["from_domains"]
                 if fd.get("verified") or fd.get("verified_at")}
print(f"\n=== AUREON SENDER VALIDATION ({len(aur['personas'])} personas, {len(verified_subs)} verified subs) ===")
bad = 0
for p in aur["personas"]:
    fa = p.get("from_addr", "")
    sub = fa.split("@")[-1] if "@" in fa else ""
    ok = sub in verified_subs
    if not ok: bad += 1
    print(f"  {'OK ' if ok else 'BAD'} {p.get('slug'):8s} {fa:32s} {p.get('from_name','')}")
print(f"  -> {bad} invalid senders" if bad else "  -> all senders valid (can send)")
