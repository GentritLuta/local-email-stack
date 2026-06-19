"""One-off diagnostic: are sends actually happening, tracked, ICP-fitting?

Prints, per profile:
  - last 14 days of sends with delivered/bounce/open counts
  - last 5 sends (date, from, to, subject, status)
  - 5 sample prospects (name, title, company, ICP signals)
"""
from __future__ import annotations
import datetime as dt
import json
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV = REPO / "sequences" / "supabase.env"
env = {}
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]
KEY = env["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def fetch(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def section(title: str) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")


# ── 1. Last 14 days of sends, per profile, with status ────────────────────
section("SEND HISTORY -- last 14 days, all profiles")
since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=14)).strftime("%Y-%m-%dT00:00:00Z")
sends = fetch(
    f"send_log?sent_at=gte.{urllib.parse.quote(since)}"
    f"&select=sent_at,persona_slug,from_addr,to_addr,subject,delivered,bounced,opened_at,clicked_at,replied,complained,error,resend_id,step_n"
    f"&order=sent_at.desc&limit=500"
)
print(f"total sends in last 14 days: {len(sends)}")

def profile_from_subdomain(addr: str) -> str:
    """Map from_addr -> profile based on subdomain. Aureon owns specific subs."""
    if not addr or "@" not in addr: return "?"
    sub = addr.split("@")[-1]
    aureon = {"mail.aureonglobal.de","outreach.aureonglobal.de","hi.aureonglobal.de","connect.aureonglobal.de","partners.aureonglobal.de"}
    algoalpha = {"team.aureonglobal.de","desk.aureonglobal.de","hub.aureonglobal.de"}
    if sub in aureon:    return "aureon"
    if sub in algoalpha: return "algoalpha"
    return f"unknown ({sub})"

by_day = defaultdict(lambda: Counter())
by_profile = defaultdict(lambda: Counter())
for s in sends:
    day = (s.get("sent_at") or "")[:10]
    by_day[day]["sent"] += 1
    if s.get("delivered"):  by_day[day]["delivered"] += 1
    if s.get("bounced"):    by_day[day]["bounced"]   += 1
    if s.get("opened_at"):  by_day[day]["opened"]    += 1
    if s.get("clicked_at"): by_day[day]["clicked"]   += 1
    if s.get("replied"):    by_day[day]["replied"]   += 1
    if s.get("error"):      by_day[day]["error"]     += 1
    p = profile_from_subdomain(s.get("from_addr",""))
    by_profile[p]["sent"] += 1
    if s.get("delivered"):  by_profile[p]["delivered"] += 1
    if s.get("bounced"):    by_profile[p]["bounced"]   += 1
    if s.get("opened_at"):  by_profile[p]["opened"]    += 1
    if s.get("replied"):    by_profile[p]["replied"]   += 1
    if s.get("error"):      by_profile[p]["error"]     += 1

print(f"\nDaily breakdown:")
print(f"  {'day':12} {'sent':>5} {'deliv':>6} {'bounce':>7} {'open':>5} {'click':>5} {'reply':>5} {'error':>6}")
for day in sorted(by_day.keys(), reverse=True):
    c = by_day[day]
    print(f"  {day:12} {c['sent']:>5} {c['delivered']:>6} {c['bounced']:>7} {c['opened']:>5} {c['clicked']:>5} {c['replied']:>5} {c['error']:>6}")

print(f"\nProfile breakdown (14d):")
print(f"  {'profile':24} {'sent':>5} {'deliv':>6} {'bounce':>7} {'open':>5} {'reply':>5} {'error':>6}")
for p in sorted(by_profile.keys()):
    c = by_profile[p]
    print(f"  {p:24} {c['sent']:>5} {c['delivered']:>6} {c['bounced']:>7} {c['opened']:>5} {c['replied']:>5} {c['error']:>6}")

# ── 2. Last 5 sends (date, from, to, subject, status) ─────────────────────
section("LAST 5 SENDS  -- recent activity check")
recent = fetch("send_log?select=sent_at,persona_slug,from_addr,to_addr,subject,delivered,bounced,opened_at,replied,error,resend_id&order=sent_at.desc&limit=5")
for s in recent:
    status = []
    if s.get("delivered"):  status.append("delivered")
    if s.get("bounced"):    status.append("BOUNCED")
    if s.get("opened_at"):  status.append("opened")
    if s.get("replied"):    status.append("REPLIED")
    if s.get("error"):      status.append(f"ERROR={(s['error'] or '')[:40]}")
    if not status:          status.append("(no tracking event yet)")
    p = profile_from_subdomain(s.get("from_addr",""))
    print(f"  {s.get('sent_at','')[:19]}  {p:14}  {s.get('from_addr',''):42} -> {s.get('to_addr',''):40}")
    print(f"    subj: {(s.get('subject') or '')[:70]}")
    print(f"    status: {' | '.join(status)}   resend_id={s.get('resend_id') or 'none'}")
    print()

# ── 3. ICP sample: 5 prospects per profile ────────────────────────────────
section("PROSPECT ICP SAMPLES -- are leads actually fitting?")
for slug in ("aureon", "algoalpha"):
    print(f"\n--- {slug} (sample of 5) ---")
    rows = fetch(f"prospects?profile_slug=eq.{slug}&select=first_name,last_name,title,company,website,city,state,geo,verified,quality_score,niche_slug,industry_tags&order=created_at.desc&limit=5")
    for p in rows:
        loc = " / ".join(x for x in [p.get("city"), p.get("state"), p.get("geo")] if x) or "?"
        tags = ",".join((p.get("industry_tags") or [])[:3]) if isinstance(p.get("industry_tags"), list) else ""
        print(f"  {p.get('first_name','')} {p.get('last_name','') or ''} | {p.get('title','') or 'no-title'} | {p.get('company','') or 'no-co'} | {p.get('website','') or 'no-site'} | {loc}  [v={p.get('verified')} q={p.get('quality_score')} niche={p.get('niche_slug')} tags={tags}]")


print("\n" + "=" * 72)
print("DONE")
print("=" * 72)
