# -*- coding: utf-8 -*-
import httpx
from pathlib import Path
env = {}
for ln in (Path(__file__).resolve().parent.parent / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.split("=", 1); env[k.strip()] = v.strip()
cf = env.get("CF_API_TOKEN", "")
H = {"Authorization": "Bearer " + cf, "Content-Type": "application/json"}
names = ["getalgoalpha.com", "getalgoalpha.io", "getalgoalpha.co", "getalgoalpha.net", "getalgoalpha.app", "getalgoalpha.xyz"]
with httpx.Client(timeout=20) as c:
    for name in names:
        z = c.get(f"https://api.cloudflare.com/client/v4/zones?name={name}", headers=H)
        res = z.json().get("result", []) if z.status_code == 200 else []
        line = f"{name:<20} status={z.status_code} found={len(res)}"
        if res:
            line += f"  zone_id={res[0]['id']} ({res[0]['status']})"
        print(line)
    allz = c.get("https://api.cloudflare.com/client/v4/zones?per_page=50", headers=H).json().get("result", [])
    print("TOTAL zones token can see:", len(allz))
    for zz in allz:
        print("  ", zz["name"], zz["status"], zz["id"])
