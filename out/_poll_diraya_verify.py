# -*- coding: utf-8 -*-
"""Background poll: re-trigger Resend verification on the 10 Diraya senders and
watch until all read 'verified'. Prints ALL_VERIFIED when done (or TIMEOUT)."""
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

def domains():
    d = json.loads(urllib.request.urlopen(urllib.request.Request("https://api.resend.com/domains", headers=H), timeout=20).read())
    return [x for x in d.get("data", []) if "diraya" in x["name"]]

for i in range(30):                       # ~30 min max
    ds = domains()
    by = Counter(x.get("status") for x in ds)
    print(f"[{i:02d}] {dict(by)}", flush=True)
    if by.get("verified", 0) == 10:
        print("ALL_VERIFIED", flush=True); break
    # nudge any not-yet-verified
    for x in ds:
        if x.get("status") != "verified":
            try:
                urllib.request.urlopen(urllib.request.Request(
                    f"https://api.resend.com/domains/{x['id']}/verify", data=b"", method="POST", headers=H), timeout=15)
            except Exception:
                pass
    time.sleep(60)
else:
    print("TIMEOUT_STILL_PENDING", flush=True)
