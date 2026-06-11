"""One-off: backfill send_log.subject for rows that still contain literal
'{company}' / '{first_name}' / etc. by re-rendering against the prospect
row referenced by the run. Fix for the bug where sequence-runner logged
the UNRENDERED template subject while sending the rendered one to Resend
- which broke reply-matching by recipient+subject for every reply ever
received.
"""
from __future__ import annotations
import json, re, urllib.request, urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in open(REPO / "sequences" / "supabase.env"):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H_R = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
H_W = {**H_R, "Content-Type": "application/json", "Prefer": "return=minimal"}

TAG_RX = re.compile(r"\{([a-z_][a-z0-9_]*)\}")


def get(path):
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H_R), timeout=20).read())


def patch(path, body):
    req = urllib.request.Request(
        f"{URL}/rest/v1/{path}", method="PATCH",
        data=json.dumps(body).encode(), headers=H_W)
    urllib.request.urlopen(req, timeout=20).read()


# Pull every send_log row whose subject contains an unrendered tag
rows = get("send_log?subject=like.*%7B*&select=id,run_id,to_addr,subject")
print(f"rows with unrendered tags: {len(rows)}")

# For each, find the prospect via runs → prospect_id → prospects
fixed = 0
unfixed = 0
sample_unfixed = []
for r in rows:
    rid = r.get("run_id")
    if not rid:
        unfixed += 1; continue
    runs = get(f"runs?id=eq.{rid}&select=prospect_id")
    if not runs:
        unfixed += 1; continue
    pid = runs[0].get("prospect_id")
    if not pid:
        unfixed += 1; continue
    prosp = get(f"prospects?id=eq.{pid}&select=first_name,last_name,company,city,state,title,email,website")
    if not prosp:
        unfixed += 1; continue
    p = prosp[0]
    new_subj = r["subject"]
    # Substitute every known tag, leave unknown literal (so we can spot them)
    def repl(m):
        tag = m.group(1)
        val = p.get(tag)
        if val is None or not str(val).strip():
            return m.group(0)  # leave the literal {tag}
        return str(val)
    new_subj = TAG_RX.sub(repl, new_subj)
    if new_subj == r["subject"]:
        unfixed += 1
        if len(sample_unfixed) < 5:
            sample_unfixed.append((r["id"], r["subject"], p))
        continue
    patch(f"send_log?id=eq.{r['id']}", {"subject": new_subj})
    fixed += 1

print(f"fixed: {fixed}")
print(f"unfixed: {unfixed}")
if sample_unfixed:
    print("first 5 unfixed (prospect data may not have the merge field):")
    for sid, subj, p in sample_unfixed:
        print(f"  {sid[:8]}  subj={subj[:60]}  prospect={p}")
