# -*- coding: utf-8 -*-
"""One-time pre-ramp pool clean: SMTP-verify (real RCPT probe, not MX-only) the
eligible aureon + algoalpha prospects and HARD-SUPPRESS the dead mailboxes
(smtp_rejected) and dead domains (no_mx). This is what the --no-smtp scrapers
never did. Bounded per profile so it finishes in a sane time."""
import sys, json, urllib.request, urllib.parse
from collections import Counter
from pathlib import Path
REPO = Path(r"C:\Users\bernh\local-email-stack")
sys.path.insert(0, str(REPO / "sequences"))
from lead_verify import verify  # noqa: E402

env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
B = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
K = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
H = {"apikey": K, "Authorization": "Bearer " + K, "Content-Type": "application/json"}

def g(p): return json.loads(urllib.request.urlopen(urllib.request.Request(B + p, headers=H), timeout=40).read())
def patch(pid, body):
    urllib.request.urlopen(urllib.request.Request(B + "prospects?id=eq." + pid, data=json.dumps(body).encode(),
                           method="PATCH", headers={**H, "Prefer": "return=minimal"}), timeout=30)

CAP = 250  # per profile
for prof in ("aureon", "algoalpha"):
    rows = g(f"prospects?profile_slug=eq.{prof}&verified=eq.true&unsubscribed=eq.false"
             f"&select=id,email&order=created_at.desc&limit={CAP}")
    res = Counter(); suppressed = 0
    for r in rows:
        try:
            v = verify(r["email"], do_smtp_probe=True, do_catchall_probe=False)
        except Exception as e:
            res["error"] += 1; continue
        res[v.method] += 1
        if v.method in ("smtp_rejected", "no_mx", "invalid_syntax", "malformed", "disposable", "placeholder"):
            patch(r["id"], {"verified": False, "unsubscribed": True}); suppressed += 1
    print(f"[{prof}] checked {len(rows)} | suppressed {suppressed} | methods={dict(res)}", flush=True)
print("SWEEP DONE", flush=True)
