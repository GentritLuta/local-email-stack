"""Pull the LIVE aureon sequence copy (what prospects actually receive) from the
DB — the runner reads inline_subject/body or the linked variant, so this shows
the real E1..E7."""
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

seqs = get("sequences?profile_slug=eq.aureon&select=id,slug,name")
print("aureon sequences:", [(s["slug"], s["id"][:8]) for s in seqs])
for s in seqs:
    steps = get(f"sequence_steps?sequence_id=eq.{s['id']}&select=step_n,delay_days,inline_subject,inline_body,variants(subject,body)&order=step_n.asc")
    if not steps: continue
    print(f"\n===== sequence '{s['slug']}' ({len(steps)} steps) =====")
    for st in steps:
        subj = st.get("inline_subject") or (st.get("variants") or {}).get("subject") or "(none)"
        body = st.get("inline_body") or (st.get("variants") or {}).get("body") or "(none)"
        print(f"\n--- STEP {st['step_n']} (delay {st.get('delay_days')}d) ---")
        print(f"SUBJECT: {subj}")
        print("BODY:")
        print(body)
