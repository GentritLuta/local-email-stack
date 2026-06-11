"""One-shot: pull the REAL bounce reasons from Resend for every 30-day bounce,
categorize root causes, and find leaks. Uses the full-access key the reconciler
uses (hostinger.env)."""
import json, urllib.request, urllib.parse, datetime as dt, sys
from pathlib import Path
from collections import Counter

REPO = Path(__file__).resolve().parent.parent
def load(p):
    d = {}
    for line in (REPO / "sequences" / p).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1); d[k.strip()] = v.strip().strip('"').strip("'")
    return d
env = load("supabase.env"); host = load("hostinger.env")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
RK = host.get("RESEND_FULL_ACCESS_API_KEY", "")
print("resend full-access key present:", bool(RK), "len", len(RK))
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36")

def q(p): return json.loads(urllib.request.urlopen(urllib.request.Request(URL + p, headers=H), timeout=90).read())

since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
b = q("send_log?sent_at=gte." + urllib.parse.quote(since) +
      "&bounced=eq.true&select=to_addr,resend_id,error,from_addr&limit=2000")
print(f"\n{len(b)} bounces. Querying Resend for real reasons...\n")

reasons = Counter(); types = Counter(); samples = []
ok = 0; fail = 0
for r in b:
    rid = r.get("resend_id")
    if not rid:
        reasons["no_resend_id"] += 1; continue
    try:
        req = urllib.request.Request("https://api.resend.com/emails/" + rid,
                                     headers={"Authorization": f"Bearer {RK}", "User-Agent": UA})
        d = json.loads(urllib.request.urlopen(req, timeout=20).read())
        ok += 1
        bo = d.get("bounce") or {}
        btype = bo.get("type") or bo.get("subType") or d.get("last_event") or "?"
        msg = bo.get("message") or bo.get("description") or ""
        types[btype] += 1
        # classify message
        m = msg.lower()
        if not m: cat = "EMPTY(resend gave no message)"
        elif any(x in m for x in ["does not exist", "no such", "unknown", "5.1.1", "no mailbox", "recipient address rejected", "user unknown", "invalid recipient"]): cat = "mailbox_does_not_exist"
        elif any(x in m for x in ["spamhaus", "blocklist", "blocked", "listed"]): cat = "sender_blocklisted"
        elif any(x in m for x in ["spam", "policy", "reputation", "content"]): cat = "content_or_policy"
        elif any(x in m for x in ["full", "quota", "over quota"]): cat = "mailbox_full"
        elif any(x in m for x in ["greylist", "temporar", "try again", "deferred"]): cat = "temporary"
        else: cat = "other"
        reasons[cat] += 1
        if len(samples) < 16 and msg:
            samples.append((r["to_addr"][:32], btype, msg[:90]))
    except Exception as e:
        fail += 1
        reasons["api_lookup_failed"] += 1

print(f"resend lookups ok={ok} failed={fail}\n")
print("=== BOUNCE TYPE (resend) ===")
for t, n in types.most_common(): print(f"   {n:4d}  {t}")
print("\n=== ROOT-CAUSE (from resend message) ===")
for c, n in reasons.most_common(): print(f"   {n:4d}  {c}")
print("\n=== SAMPLE real messages ===")
for to, t, m in samples: print(f"   {to:32s} [{t}] {m}")
