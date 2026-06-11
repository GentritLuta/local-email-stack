# -*- coding: utf-8 -*-
"""_todo_live_audit.py - one-shot live audit for the 2026-06-05 todo.

Pulls REAL state from Supabase (not config) for aureon + diraya:
  - sends today + last 7d, per sending subdomain, vs the 12x15 target
  - reply counts by class (reply/bounce/complaint/unrelated) last 7d/30d
  - whether replies are matched to runs and whether runs got paused
  - run status distribution per profile
Read-only. No writes, no sends.
"""
from __future__ import annotations
import datetime as dt, json, sys, urllib.parse, urllib.request
from collections import Counter, defaultdict
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"].rstrip("/"); KEY = env["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

def fetch(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def dom(addr: str) -> str:
    a = (addr or "").lower(); return a.split("@", 1)[1] if "@" in a else "(none)"

now = dt.datetime.now(dt.timezone.utc)
today0 = now.strftime("%Y-%m-%dT00:00:00Z")
since7 = (now - dt.timedelta(days=7)).isoformat()
since30 = (now - dt.timedelta(days=30)).isoformat()

# Load profile domain sets to attribute sends to a brand.
def prof_domains(slug: str) -> set:
    p = json.loads((REPO / "profiles" / f"{slug}.json").read_text(encoding="utf-8"))
    return {d["domain"].lower() for d in p.get("relay", {}).get("from_domains", [])}

AUREON_D = prof_domains("aureon")
DIRAYA_D = prof_domains("diraya")

print("=" * 72)
print(f"LIVE AUDIT  {now:%Y-%m-%d %H:%M UTC}")
print("=" * 72)

# ---- Sends today + 7d, per subdomain ----
sends7 = fetch(f"send_log?sent_at=gte.{urllib.parse.quote(since7)}"
               f"&select=from_addr,sent_at,bounced,replied,delivered,error&limit=20000")
today_by_dom = Counter()
d7_by_dom = Counter()
for s in sends7:
    d = dom(s.get("from_addr"))
    d7_by_dom[d] += 1
    if (s.get("sent_at") or "") >= today0:
        today_by_dom[d] += 1

def report_brand(name: str, domains: set):
    print(f"\n--- {name}: {len(domains)} configured subdomains ---")
    print(f"{'subdomain':38} {'today':>6} {'7d':>6}")
    active = 0
    for d in sorted(domains):
        t = today_by_dom.get(d, 0); w = d7_by_dom.get(d, 0)
        if t > 0: active += 1
        flag = "" if t >= 15 else ("  <15" if t > 0 else "  IDLE")
        print(f"{d:38} {t:>6} {w:>6}{flag}")
    # sends from domains NOT in the configured set (drift)
    extras = sorted(set(today_by_dom) - domains - {"(none)"})
    extras = [e for e in extras if any(part in e for part in name.lower().split())]
    print(f"  -> {active}/{len(domains)} subdomains sent today; target = 12 subdomains x 15/day")
    print(f"  -> total today across configured: {sum(today_by_dom.get(d,0) for d in domains)}  (target 180)")

report_brand("aureon", AUREON_D)
report_brand("diraya", DIRAYA_D)

# all sending domains seen today (catch drift / unexpected senders)
print("\n--- ALL sending subdomains seen today (drift check) ---")
for d, c in today_by_dom.most_common():
    tag = "aureon" if d in AUREON_D else ("diraya" if d in DIRAYA_D else "OTHER")
    print(f"  {d:38} {c:>5}  [{tag}]")

# ---- Replies ----
print("\n" + "=" * 72)
print("REPLIES (replies table)")
print("=" * 72)
rep7 = fetch(f"replies?received_at=gte.{urllib.parse.quote(since7)}"
             f"&select=class,run_id,from_addr,to_addr,subject,received_at&order=received_at.desc&limit=2000")
cls = Counter(r.get("class") for r in rep7)
matched = sum(1 for r in rep7 if r.get("run_id"))
print(f"last 7d: {len(rep7)} inbound rows  classes={dict(cls)}  matched_to_run={matched}")
real = [r for r in rep7 if r.get("class") == "reply"]
print(f"  genuine prospect replies (class=reply): {len(real)}")
for r in real[:15]:
    print(f"    {(r.get('from_addr') or '')[:38]:38} | {(r.get('subject') or '')[:40]}")

# ---- Run statuses ----
print("\n" + "=" * 72)
print("RUN STATUS distribution")
print("=" * 72)
for slug in ("aureon", "diraya"):
    try:
        seqs = fetch(f"sequences?profile_slug=eq.{slug}&select=id")
        sids = [s["id"] for s in seqs]
        if not sids:
            print(f"  {slug:10}: (no sequence rows)"); continue
        idlist = ",".join(str(s) for s in sids)
        runs = fetch(f"runs?sequence_id=in.({idlist})&select=status&limit=20000")
        c = Counter(r.get("status") for r in runs)
        print(f"  {slug:10}: total={len(runs)} {dict(c)}")
    except Exception as e:
        print(f"  {slug:10}: (query failed: {e})")
print("\nDONE.")
