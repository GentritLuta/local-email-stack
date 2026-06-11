# -*- coding: utf-8 -*-
"""diraya-report.py — daily ops report for the Diraya pilot, AS DETAILED as the
Aureon (daily-report.py) report, scoped to Diraya. Reuses daily-report.py's render
+ intent helpers so the two stay consistent. Sections: headline KPIs, 24h/7d/30d
window table, reply-intent breakdown, per-step funnel, subdomain health (Diraya's
10 senders), persona head-to-head, pipeline, recent replies, alerts.

Sends FROM "Diraya Ops <reports@team.diraya.biz>" on the Pro Resend account TO
amoura.ma@diraya.ca + info@aureonglobal.de. Schedule: LES-diraya-report daily 08:00.

  py scripts/diraya-report.py            # send to both
  py scripts/diraya-report.py --dry      # print, no send
  py scripts/diraya-report.py --to X@y   # override recipients
"""
from __future__ import annotations
import argparse, importlib.util, json, sys, datetime as dt, urllib.request, urllib.parse, urllib.error
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from profile_lib import load_profile  # noqa
# Reuse the Aureon report's render + intent helpers (kept DRY so both look the same).
_spec = importlib.util.spec_from_file_location("dr", REPO / "scripts" / "daily-report.py")
dr = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(dr)  # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"].rstrip("/"); KEY = env["SUPABASE_ANON_KEY"]
H_R = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

DIRAYA = load_profile("diraya")
RK = DIRAYA.get("relay", {}).get("resend_api_key", "")               # Pro account key
DIRAYA_DOMAINS = {d["domain"].lower() for d in DIRAYA.get("relay", {}).get("from_domains", [])}
DIRAYA_PERSONAS = {p["slug"]: p for p in DIRAYA.get("personas", [])}
RECIPIENTS = ["amoura.ma@diraya.ca", "info@aureonglobal.de"]
FROM = "Diraya Ops <reports@team.diraya.biz>"
ORANGE = "#FF6B00"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123 Safari/537.36"


def supa_get(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H_R)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def _dom(addr: str) -> str:
    a = (addr or "").lower(); return a.split("@", 1)[1] if "@" in a else ""


def fetch() -> dict:
    since30 = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
    s30 = urllib.parse.quote(since30)
    sends = supa_get(f"send_log?sent_at=gte.{s30}&select=resend_id,run_id,step_n,persona_slug,"
                     f"from_addr,to_addr,subject,delivered,bounced,replied,complained,opened_at,"
                     f"clicked_at,sent_at,error&order=sent_at.desc&limit=10000")
    sends = [s for s in sends if _dom(s.get("from_addr")) in DIRAYA_DOMAINS]
    replies = supa_get(f"replies?received_at=gte.{s30}&select=id,run_id,profile_slug,from_addr,"
                       f"to_addr,subject,class,body_snippet,received_at&order=received_at.desc&limit=2000")
    replies = [r for r in replies if r.get("profile_slug") == "diraya" or _dom(r.get("to_addr")) in DIRAYA_DOMAINS]
    prospects = supa_get("prospects?profile_slug=eq.diraya&select=id,email,first_name,company,"
                         "verified,unsubscribed,unsubscribed_at,niche_slug&limit=10000")
    sid = supa_get("sequences?profile_slug=eq.diraya&select=id")
    sid = sid[0]["id"] if sid else None
    runs = supa_get(f"runs?sequence_id=eq.{sid}&select=id,prospect_id,status,current_step&limit=10000") if sid else []
    return {"sends": sends, "replies": replies, "prospects": prospects, "runs": runs}


def aggregate(data: dict) -> dict:
    sends, replies, prospects, runs = data["sends"], data["replies"], data["prospects"], data["runs"]

    def kpis(hours):
        s = sends if hours is None else [x for x in sends if dr.in_window(x.get("sent_at"), hours)]
        r = replies if hours is None else [x for x in replies if dr.in_window(x.get("received_at"), hours)]
        return {"sent": len(s),
                "delivered": sum(1 for x in s if x.get("delivered") and not x.get("bounced")),
                "bounced": sum(1 for x in s if x.get("bounced")),
                "complained": sum(1 for x in s if x.get("complained")),
                "opened": sum(1 for x in s if x.get("opened_at")),
                "clicked": sum(1 for x in s if x.get("clicked_at")),
                "real_replies": sum(1 for x in r if x.get("class") == "reply"),
                "unique_to": len({x["to_addr"].lower() for x in s})}
    today, w7, w30 = kpis(24), kpis(7 * 24), kpis(None)

    intents = Counter()
    for r in replies:
        if r.get("class") == "reply":
            intents[dr.classify_intent(r.get("subject"), r.get("body_snippet"))] += 1
    pos_to = {r["from_addr"].lower() for r in replies if r.get("class") == "reply"
              and dr.classify_intent(r.get("subject"), r.get("body_snippet")) == "positive"}

    funnel = {}
    for s in sends:
        row = funnel.setdefault(s.get("step_n") or 0, {"sent": 0, "delivered": 0, "opened": 0, "replied": 0, "positive": 0})
        row["sent"] += 1
        if s.get("delivered") and not s.get("bounced"): row["delivered"] += 1
        if s.get("opened_at"): row["opened"] += 1
        if s.get("replied"): row["replied"] += 1
        if s["to_addr"].lower() in pos_to: row["positive"] += 1

    sub = {}
    for d in DIRAYA.get("relay", {}).get("from_domains", []):
        sub[d["domain"]] = {"current_day": d.get("warmup", {}).get("current_day", 0),
                            "sent": 0, "delivered": 0, "bounced": 0, "complained": 0, "opened": 0}
    for s in sends:
        if not dr.in_window(s.get("sent_at"), 7 * 24): continue
        row = sub.get(_dom(s.get("from_addr")))
        if not row: continue
        row["sent"] += 1
        if s.get("delivered") and not s.get("bounced"): row["delivered"] += 1
        if s.get("bounced"): row["bounced"] += 1
        if s.get("complained"): row["complained"] += 1
        if s.get("opened_at"): row["opened"] += 1

    persona = {}
    for s in sends:
        k = s.get("persona_slug") or "(none)"
        pmeta = DIRAYA_PERSONAS.get(k, {})
        row = persona.setdefault(k, {"name": pmeta.get("full_name", k), "title": pmeta.get("title", ""),
                                     "sent": 0, "delivered": 0, "opened": 0, "bounced": 0, "replied": 0, "positive": 0})
        row["sent"] += 1
        if s.get("delivered") and not s.get("bounced"): row["delivered"] += 1
        if s.get("opened_at"): row["opened"] += 1
        if s.get("bounced"): row["bounced"] += 1
        if s.get("replied"): row["replied"] += 1
        if s["to_addr"].lower() in pos_to: row["positive"] += 1

    enrolled_ids = {r["prospect_id"] for r in runs}
    verified = [p for p in prospects if p.get("verified") and not p.get("unsubscribed")]
    eligible = [p for p in verified if p["id"] not in enrolled_ids and p.get("first_name") and p.get("company")]
    pipeline = {"total": len(prospects), "verified_active": len(verified),
                "enrolled": sum(1 for p in prospects if p["id"] in enrolled_ids), "eligible": len(eligible)}

    recent = sorted([r for r in replies if dr.in_window(r.get("received_at"), 24)],
                    key=lambda r: r.get("received_at", ""), reverse=True)
    bounces = [s for s in sends if s.get("bounced") and dr.in_window(s.get("sent_at"), 24)]
    suppr = [p for p in prospects if p.get("unsubscribed") and dr.in_window(p.get("unsubscribed_at"), 24)]
    return {"today": today, "w7": w7, "w30": w30, "intents": dict(intents),
            "funnel": dict(sorted(funnel.items())), "sub": sub, "persona": persona,
            "pipeline": pipeline, "recent": recent, "bounces": bounces, "suppr": suppr}


def render(a: dict) -> str:
    P, G, R, A, M, RULE = ORANGE, dr.GREEN, dr.RED, dr.AMBER, dr.MUTED, dr.RULE
    t, w7, w30 = a["today"], a["w7"], a["w30"]
    pct = dr.pct

    head = dr.kpi_row([
        dr.kpi_card("Sent today", f"{t['sent']:,}", f"{t['unique_to']:,} unique"),
        dr.kpi_card("Delivered", pct(t["delivered"], t["sent"]), f"{t['delivered']:,} delivered", G),
        dr.kpi_card("Open rate", pct(t["opened"], t["delivered"]), "of delivered"),
        dr.kpi_card("Replies", f"{t['real_replies']:,}", pct(t["real_replies"], t["sent"]), G),
        dr.kpi_card("Bounce rate", pct(t["bounced"], t["sent"]), "target < 5%",
                    R if t["sent"] and t["bounced"] / t["sent"] > 0.05 else G),
        dr.kpi_card("Complaint", pct(t["complained"], t["sent"], 2), "target < 0.1%"),
        dr.kpi_card("Click rate", pct(t["clicked"], t["delivered"]), "of delivered"),
        dr.kpi_card("Unique recip.", f"{t['unique_to']:,}", "today"),
    ])
    blocks = [dr.section("Today at a glance (last 24h)", "Diraya pilot snapshot since yesterday.", head)]

    win = dr.table(["Window", "Sent", "Delivered", "Open %", "Reply %", "Bounce %"],
                   [[lbl, f"{k['sent']:,}", f"{k['delivered']:,}", pct(k["opened"], k["delivered"]),
                     pct(k["real_replies"], k["sent"]), pct(k["bounced"], k["sent"])]
                    for lbl, k in [("Last 24h", t), ("Last 7d", w7), ("Last 30d", w30)]],
                   ["left", "right", "right", "right", "right", "right"])
    blocks.append(dr.section("Time-window comparison", "Trend as warmup ramps and the lead pool grows.", win))

    intents = a["intents"]; tot = sum(intents.values())
    if tot:
        ii = dr.kpi_row([dr.kpi_card("Positive", f"{intents.get('positive',0):,}", pct(intents.get('positive',0), tot), G),
                         dr.kpi_card("Neutral", f"{intents.get('neutral',0):,}", pct(intents.get('neutral',0), tot)),
                         dr.kpi_card("Negative", f"{intents.get('negative',0):,}", pct(intents.get('negative',0), tot), A),
                         dr.kpi_card("Auto-reply", f"{intents.get('auto_reply',0):,}", pct(intents.get('auto_reply',0), tot)),
                         dr.kpi_card("Unsubscribe", f"{intents.get('unsubscribe',0):,}", pct(intents.get('unsubscribe',0), tot), R)])
    else:
        ii = '<div style="color:#666;padding:8px;">No replies classified in the last 30 days yet.</div>'
    blocks.append(dr.section("Reply quality (last 30d)", "Live-classified intent of every reply.", ii))

    if a["funnel"]:
        fr = [[f"step {s}", f"{r['sent']:,}", f"{r['delivered']:,}", pct(r['opened'], r['delivered']),
               pct(r['replied'], r['delivered']), dr.colored(str(r['positive']), G) if r['positive'] else "—"]
              for s, r in a["funnel"].items()]
        fi = dr.table(["Step", "Sent", "Delivered", "Open %", "Reply %", "Positive"], fr,
                      ["left", "right", "right", "right", "right", "right"])
    else:
        fi = '<div style="color:#666;padding:8px;">No step-tagged sends yet.</div>'
    blocks.append(dr.section("Per-step engagement funnel (last 30d)", "Where the 7-email sequence converts.", fi))

    MIN = 20
    sr = []
    for dom, r in sorted(a["sub"].items(), key=lambda kv: -kv[1]["sent"]):
        if r["sent"] == 0:
            sr.append([f'<code>{dom}</code>', f"day {r['current_day']}", "0", "0", "—", "—", dr.colored("idle", M)]); continue
        br = r["bounced"] / r["sent"]; low = r["sent"] < MIN
        st = dr.colored("low-vol", M) if low else (dr.colored("ALERT", R) if br > 0.05 else dr.colored("OK", G))
        sr.append([f'<code>{dom}</code>', f"day {r['current_day']}", f"{r['sent']:,}", f"{r['delivered']:,}",
                   pct(r["bounced"], r["sent"]), pct(r["opened"], r["delivered"]), st])
    si = dr.table(["Subdomain", "Warmup", "7d Sent", "Delivered", "Bounce %", "Open %", "Status"],
                  sr or [["(no senders)", "", "", "", "", "", ""]],
                  ["left", "left", "right", "right", "right", "right", "center"])
    blocks.append(dr.section("Sender health (rolling 7d)", "Diraya's 10 subdomains on the Pro account, with warmup day.", si))

    pr = []
    for k, r in sorted(a["persona"].items(), key=lambda kv: -kv[1]["sent"]):
        pr.append([f'{dr.escape(r["name"])}<br><span style="color:{M};font-size:11px">{dr.escape(r["title"])}</span>',
                   f"{r['sent']:,}", pct(r["delivered"], r["sent"]), pct(r["opened"], r["delivered"]),
                   pct(r["replied"], r["delivered"]), dr.colored(str(r["positive"]), G) if r["positive"] else "—"])
    pi = dr.table(["Persona", "Sent (30d)", "Delivery %", "Open %", "Reply %", "Positive"],
                  pr or [["(no data)", "", "", "", "", ""]], ["left", "right", "right", "right", "right", "right"])
    blocks.append(dr.section("Persona head-to-head (last 30d)", "Each Diraya identity's engagement. Diverging opens signal copy/signature differences.", pi))

    pl = a["pipeline"]
    pli = dr.kpi_row([dr.kpi_card("Total leads", f"{pl['total']:,}", "in pool"),
                      dr.kpi_card("Verified active", f"{pl['verified_active']:,}", "sendable"),
                      dr.kpi_card("Enrolled", f"{pl['enrolled']:,}", "in sequence"),
                      dr.kpi_card("Eligible (ready)", f"{pl['eligible']:,}", "next enroll", G if pl['eligible'] else None)])
    blocks.append(dr.section("Pipeline snapshot", "YC AI-founder leads ready for tomorrow's 09:30 enrollment.", pli))

    rr = a["recent"]
    if rr:
        rows = [[f'<code>{dr.escape(r.get("received_at","")[:16])}</code>', dr.escape(r.get("from_addr","")),
                 dr.escape((r.get("subject") or "")[:50]),
                 dr.colored(dr.classify_intent(r.get("subject"), r.get("body_snippet")),
                            {"positive": G, "negative": A, "unsubscribe": R}.get(dr.classify_intent(r.get("subject"), r.get("body_snippet")), M)),
                 f'<span style="color:#444;font-size:12px">{dr.escape((r.get("body_snippet") or "")[:200])}</span>'] for r in rr]
        ri = dr.table(["When (UTC)", "From", "Subject", "Intent", "Snippet"], rows, ["left", "left", "left", "center", "left"])
    else:
        ri = '<div style="color:#666;padding:8px;">No replies in the last 24h.</div>'
    blocks.append(dr.section("Recent replies (last 24h)", "Every reply that landed, with snippet — route GHOSTS/REVIEW + positives to Calendly.", ri))

    ai = ""
    if a["bounces"]:
        ai += dr.table(["Bounced address", "Sender", "Step", "Reason"],
                       [[dr.escape(b["to_addr"]), f'<code>{dr.escape((b.get("from_addr") or "").split("@")[0])}</code>',
                         f"step {b.get('step_n','?')}", dr.escape((b.get("error") or "")[:80])] for b in a["bounces"][:25]],
                       ["left", "left", "left", "left"])
    if a["suppr"]:
        ai += dr.table(["New suppressions today"], [[dr.escape(p["email"])] for p in a["suppr"][:25]], ["left"])
    blocks.append(dr.section("Alerts (last 24h)", "Bounces + new suppressions since yesterday.",
                             ai or '<div style="color:#666;padding:8px;">No bounces or suppressions in the last 24h.</div>'))

    return f"""<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0;background:#f5f5f5;font-family:'Inter',-apple-system,'Segoe UI',sans-serif;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f5f5f5;padding:24px 12px;"><tr><td align="center">
<table role="presentation" width="800" cellpadding="0" cellspacing="0" style="max-width:800px;width:100%;">
<tr><td style="background:#0a0a0a;padding:24px 28px;border-radius:6px 6px 0 0;border-top:3px solid {P};">
<div style="font-size:18px;font-weight:700;color:{P};letter-spacing:.4px;">Diraya — Daily Pilot Report</div>
<div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1.4px;margin-top:6px;">{dt.datetime.now().strftime("%A, %B %d %Y")} &middot; AI engineering outreach</div>
</td></tr><tr><td style="padding:24px 0;">{''.join(blocks)}</td></tr>
<tr><td style="background:#0a0a0a;padding:18px 28px;border-radius:0 0 6px 6px;text-align:center;">
<div style="font-size:11px;color:#888;">Generated by Aureon Global for Diraya Inc &middot; {dt.datetime.now().strftime("%H:%M")}</div>
</td></tr></table></td></tr></table></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--to", default=None, help="override recipients (comma-separated)")
    args = ap.parse_args()
    recipients = [x.strip() for x in args.to.split(",")] if args.to else RECIPIENTS
    print("fetching Diraya data..."); data = fetch()
    print(f"  sends={len(data['sends'])} replies={len(data['replies'])} prospects={len(data['prospects'])} runs={len(data['runs'])}")
    agg = aggregate(data); html = render(agg)
    t = agg["today"]
    subject = (f"Diraya daily: {t['sent']} sent, {dr.pct(t['opened'], t['delivered'])} open, "
               f"{dr.pct(t['real_replies'], t['sent'])} reply, {agg['pipeline']['total']} leads")
    if args.dry:
        print(subject); print("-> would send to", recipients, f"(html {len(html)} bytes)"); return 0
    payload = {"from": FROM, "to": recipients, "subject": subject, "html": html,
               "tags": [{"name": "kind", "value": "diraya_daily_report"}]}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(),
                                 method="POST", headers={"Authorization": "Bearer " + RK,
                                 "Content-Type": "application/json", "User-Agent": UA})
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=30).read()); print("sent:", r.get("id"), "to", recipients)
    except urllib.error.HTTPError as e:
        print("! send failed", e.code, e.read().decode()[:200]); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
