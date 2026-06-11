# -*- coding: utf-8 -*-
"""Gentle WATCH-ONLY poll for the 6 Spaceship-NS Diraya senders. Deliberately does
NOT call /verify (repeated nudges may have been resetting SES's DKIM-check clock).
Just polls status every 10 min and reports ALL6_VERIFIED when SES finishes on its own."""
import json, time, urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(r"C:\Users\bernh\local-email-stack")
env = {}
for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
H = {"Authorization": "Bearer " + env["RESEND_NEW_ACCOUNT_API_KEY"], "User-Agent": "les-diraya/1.0"}
SP = ("diraya.biz", "diraya-agency.shop", "diraya-marketing.shop")

def domains():
    d = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.resend.com/domains", headers=H), timeout=20).read())
    return [x for x in d.get("data", []) if "diraya" in x["name"] and any(x["name"].endswith(r) for r in SP)]

for i in range(20):                       # ~3.3h at 600s, no nudging
    try:
        by = Counter(x.get("status") for x in domains())
        print(f"[{i:02d}] {dict(by)}", flush=True)
        if by.get("verified", 0) == 6:
            print("ALL6_VERIFIED", flush=True); break
    except Exception as e:
        print(f"[{i:02d}] err {e}", flush=True)
    time.sleep(600)
else:
    print("STILL_PENDING_AFTER_GENTLE_WATCH", flush=True)
