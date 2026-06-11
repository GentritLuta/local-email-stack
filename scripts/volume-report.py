# -*- coding: utf-8 -*-
"""volume-report.py — one-glance volume check across BOTH profiles (Aureon + Diraya).

Answers "are both sending, and did the overnight harvest grow Diraya?" in a single
compact email: per profile -> sent 24h, delivery %, bounce %, today's cap utilisation
(sent vs warmup ceiling), queued pipeline, and the live lead-pool size. Diraya's lead
count is the headline (it's lead-supply bound). Sends to info@aureonglobal.de.

Scheduled one-time tomorrow ~18:00 local (after the 03:00 full-universe harvest + the
US business-day send batch). Run anytime:  py scripts/volume-report.py [--dry]
"""
from __future__ import annotations
import argparse, json, sys, datetime as dt, urllib.request, urllib.parse, urllib.error
from collections import Counter

import importlib.util
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
RK = load_profile("aureon").get("relay", {}).get("resend_api_key", "")
FROM = "Outreach Stack <reports@hi.aureonglobal.de>"
TO = ["info@aureonglobal.de"]
GOLD, DARK, MUT = "#d4af37", "#0a0a0a", "#94a3b8"


def get(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(U + path, headers=H), timeout=60).read())


def dom(a):
    a = (a or "").lower(); return a.split("@", 1)[1] if "@" in a else ""


def collect(slug, sends24, sent_today_dom, runs_by_seq, sid2p):
    p = load_profile(slug)
    doms = {d["domain"].lower() for d in p["relay"]["from_domains"]}
    rs = [s for s in sends24 if dom(s["from_addr"]) in doms]
    deliv = sum(1 for s in rs if s["delivered"] and not s["bounced"])
    bounced = sum(1 for s in rs if s["bounced"])
    cap = sum(daily_target_for_domain(p, d) for d in p["relay"]["from_domains"])
    sent_today = sum(sent_today_dom.get(d["domain"].lower(), 0) for d in p["relay"]["from_domains"])
    queued = sum(1 for r in runs_by_seq if r.get("status") == "queued" and sid2p.get(r["sequence_id"]) == slug)
    return {"slug": slug, "sent24": len(rs), "deliv": deliv, "bounced": bounced,
            "cap": cap, "sent_today": sent_today, "queued": queued,
            "leads": _count(f"prospects?profile_slug=eq.{slug}&select=id"),
            "leads_active": _count(f"prospects?profile_slug=eq.{slug}&verified=eq.true&unsubscribed=eq.false&select=id")}


def _count(path):
    req = urllib.request.Request(U + path + "&limit=1", headers={**H, "Prefer": "count=exact"})
    r = urllib.request.urlopen(req, timeout=30)
    cr = r.headers.get("content-range", "*/0")
    return int(cr.split("/")[-1]) if "/" in cr else 0


def pct(n, d):
    return f"{100*n/d:.0f}%" if d else "—"


def card(p):
    util = pct(p["sent_today"], p["cap"])
    full = p["sent_today"] >= p["cap"] and p["cap"] > 0
    color = "#16a34a" if (p["sent24"] > 0) else "#dc2626"
    status = "AT CAP" if full else ("SENDING" if p["sent24"] else "IDLE")
    return f"""<td style="padding:14px 18px;vertical-align:top;width:50%">
<div style="font-size:15px;font-weight:700;color:{DARK};text-transform:capitalize">{p['slug']}
<span style="font-size:11px;color:{color};font-weight:600;margin-left:6px">&#9679; {status}</span></div>
<table style="width:100%;border-collapse:collapse;margin-top:8px;font-size:13px">
<tr><td style="color:{MUT};padding:3px 0">Sent (24h)</td><td style="text-align:right;font-weight:700">{p['sent24']}</td></tr>
<tr><td style="color:{MUT};padding:3px 0">Delivered</td><td style="text-align:right">{pct(p['deliv'],p['sent24'])} &middot; bounce {pct(p['bounced'],p['sent24'])}</td></tr>
<tr><td style="color:{MUT};padding:3px 0">Today vs cap</td><td style="text-align:right;font-weight:700">{p['sent_today']}/{p['cap']} ({util})</td></tr>
<tr><td style="color:{MUT};padding:3px 0">Queued pipeline</td><td style="text-align:right">{p['queued']}</td></tr>
<tr><td style="color:{MUT};padding:3px 0">Lead pool (active)</td><td style="text-align:right;font-weight:700">{p['leads_active']} / {p['leads']}</td></tr>
</table></td>"""


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry", action="store_true"); a = ap.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    since24 = urllib.parse.quote((now - dt.timedelta(hours=24)).isoformat())
    midnight = urllib.parse.quote(now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat())
    sends24 = get(f"send_log?sent_at=gte.{since24}&select=from_addr,delivered,bounced&limit=10000")
    sent_today = Counter(dom(s["from_addr"]) for s in get(f"send_log?sent_at=gte.{midnight}&select=from_addr&limit=10000"))
    seqs = get("sequences?select=id,profile_slug"); sid2p = {s["id"]: s["profile_slug"] for s in seqs}
    runs = get("runs?status=eq.queued&select=status,sequence_id&limit=20000")
    au = collect("aureon", sends24, sent_today, runs, sid2p)
    dz = collect("diraya", sends24, sent_today, runs, sid2p)
    html = f"""<!doctype html><meta charset="utf-8"><body style="margin:0;background:#f5f5f5;font-family:Inter,Segoe UI,sans-serif">
<table width="100%" style="padding:22px 12px"><tr><td align="center">
<table width="660" style="max-width:660px;width:100%">
<tr><td style="background:{DARK};border-top:3px solid {GOLD};padding:18px 22px;border-radius:6px 6px 0 0">
<div style="color:{GOLD};font-weight:700;font-size:16px">Daily Volume Check &mdash; Aureon + Diraya</div>
<div style="color:{MUT};font-size:11px;letter-spacing:1px;margin-top:4px">{now.strftime('%A %B %d, %Y &middot; %H:%M UTC')}</div></td></tr>
<tr><td style="background:#fff;border:1px solid #e5e7eb;border-top:0;border-radius:0 0 6px 6px">
<table style="width:100%;border-collapse:collapse"><tr>{card(au)}{card(dz)}</tr></table>
<div style="padding:10px 18px 16px;font-size:12px;color:#475569;border-top:1px solid #eef2f7">
Aureon is warmup-capped ({au['cap']}/day, ramping). Diraya is lead-bound &mdash; pool now <b>{dz['leads']}</b>
(was 11 yesterday); the 03:00 full-YC sweep grows it toward the {dz['cap']}/day cap.</div>
</td></tr></table></td></tr></table></body>"""
    subj = f"Volume: Aureon {au['sent24']} sent ({pct(au['deliv'],au['sent24'])} deliv) · Diraya {dz['sent24']} · {dz['leads']} leads"
    if a.dry:
        print(subj); print(f"aureon={au['sent24']}/24h cap {au['sent_today']}/{au['cap']} | diraya={dz['sent24']}/24h leads={dz['leads']}")
        return 0
    payload = {"from": FROM, "to": TO, "subject": subj, "html": html,
               "tags": [{"name": "kind", "value": "volume_report"}]}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(),
                                 method="POST", headers={"Authorization": "Bearer " + RK,
                                 "Content-Type": "application/json", "User-Agent": "les volume/1.0"})
    try:
        print("sent:", json.loads(urllib.request.urlopen(req, timeout=30).read()).get("id"), "to", TO)
    except urllib.error.HTTPError as e:
        print("! failed", e.code, e.read().decode()[:160]); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
