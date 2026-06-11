# -*- coding: utf-8 -*-
"""smtp-pool-verify.py — daily deliverability gate (scheduled before enrollment).

The scrapers run --no-smtp (MX-only) for speed, which can't tell a real mailbox
from a dead one or a catch-all — that is what drove the bounces. This pass does a
REAL SMTP RCPT probe on the freshest eligible prospects per profile and HARD-
suppresses only mailboxes that definitively do not exist.

Safe-suppression policy (avoid false positives from residential-IP probing):
  - no_mx / malformed / invalid_syntax / disposable / placeholder  -> suppress
  - smtp_rejected with RCPT code 550/551/553 (mailbox doesn't exist) -> suppress
  - 554 / 4xx soft-fail / probe-failed / mx_verified / smtp_verified -> KEEP
    (554 is usually policy/IP-block, not a dead mailbox; soft-fails are temporary)

Runs as LES-smtp-pool-verify daily at 09:00, before LES-daily-fill-and-enroll.
"""
import re
import sys
import json
import urllib.request
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

# Deterministic, DNS-independent "definitely junk" methods only. NOT no_mx — a
# resolver blip returns no_mx for a perfectly live domain, which would falsely
# suppress whole brokerages. Truly-dead domains bounce Permanent at send time and
# the webhook suppresses them then.
HARD = {"invalid_syntax", "malformed", "disposable", "placeholder"}
DEAD_RCPT = {550, 551, 553}   # mailbox does not exist; 554 (policy/IP-block) excluded
CAP = 250                      # freshest N per profile per run

import time

def _retry(fn, tries=4):
    """Survive transient DNS/network blips (getaddrinfo failed, timeouts) — the
    heavy MX-lookup load can momentarily starve the resolver. Back off + retry;
    never raise, so one failed call can't kill the whole sweep."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if i == tries - 1:
                print("  net error (skipped):", str(e)[:70], flush=True)
                return None
            time.sleep(2 ** i)

def g(p):
    r = _retry(lambda: json.loads(urllib.request.urlopen(
        urllib.request.Request(B + p, headers=H), timeout=40).read()))
    return r if r is not None else []

def suppress(pid):
    _retry(lambda: urllib.request.urlopen(urllib.request.Request(
        B + "prospects?id=eq." + pid, data=json.dumps({"verified": False, "unsubscribed": True}).encode(),
        method="PATCH", headers={**H, "Prefer": "return=minimal"}), timeout=30))

def should_suppress(v) -> bool:
    if v.method in HARD:
        return True
    if v.method == "smtp_rejected":
        m = re.search(r"RCPT (\d{3})", v.error or "")
        return bool(m) and int(m.group(1)) in DEAD_RCPT
    return False

for prof in ("aureon", "algoalpha"):
    rows = g(f"prospects?profile_slug=eq.{prof}&verified=eq.true&unsubscribed=eq.false"
             f"&select=id,email&order=created_at.desc&limit={CAP}")
    res = Counter(); killed = 0
    for r in rows:
        try:
            v = verify(r["email"], do_smtp_probe=True, do_catchall_probe=False)
        except Exception:
            res["error"] += 1; continue
        res[v.method] += 1
        if should_suppress(v):
            suppress(r["id"]); killed += 1
    print(f"[{prof}] checked {len(rows)} | suppressed {killed} dead | methods={dict(res)}", flush=True)
print("POOL-VERIFY DONE", flush=True)
