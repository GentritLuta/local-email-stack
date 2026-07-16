# -*- coding: utf-8 -*-
"""One-time: create + seed the global suppression list, then enforce it on current rows.

Seeds: every genuine replier (replies.class='reply'), every already-unsubscribed
prospect, the teamminik.com domain (a former client), and the specific addresses the
operator named. Then, for every suppressed email, sets unsubscribed=true on all its
prospect rows (so the existing send/enroll enforcement blocks them immediately) and
cancels any queued/running runs. Idempotent.
"""
import sys, json, urllib.request, urllib.parse
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sequences"))
import clarity_gate as cg   # for the management-API SQL runner
import suppress

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

env = {}
for ln in open(Path(__file__).resolve().parent.parent / "sequences" / "supabase.env"):
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.split("=", 1); env[k.strip()] = v.strip()
U = env["SUPABASE_URL"].rstrip("/"); K = env["SUPABASE_ANON_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "User-Agent": "les-seed/1.0"}
HW = {**H, "Content-Type": "application/json", "Prefer": "return=representation"}


def g(p):
    out, s = [], 0
    while True:
        sep = "&" if "?" in p else "?"
        c = json.loads(urllib.request.urlopen(urllib.request.Request(
            f"{U}/rest/v1/{p}{sep}limit=1000&offset={s}", headers=H), timeout=90).read())
        out += c
        if len(c) < 1000:
            break
        s += 1000
    return out


def patch(path, body):
    return json.loads(urllib.request.urlopen(urllib.request.Request(
        f"{U}/rest/v1/{path}", data=json.dumps(body).encode(), method="PATCH", headers=HW),
        timeout=90).read() or b"[]")


# 1. create table + indexes (management API; needs a User-Agent or Cloudflare 1010s)
print("creating suppression table ...")
cg._sql("""
CREATE TABLE IF NOT EXISTS suppression (
  value text PRIMARY KEY,
  vtype text NOT NULL CHECK (vtype IN ('email','domain')),
  reason text,
  created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_suppression_vtype ON suppression(vtype);
ALTER TABLE suppression ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS suppression_service_all ON suppression;
CREATE POLICY suppression_service_all ON suppression FOR ALL TO service_role USING (true) WITH CHECK (true);
""")
print("  table ready")

# 2. gather everything to suppress
DOMAINS = {"teamminik.com"}
NAMED = {"ryan@mnrealestateteam.com", "michelle@teamminik.com", "austin@mynexthomeelite.com"}
repliers = {(r.get("from_addr") or "").lower() for r in g("replies?class=eq.reply&select=from_addr")
            if r.get("from_addr")}
unsub_now = {(p.get("email") or "").lower() for p in g("prospects?unsubscribed=eq.true&select=email")
             if p.get("email")}
emails = {e for e in (repliers | unsub_now | NAMED) if "@" in e}
print(f"\nseeding: {len(emails)} emails ({len(repliers)} repliers + {len(unsub_now)} prior opt-outs + named), "
      f"{len(DOMAINS)} domains")

for d in DOMAINS:
    suppress.add_domain(d, "former client / blocked domain")
for e in sorted(emails):
    reason = "blocked domain" if e.split("@")[-1] in DOMAINS else (
        "opted out" if e in unsub_now else "replied")
    suppress.add_email(e, reason)

sup = suppress.load_suppressed()
print(f"  suppression now holds {len(sup['emails'])} emails + {len(sup['domains'])} domains")

# 3. enforce on CURRENT rows: unsubscribe every prospect row whose email/domain is suppressed,
#    and cancel their non-terminal runs (so the existing send/enroll checks block them today)
seq = g("sequences?select=id,profile_slug")
pr = g("prospects?select=id,email,profile_slug,unsubscribed")
targets = [p for p in pr if suppress.is_suppressed(p.get("email"), sup)]
to_unsub = [p for p in targets if not p.get("unsubscribed")]
print(f"\nprospect rows matching suppression: {len(targets)}  (need unsubscribe: {len(to_unsub)})")

ids = [p["id"] for p in to_unsub]
for i in range(0, len(ids), 50):
    batch = ",".join(ids[i:i+50])
    patch(f"prospects?id=in.({batch})", {"unsubscribed": True})
print(f"  unsubscribed {len(ids)} rows")

# cancel any queued/running runs for suppressed prospects
allpids = {p["id"] for p in targets}
runs = [r for r in g("runs?status=in.(queued,running)&select=id,prospect_id")
        if r["prospect_id"] in allpids]
rids = [r["id"] for r in runs]
for i in range(0, len(rids), 50):
    batch = ",".join(rids[i:i+50])
    patch(f"runs?id=in.({batch})", {"status": "cancelled"})
print(f"  cancelled {len(rids)} active runs for suppressed prospects")

# 4. sanity: the three named must be fully covered
print("\nverify named:")
for e in sorted(NAMED):
    supd = suppress.is_suppressed(e, suppress.load_suppressed())
    rows = [p for p in pr if (p.get("email") or "").lower() == e]
    print(f"  {e:34} suppressed={supd}  prospect_rows={len(rows)}")
print("\nDONE")
