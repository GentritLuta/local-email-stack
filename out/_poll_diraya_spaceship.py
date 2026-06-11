# -*- coding: utf-8 -*-
"""Robust poll: watch ONLY the 6 Spaceship-NS Diraya senders (the 3 roots that are
correctly delegated) until all read 'verified'. Transient socket/network errors are
swallowed so a single DNS-filter blip cannot kill the run. Re-nudges each cycle.
Prints ALL6_VERIFIED when done, or TIMEOUT_STILL_PENDING."""
import json, time, urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(r"C:\Users\bernh\local-email-stack")
env = {}
for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
KEY = env["RESEND_NEW_ACCOUNT_API_KEY"]
H = {"Authorization": "Bearer " + KEY, "User-Agent": "les-diraya/1.0", "Content-Type": "application/json"}
SPACESHIP = ("diraya.biz", "diraya-agency.shop", "diraya-marketing.shop")

def domains():
    d = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.resend.com/domains", headers=H), timeout=20).read())
    return [x for x in d.get("data", []) if "diraya" in x["name"] and any(x["name"].endswith(r) for r in SPACESHIP)]

for i in range(60):                       # ~2h max at 120s cadence
    try:
        ds = domains()
    except Exception as e:
        print(f"[{i:02d}] transient: {e}", flush=True); time.sleep(120); continue
    by = Counter(x.get("status") for x in ds)
    print(f"[{i:02d}] {dict(by)}", flush=True)
    if by.get("verified", 0) == len(ds) == 6:
        print("ALL6_VERIFIED", flush=True); break
    for x in ds:
        if x.get("status") != "verified":
            try:
                urllib.request.urlopen(urllib.request.Request(
                    f"https://api.resend.com/domains/{x['id']}/verify", data=b"", method="POST", headers=H), timeout=15)
            except Exception:
                pass
    time.sleep(120)
else:
    print("TIMEOUT_STILL_PENDING", flush=True)
