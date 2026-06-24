# -*- coding: utf-8 -*-
"""_brand-send-counts.py — read-only: count today's sends per brand (by sending domain).

Used to verify the round-robin runner fairness fix: run once for a baseline, then
again after the next runner tick to confirm mark-eting / energ ramp up.
No emails sent, no writes.  Usage: py scripts/_brand-send-counts.py
"""
from __future__ import annotations
import json, sys, datetime as dt, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from profile_lib import load_profile  # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

env = {}
for ln in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.split("=", 1); env[k.strip()] = v.strip()
U = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"; K = env["SUPABASE_ANON_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K}


def get(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(U + path, headers=H), timeout=90).read())


def dom(a):
    a = (a or "").lower(); return a.split("@", 1)[1] if "@" in a else ""


# build sending-domain -> brand map from every profile json
dom2brand = {}
brands = []
for pj in sorted((REPO / "profiles").glob("*.json")):
    slug = pj.stem
    try:
        p = load_profile(slug)
    except Exception:
        continue
    active = p.get("active", True)
    brands.append(slug)
    for d in p.get("relay", {}).get("from_domains", []):
        dom2brand[d["domain"].lower()] = slug

# today's send_log rows (UTC date)
today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
rows = get(f"send_log?sent_at=gte.{today}T00:00:00&select=from_addr,sent_at&limit=20000")

counts = {}
unmapped = 0
for r in rows:
    b = dom2brand.get(dom(r["from_addr"]))
    if b is None:
        unmapped += 1
        continue
    counts[b] = counts.get(b, 0) + 1

print(f"=== sends today (UTC {today}) — total rows: {len(rows)} ===")
for b in sorted(counts, key=lambda x: -counts[x]):
    flag = "  <== watch" if b in ("mark-eting", "energ") else ""
    print(f"  {b:<22} {counts[b]:>5}{flag}")
if unmapped:
    print(f"  (unmapped from_addr domains: {unmapped})")
for w in ("mark-eting", "energ"):
    if w not in counts:
        print(f"  {w:<22}     0  <== watch")
print(f"stamp: {dt.datetime.now().strftime('%H:%M:%S')} local")
