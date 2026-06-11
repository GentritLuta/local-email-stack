# -*- coding: utf-8 -*-
"""_all-volume-check.py — read-only 24h send volume across EVERY profile.

Ad-hoc diagnostic for the daily todo: prints per-profile sent(24h), delivered%,
bounce%, today-vs-cap, queued pipeline, and active lead pool. Covers all profiles
in profiles/*.json (active ones first), not just the two volume-report.py hardcodes.
"""
from __future__ import annotations
import json, sys, datetime as dt, urllib.request, urllib.parse
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from profile_lib import load_profile, daily_target_for_domain  # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

env = {}
for ln in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.split("=", 1); env[k.strip()] = v.strip()
U = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"; K = env["SUPABASE_ANON_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K}


def get(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(U + path, headers=H), timeout=60).read())


def _count(path):
    req = urllib.request.Request(U + path + "&limit=1", headers={**H, "Prefer": "count=exact"})
    r = urllib.request.urlopen(req, timeout=30)
    cr = r.headers.get("content-range", "*/0")
    return int(cr.split("/")[-1]) if "/" in cr else 0


def dom(a):
    a = (a or "").lower(); return a.split("@", 1)[1] if "@" in a else ""


def pct(n, d):
    return f"{100*n/d:.0f}%" if d else "-"


def main():
    slugs = sorted(p.stem for p in (REPO / "profiles").glob("*.json")
                   if ".private" not in p.name and ".bak" not in p.name and p.stem != "_schema")
    now = dt.datetime.now(dt.timezone.utc)
    since24 = urllib.parse.quote((now - dt.timedelta(hours=24)).isoformat())
    midnight = urllib.parse.quote(now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat())
    sends24 = get(f"send_log?sent_at=gte.{since24}&select=from_addr,delivered,bounced&limit=20000")
    sent_today = Counter(dom(s["from_addr"]) for s in get(f"send_log?sent_at=gte.{midnight}&select=from_addr&limit=20000"))
    seqs = get("sequences?select=id,profile_slug"); sid2p = {s["id"]: s["profile_slug"] for s in seqs}
    runs = get("runs?status=eq.queued&select=status,sequence_id&limit=50000")

    print(f"{'profile':<18}{'active':<8}{'sent24':>7}{'deliv':>7}{'bounce':>7}{'today/cap':>12}{'queued':>8}{'leads(act)':>12}")
    print("-" * 82)
    rows = []
    for slug in slugs:
        try:
            p = load_profile(slug)
        except Exception as e:
            print(f"{slug:<18} ERROR {e}"); continue
        doms = {d["domain"].lower() for d in p.get("relay", {}).get("from_domains", [])}
        rs = [s for s in sends24 if dom(s["from_addr"]) in doms]
        deliv = sum(1 for s in rs if s["delivered"] and not s["bounced"])
        bounced = sum(1 for s in rs if s["bounced"])
        try:
            cap = sum(daily_target_for_domain(p, d) for d in p.get("relay", {}).get("from_domains", []))
        except Exception:
            cap = 0
        st = sum(sent_today.get(d, 0) for d in doms)
        queued = sum(1 for r in runs if sid2p.get(r["sequence_id"]) == slug)
        leads_act = _count(f"prospects?profile_slug=eq.{slug}&verified=eq.true&unsubscribed=eq.false&select=id")
        leads = _count(f"prospects?profile_slug=eq.{slug}&select=id")
        rows.append((slug, p.get("active", False), len(rs), deliv, bounced, st, cap, queued, leads_act, leads))

    rows.sort(key=lambda r: (not r[1], -r[2]))
    for (slug, active, s24, dv, bn, st, cap, q, la, lt) in rows:
        a = "yes" if active else "no"
        print(f"{slug:<18}{a:<8}{s24:>7}{pct(dv,s24):>7}{pct(bn,s24):>7}{f'{st}/{cap}':>12}{q:>8}{f'{la}/{lt}':>12}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
