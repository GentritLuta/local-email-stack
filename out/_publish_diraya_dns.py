# -*- coding: utf-8 -*-
"""Publish the Resend DKIM/SPF/MX records for the 10 Diraya senders onto their 5
Spaceship roots — ADDITIVELY, without clobbering existing records (diraya.biz
hosts a live Webflow site + Google email).

  py out/_publish_diraya_dns.py --test    # determine PUT semantics on empty cleardiraya.com
  py out/_publish_diraya_dns.py           # publish all 5 roots (uses the safe method)
"""
import json, sys, time, urllib.request, urllib.error
from pathlib import Path

REPO = Path(r"C:\Users\bernh\local-email-stack")
env = {}
for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
KEY, SEC = env["SPACESHIP_API_KEY"], env["SPACESHIP_API_SECRET"]
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
H = {"X-API-Key": KEY, "X-API-Secret": SEC, "Content-Type": "application/json", "User-Agent": UA}
BASE = "https://spaceship.dev/api/v1"
TTL = 3600

ALL = json.loads((REPO / "out" / "diraya-dns-export" / "_all_records.json").read_text(encoding="utf-8"))

def to_ss(rec):
    t = rec["type"]; o = {"type": t, "name": rec["name"], "ttl": TTL}
    if t == "MX":
        o["exchange"] = rec["value"]; o["preference"] = int(rec.get("priority") or 10)
    else:
        o["value"] = rec["value"]
    return o

def get(domain):
    r = urllib.request.Request(f"{BASE}/dns/records/{domain}?take=500&skip=0", headers=H)
    return json.loads(urllib.request.urlopen(r, timeout=30).read()).get("items", [])

def put(domain, items, force=True):
    body = json.dumps({"force": force, "items": items}).encode()
    r = urllib.request.Request(f"{BASE}/dns/records/{domain}", data=body, method="PUT", headers=H)
    try:
        resp = urllib.request.urlopen(r, timeout=30)
        return resp.status, resp.read().decode()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]

if "--test" in sys.argv:
    d = "cleardiraya.com"
    recs = [to_ss(r) for r in ALL[d]]
    print(f"SEMANTICS TEST on {d} (currently {len(get(d))} records)")
    print("  PUT first 3...", put(d, recs[:3])); time.sleep(1)
    a = len(get(d)); print(f"  -> now {a} records")
    print("  PUT next 3 ...", put(d, recs[3:])); time.sleep(1)
    b = len(get(d)); print(f"  -> now {b} records")
    if b == 6:
        print("\nRESULT: PUT is ADDITIVE (merges). Safe to send only the 6 new records per root.")
    elif b == 3:
        print("\nRESULT: PUT REPLACES the zone. Must merge existing+new. Re-publishing all 6 to cleardiraya...")
        print("  ", put(d, recs)); print(f"  -> now {len(get(d))} records")
    else:
        print(f"\nRESULT: unexpected ({b}). Inspect manually before publishing live domains.")
    sys.exit(0)

# ---- PUBLISH (default) ----
ADDITIVE = "--replace" not in sys.argv  # default assume additive (confirmed by --test)
for d in ["cleardiraya.com", "dirayaget.com", "diraya.biz", "diraya-agency.shop", "diraya-marketing.shop"]:
    existing = get(d)
    new = [to_ss(r) for r in ALL[d]]
    # skip ones already present (same type+name+value/exchange)
    def keyf(x): return (x["type"], x["name"], x.get("value") or x.get("exchange"))
    have = {keyf(e) for e in existing}
    missing = [n for n in new if keyf(n) not in have]
    if not missing:
        print(f"{d:26} already has all 6 Resend records — skip"); continue
    items = missing if ADDITIVE else (existing + missing)
    st, msg = put(d, items, force=True)
    after = get(d)
    print(f"{d:26} +{len(missing)} resend recs -> PUT {st} | now {len(after)} total")
    time.sleep(0.6)
print("\nDONE publishing. Verify in Resend next.")
