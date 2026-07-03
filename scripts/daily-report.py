"""daily-report.py - send a daily ops summary to info@aureonglobal.de.

Mirrors the in-app Analytics dashboard:
  - Headline KPIs (Sent, Delivered, Replied, Unsubscribed) per window
  - Quality KPIs (Bounce / Complaint / Open / Click rate)
  - Reply intent breakdown (positive / negative / auto / unsubscribe / neutral)
  - Per-step engagement funnel
  - Subdomain health (rolling 7d) with status pills
  - Persona head-to-head
  - Per-client and per-niche breakdowns
  - Pipeline snapshot (eligible-but-not-yet-enrolled per client)
  - Today's bounces (with reason) + suppressed contacts

Sent FROM reports@hi.aureonglobal.de (verified subdomain) TO
info@aureonglobal.de via Resend HTTP API. One email per day.

Schedule: LES-daily-report runs daily 08:00 local, after the
LES-daily-fill-and-enroll pass at 09:30 means the morning report
covers yesterday + last-7d view. Honest, no spin, no markdown.

Run manually:
    py scripts/daily-report.py                # send live
    py scripts/daily-report.py --dry          # print HTML + skip send
    py scripts/daily-report.py --to OTHER@x   # override recipient
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.parse
import urllib.request
import urllib.error
from collections import Counter, defaultdict
from html import escape
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# area-code -> state/metro helpers (degrade gracefully so a geo glitch never
# breaks the daily send)
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from area_codes import metro_for, state_for
except Exception:
    def metro_for(_a): return ""
    def state_for(_a): return ""
ENV  = REPO / "sequences" / "supabase.env"
HOST_ENV = REPO / "sequences" / "hostinger.env"

env = {}
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
host = {}
for line in HOST_ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        host[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
RESEND_FULL = host["RESEND_FULL_ACCESS_API_KEY"]

# Use the production Aureon Resend key for the actual send (any verified
# subdomain works). Reports go FROM a clearly non-outreach address so they
# don't get confused with prospect mail in the user's own inbox.
PROFILE_KEY_PATH = REPO / "profiles" / "aureon.private.json"
RESEND_SEND_KEY = json.loads(PROFILE_KEY_PATH.read_text(encoding="utf-8"))["relay"]["resend_api_key"]

H_R = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123.0.0.0 Safari/537.36"

# ─── Reply-intent classifier (mirrors Analytics.tsx) ──────────────────────

AUTO_RX  = re.compile(r"\b(out of office|out-of-office|vacation|abwesenheits?notiz|automatic(?:ally)?\s+reply|auto[-\s]?reply|abwesend|ferien|on (?:vacation|holiday|leave)|away from|automatische antwort|paternity|maternity)\b", re.I)
UNSUB_RX = re.compile(r"\b(unsubscribe|abmelden|austragen|remove me from|please remove|stop sending|stop emailing|do not (?:contact|email)|gdpr (?:request|removal)|cease and desist|nicht mehr (?:kontakt|email|mail))\b", re.I)
NEG_RX   = re.compile(r"\b(not interested|nicht interess(?:iert|ant)|kein interesse|no thanks|nein danke|not relevant|wrong person|wrong contact|wrong number|please stop|stop contact|not for us|not a fit|won'?t be|nicht passend|no thank you)\b", re.I)
POS_RX   = re.compile(r"\b(interested|interess(?:iert|ant)|let'?s (?:chat|talk|schedule|hop on|jump on)|gerne|sounds good|happy to (?:chat|talk|jump)|please send|share more|tell me more|book a call|book a time|schedule a (?:call|time|meeting)|when (?:are you|works for you)|sure|absolutely|yes,? (?:please|happy|absolutely)|let me know more|melde mich|melden sie sich|machen wir|passt mir|gerne ein gespr|gerne mehr)\b", re.I)


def classify_intent(subject: str | None, body: str | None) -> str:
    hay = f"{subject or ''}\n{body or ''}"
    if AUTO_RX.search(hay):  return "auto_reply"
    if UNSUB_RX.search(hay): return "unsubscribe"
    if NEG_RX.search(hay):   return "negative"
    if POS_RX.search(hay):   return "positive"
    return "neutral"


# ─── Data fetch ───────────────────────────────────────────────────────────

def supa_get(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H_R)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def supa_get_all(path: str, page: int = 1000, max_pages: int = 60) -> list:
    """Fetch ALL rows for a query, paging past PostgREST's 1000-row default cap.
    The 7d/30d windows undercounted because a single request maxes at 1000 rows;
    this walks offsets until a short page (or the safety cap) is hit."""
    out: list = []
    for i in range(max_pages):
        sep = "&" if "?" in path else "?"
        rows = supa_get(f"{path}{sep}limit={page}&offset={i * page}")
        out.extend(rows)
        if len(rows) < page:
            break
    return out


# Production-only filter. Anything outside these sets is pre-system test
# data left in Supabase (legacy personas, business-correspondence replies
# to info@aureonglobal.de, etc.) and gets excluded from the report.
# ACTIVE_PROFILES is now derived from the DB `active` flag at fetch time (see
# fetch_all_data), NOT hardcoded — a hardcoded list went stale and silently
# zeroed every newer client's report (energ/diraya/dorian/lk/mark-eting were
# missing). The persona allowlist is also gone: a send is attributed purely by
# its SENDING SUBDOMAIN, which is collision-free and authoritative (every active
# subdomain belongs to exactly one profile). 2026-06-15.


def _is_production_send(row: dict, active_subdomains: set[str]) -> bool:
    """A send_log row counts as production iff its persona AND its from-
    subdomain both belong to the live campaigns. Filters out legacy daniel/
    marco/olivia/rachel test sends and pre-system mail.aureonglobal.de
    traffic from setup-period scripts."""
    from_addr = (row.get("from_addr") or "").lower()
    domain = from_addr.split("@", 1)[1] if "@" in from_addr else ""
    return domain in active_subdomains


def _is_production_reply(row: dict, active_subdomains: set[str]) -> bool:
    """A reply counts as a real cold-outreach reply iff EITHER (a) it was
    matched to one of our sends via run_id during IMAP polling, OR (b) its
    To: address is one of our outreach SENDER subdomains (which is where
    real prospect replies land — never info@aureonglobal.de which is the
    user's business inbox). Everything else (invoices, calendar invites,
    Wolt welcome emails, etc) gets filtered."""
    if row.get("class") != "reply": return False
    if row.get("run_id"): return True
    to_addr = (row.get("to_addr") or "").lower()
    domain = to_addr.split("@", 1)[1] if "@" in to_addr else ""
    return domain in active_subdomains


def fetch_all_data() -> dict:
    """Pull the data shapes the dashboard reads. Filtered to the last 30d
    server-side to bound query size, then production-filtered client-side."""
    since30 = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)).isoformat()
    s30 = urllib.parse.quote(since30)
    profiles = supa_get("profiles?select=slug,name,active,config&limit=20")

    # Build the set of active SENDER subdomains from active-profile relay pools.
    # "Active" = the profile's DB `active` flag is true AND it has sending
    # subdomains. Derived live so a new client is never silently excluded.
    active_subdomains: set[str] = set()
    for p in profiles:
        cfg = p.get("config") or {}
        if not p.get("active"): continue
        for fd in (cfg.get("relay", {}).get("from_domains") or []):
            if fd.get("domain"): active_subdomains.add(fd["domain"])

    sends_raw = supa_get_all(
        f"send_log?sent_at=gte.{s30}&select=resend_id,run_id,step_n,persona_slug,from_addr,"
        f"to_addr,subject,delivered,bounced,replied,complained,opened_at,clicked_at,"
        f"sent_at,error&order=sent_at.desc")
    replies_raw = supa_get_all(
        f"replies?received_at=gte.{s30}&select=id,run_id,profile_slug,from_addr,to_addr,"
        f"subject,class,body_snippet,received_at,raw_headers&order=received_at.desc")
    prospects = supa_get_all(
        "prospects?select=id,profile_slug,email,first_name,company,city,state,phone,verified,"
        "unsubscribed,unsubscribed_at,verification_method,niche_slug")
    prospect_emails = {(p.get("email") or "").lower() for p in prospects if p.get("email")}

    sends_prod   = [r for r in sends_raw   if _is_production_send(r, active_subdomains)]
    # A reply counts as production if it matched a send/subdomain OR is simply
    # from a known prospect address. The second clause guarantees EVERY genuine
    # prospect reply lands in the report, even ones that hit info@ unmatched.
    replies_prod = [r for r in replies_raw
                    if _is_production_reply(r, active_subdomains)
                    or (r.get("class") == "reply"
                        and (r.get("from_addr") or "").lower() in prospect_emails)]

    print(f"  filter: send_log {len(sends_raw)} -> {len(sends_prod)} production rows")
    print(f"  filter: replies  {len(replies_raw)} -> {len(replies_prod)} production rows")

    return {
        "profiles":  profiles,
        "sequences": supa_get("sequences?select=id,slug,profile_slug&limit=50"),
        "sends":     sends_prod,
        "replies":   replies_prod,
        "replies_all": replies_raw,
        "prospects": prospects,
        "runs":      supa_get_all(
            "runs?select=id,sequence_id,prospect_id,status,current_step,next_send_at"),
    }


# ─── Aggregations ─────────────────────────────────────────────────────────

def in_window(iso: str | None, hours: int) -> bool:
    if not iso: return False
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    try:
        return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")) >= cutoff
    except Exception:
        return False


def aggregate(data: dict) -> dict:
    profiles = data["profiles"]; sends = data["sends"]; replies = data["replies"]
    prospects = data["prospects"]; runs = data["runs"]; sequences = data["sequences"]

    # persona -> profile_slug lookup. WARNING: persona names collide across
    # profiles (atalsolidrocks has anna/lukas/tobias/... which also exist in
    # aureon/algo/f2), so last-writer-wins here mis-maps a name to whichever
    # profile is iterated last. Do NOT use this to attribute sends to profiles.
    persona_to_profile: dict[str, str] = {}
    for p in profiles:
        for persona in (p.get("config", {}).get("personas") or []):
            persona_to_profile[persona["slug"]] = p["slug"]

    # subdomain -> profile_slug. AUTHORITATIVE + collision-free: each sending
    # subdomain belongs to exactly one profile. Attribute sends by the sending
    # domain, never by persona_slug (which collides and silently dumped all of
    # aureon's "anna" volume onto atalsolidrocks in the report).
    domain_to_profile: dict[str, str] = {}
    for p in profiles:
        for fd in (p.get("config", {}).get("relay", {}).get("from_domains") or []):
            if fd.get("domain"):
                domain_to_profile[fd["domain"].lower()] = p["slug"]

    def _send_profile(s: dict) -> str:
        """Profile a send_log row belongs to, by SENDING DOMAIN (collision-free).
        Falls back to persona only when the domain is unknown."""
        fa = (s.get("from_addr") or "").lower()
        dom = fa.split("@", 1)[1] if "@" in fa else ""
        return (domain_to_profile.get(dom)
                or persona_to_profile.get(s.get("persona_slug") or "")
                or "(unknown)")

    # email+profile -> niche_slug
    niche_lookup: dict[str, str] = {}
    for p in prospects:
        niche_lookup[f"{p['profile_slug']}|{p['email'].lower()}"] = p.get("niche_slug") or "(none)"

    # ── Headline (per window) ──
    def kpis_for(window_hours: int | None) -> dict:
        s = sends if window_hours is None else [x for x in sends if in_window(x.get("sent_at"), window_hours)]
        r = replies if window_hours is None else [x for x in replies if in_window(x.get("received_at"), window_hours)]
        total = len(s)
        delivered = sum(1 for x in s if x.get("delivered") and not x.get("bounced"))
        bounced   = sum(1 for x in s if x.get("bounced"))
        complained = sum(1 for x in s if x.get("complained"))
        opened    = sum(1 for x in s if x.get("opened_at"))
        clicked   = sum(1 for x in s if x.get("clicked_at"))
        replied_sends = sum(1 for x in s if x.get("replied"))
        real_replies = [x for x in r if x.get("class") == "reply"]
        unique_to = len({x["to_addr"].lower() for x in s})
        return {
            "sent":       total,
            "delivered":  delivered,
            "bounced":    bounced,
            "complained": complained,
            "opened":     opened,
            "clicked":    clicked,
            "replied_sends": replied_sends,
            "real_replies":  len(real_replies),
            "unique_to":  unique_to,
        }

    today  = kpis_for(24)
    last_7 = kpis_for(7 * 24)
    last30 = kpis_for(None)

    # ── Reply intents (last 30d) ──
    intents = Counter()
    for r in replies:
        if r.get("class") != "reply": continue
        intents[classify_intent(r.get("subject"), r.get("body_snippet"))] += 1

    # ── Per-step funnel (last 30d) ──
    pos_emails = {r["from_addr"].lower() for r in replies
                  if r.get("class") == "reply"
                  and classify_intent(r.get("subject"), r.get("body_snippet")) == "positive"}
    step_funnel: dict[int, dict] = {}
    for s in sends:
        step = s.get("step_n") or 0
        row = step_funnel.setdefault(step, {"sent": 0, "delivered": 0, "opened": 0,
                                             "replied": 0, "positive": 0})
        row["sent"] += 1
        if s.get("delivered") and not s.get("bounced"): row["delivered"] += 1
        if s.get("opened_at"):  row["opened"] += 1
        if s.get("replied"):    row["replied"] += 1
        if s["to_addr"].lower() in pos_emails: row["positive"] += 1

    # ── Subdomain health (rolling 7d) ──
    sub_health: dict[str, dict] = {}
    for p in profiles:
        for d in (p.get("config", {}).get("relay", {}).get("from_domains") or []):
            if not d.get("domain"): continue
            sub_health[d["domain"]] = {
                "profile":     p["name"],
                "current_day": d.get("warmup", {}).get("current_day", 0),
                "sent": 0, "delivered": 0, "bounced": 0, "complained": 0, "opened": 0,
            }
    for s in sends:
        if not in_window(s.get("sent_at"), 7 * 24): continue
        dom = (s["from_addr"].split("@") + [""])[1].lower()
        row = sub_health.get(dom)
        if not row: continue
        row["sent"] += 1
        if s.get("delivered") and not s.get("bounced"): row["delivered"] += 1
        if s.get("bounced"):    row["bounced"] += 1
        if s.get("complained"): row["complained"] += 1
        if s.get("opened_at"):  row["opened"] += 1

    # ── Persona head-to-head ──
    persona_perf: dict[str, dict] = {}
    for s in sends:
        k = s.get("persona_slug") or "(none)"
        prof_slug = _send_profile(s)
        prof = next((p["name"] for p in profiles if p["slug"] == prof_slug), prof_slug)
        row = persona_perf.setdefault(k, {"profile": prof, "sent": 0, "delivered": 0,
                                          "opened": 0, "bounced": 0, "replied": 0, "positive": 0})
        row["sent"] += 1
        if s.get("delivered") and not s.get("bounced"): row["delivered"] += 1
        if s.get("opened_at"): row["opened"] += 1
        if s.get("bounced"):   row["bounced"] += 1
        if s.get("replied"):   row["replied"] += 1
        if s["to_addr"].lower() in pos_emails: row["positive"] += 1

    # ── Per client + per niche (last 30d) ──
    per_client: dict[str, dict] = {}
    for p in profiles:
        per_client[p["slug"]] = {"name": p["name"], "sent": 0, "delivered": 0,
                                  "bounced": 0, "replied": 0, "opened": 0, "unsubs": 0}
    for s in sends:
        slug = _send_profile(s)
        row = per_client.setdefault(slug, {"name": slug, "sent": 0, "delivered": 0,
                                            "bounced": 0, "replied": 0, "opened": 0, "unsubs": 0})
        row["sent"] += 1
        if s.get("delivered") and not s.get("bounced"): row["delivered"] += 1
        if s.get("bounced"):    row["bounced"] += 1
        if s.get("replied"):    row["replied"] += 1
        if s.get("opened_at"):  row["opened"] += 1
    for p in prospects:
        if p.get("unsubscribed") and in_window(p.get("unsubscribed_at"), 30 * 24):
            row = per_client.get(p["profile_slug"])
            if row: row["unsubs"] += 1
    # Per-client REAL replies come from the replies table (class='reply'), NOT the
    # laggy/partial send_log.replied flag. send_log.replied only fills when a reply is
    # header/subject-matched to its sent row (Resend rewrites Message-IDs, so most never
    # match), which made working clients (e.g. algoalpha's 25 real replies) look dead.
    _email2slug = {(p.get("email") or "").lower(): p.get("profile_slug")
                   for p in prospects if p.get("email")}
    for row in per_client.values():
        row["real_replies"] = 0
    for r in replies:
        if r.get("class") != "reply":
            continue
        pslug = r.get("profile_slug") or _email2slug.get((r.get("from_addr") or "").lower())
        row = per_client.get(pslug)
        if row:
            row["real_replies"] = row.get("real_replies", 0) + 1

    per_niche: dict[str, dict] = {}
    for p in prospects:
        k = p.get("niche_slug") or "(none)"
        row = per_niche.setdefault(k, {"prospects": 0, "sent": 0, "delivered": 0,
                                        "bounced": 0, "replied": 0})
        row["prospects"] += 1
    for s in sends:
        prof_slug = _send_profile(s)
        if prof_slug == "(unknown)": continue
        niche = niche_lookup.get(f"{prof_slug}|{s['to_addr'].lower()}", "(none)")
        row = per_niche.setdefault(niche, {"prospects": 0, "sent": 0, "delivered": 0,
                                            "bounced": 0, "replied": 0})
        row["sent"] += 1
        if s.get("delivered") and not s.get("bounced"): row["delivered"] += 1
        if s.get("bounced"): row["bounced"] += 1
        if s.get("replied"): row["replied"] += 1

    # ── Pipeline snapshot per profile ──
    pipeline: list[dict] = []
    for p in profiles:
        prof_prospects = [x for x in prospects if x["profile_slug"] == p["slug"]]
        seq = next((s for s in sequences if s["profile_slug"] == p["slug"]), None)
        enrolled_ids = set()
        if seq:
            enrolled_ids = {r["prospect_id"] for r in runs if r["sequence_id"] == seq["id"]}
        verified = [x for x in prof_prospects if x.get("verified") and not x.get("unsubscribed")]
        # Determine required merges from variants file (cheap heuristic)
        requires_city = False
        eligible = [x for x in verified
                    if x["id"] not in enrolled_ids
                    and x.get("first_name") and x.get("company")
                    and (not requires_city or x.get("city"))]
        pipeline.append({
            "slug":              p["slug"],
            "name":              p["name"],
            "total_prospects":   len(prof_prospects),
            "verified_active":   len(verified),
            "enrolled":          sum(1 for x in prof_prospects if x["id"] in enrolled_ids),
            "eligible_unenrolled": len(eligible),
        })

    # ── Today's bounces + new suppressions ──
    todays_bounces = [s for s in sends
                      if s.get("bounced") and in_window(s.get("sent_at"), 24)]
    new_suppressions = [p for p in prospects
                        if p.get("unsubscribed")
                        and in_window(p.get("unsubscribed_at"), 24)]

    # ── Recent replies (last 7d) - actual content + how each was handled.
    # Widened from 24h: reply volume is low during warmup, so a 24h window often
    # read empty and looked like the report had "stopped". 7d keeps every recent
    # reply in view, each tagged with its handling status, so nothing slips.
    recent_replies = sorted(
        [r for r in replies if in_window(r.get("received_at"), 7 * 24)],
        key=lambda r: r.get("received_at", ""), reverse=True,
    )

    # All inbound mail to info@ in the last 24h (every class, minus our own
    # outbound system rows). imap-poll auto-marks these read, so this is the
    # operator's safety net to not miss anything that hit the inbox.
    inbox_24h = sorted(
        [r for r in data["replies_all"]
         if in_window(r.get("received_at"), 24)
         and not (r.get("from_addr") or "").lower().startswith(("alerts@", "drafts@", "reports@"))],
        key=lambda r: r.get("received_at", ""), reverse=True,
    )

    # ── Lead geography (Aureon) — ties to the referral-list give-first engine.
    # "covered" = a curated attorney list exists for that metro, so a LIST/
    # PROBATE reply from there auto-fulfils. Uncovered metros are the build queue.
    def _ac(phone: str | None) -> str:
        d = re.sub(r"\D", "", phone or "")
        if len(d) == 11 and d.startswith("1"): d = d[1:]
        return d[:3] if len(d) >= 10 else ""
    covered_acs: set[str] = set(); covered_states: set[str] = set(); covered_cities: set[str] = set()
    try:
        cur = json.loads((REPO / "referral-lists" / "curated.json").read_text(encoding="utf-8"))
        for e in cur.get("lists", []):
            covered_acs |= set(e["match"].get("area_codes", []))
            covered_states |= {s.upper() for s in e["match"].get("states", [])}
            covered_cities |= {c.lower() for c in e["match"].get("cities", [])}
    except Exception:
        pass
    geo_metro: dict[str, dict] = {}; geo_total = 0; geo_covered = 0
    for p in prospects:
        if p.get("profile_slug") != "aureon": continue
        geo_total += 1
        ac = _ac(p.get("phone"))
        st = (p.get("state") or state_for(ac) or "").upper()
        city_l = (p.get("city") or "").strip().lower()
        metro = metro_for(ac) or (f"{st} (other)" if st else "(unknown)")
        covered = (ac in covered_acs) or (city_l in covered_cities) or (st in covered_states)
        if covered: geo_covered += 1
        row = geo_metro.setdefault(metro, {"state": st, "leads": 0, "covered": covered})
        row["leads"] += 1
        if covered: row["covered"] = True
        if st and not row["state"]: row["state"] = st
    geography = {
        "total": geo_total, "covered": geo_covered,
        "by_metro": dict(sorted(geo_metro.items(), key=lambda kv: -kv[1]["leads"])),
    }

    action_items = build_action_items(recent_replies[:12])

    return {
        "today":      today,
        "last_7":     last_7,
        "last_30":    last30,
        "intents":    dict(intents),
        "step_funnel": dict(sorted(step_funnel.items())),
        "sub_health": sub_health,
        "persona_perf": persona_perf,
        "per_client": per_client,
        "per_niche":  per_niche,
        "pipeline":   pipeline,
        "todays_bounces":   todays_bounces,
        "new_suppressions": new_suppressions,
        "recent_replies":   recent_replies,
        "action_items":     action_items,
        "inbox_24h":        inbox_24h,
        "geography":        geography,
    }


# Concrete next-step to-do list built from the recent replies. One CLI call turns
# every genuine reply into a spelled-out action (e.g. "Message @handle on
# Telegram", "Send the seller list to X", "Book the call with Y"), so the daily
# report tells the operator/client exactly what to do to convert each reply.
_OPERATOR_ADDR = "info@aureonglobal.de"
_REPORT_TO_CACHE: dict[str, str | None] = {}


def _report_to_for(slug: str) -> str | None:
    """Client inbox for this profile (relay.report_to) — the same address the
    forward-replies script hands the lead to. report_to == the operator means we
    own the close; anything else means the CLIENT is the closer."""
    if slug in _REPORT_TO_CACHE:
        return _REPORT_TO_CACHE[slug]
    pf = REPO / "profiles" / f"{slug}.json"
    rt = None
    if pf.exists():
        try:
            p = json.loads(pf.read_text(encoding="utf-8"))
            rt = ((p.get("relay") or {}).get("report_to") or p.get("report_to")
                  or ((p.get("brand") or {}).get("legal") or {}).get("contact_email"))
        except Exception:
            rt = None
    _REPORT_TO_CACHE[slug] = rt
    return rt


def build_action_items(replies: list[dict]) -> list[dict]:
    # Only genuine prospect replies, and NOT autoresponders (out-of-office, ticket
    # bots). The AI has already replied to most of these (reply-autodraft auto-sends
    # and stamps raw_headers.answer_text), so the to-do is the HUMAN HANDOFF to close,
    # not another first reply.
    genuine = [r for r in replies
               if r.get("class") == "reply"
               and not AUTO_RX.search(f"{r.get('subject','')}\n{r.get('body_snippet','')}")]
    # Ask each reply ONCE: drop any that have already been handled (the operator
    # decided it in the reply-review popup -> raw_headers.reviewed, or the pipeline
    # already auto-answered it). Without this, the same reply -- and every past
    # answered one -- is re-listed as a to-do every day for the whole 7d window.
    def _already_handled(r: dict) -> bool:
        rh = r.get("raw_headers") or {}
        return bool(rh.get("reviewed") or rh.get("autosent")
                    or rh.get("autoreply_sent") or rh.get("answer_text"))
    genuine = [r for r in genuine if not _already_handled(r)]
    if not genuine:
        return []
    import os, subprocess, tempfile, shutil
    # Prefer the real claude.exe (the .cmd shim fails to launch via subprocess on
    # Windows); fall back to the configured CLI path.
    _exe = r"D:\npm-global\node_modules\@anthropic-ai\claude-code\bin\claude.exe"
    CLAUDE = _exe if os.path.exists(_exe) else os.environ.get("CLAUDE_CLI", r"D:\npm-global\claude.cmd")
    lines = []
    for i, r in enumerate(genuine):
        body = (r.get("body_snippet") or "").replace("\n", " ")[:300]
        rh = r.get("raw_headers") or {}
        ans = (rh.get("answer_text") or "")
        if rh.get("autosent") or rh.get("autoreply_sent") or ans:
            status = "WE ALREADY REPLIED" + (f' (our reply: "{ans[:150]}")' if ans else "")
        else:
            status = "NOT yet answered by us"
        slug = r.get("profile_slug") or ""
        rt = _report_to_for(slug)
        if rt and rt.lower() != _OPERATOR_ADDR.lower():
            owner = (f"CLIENT LEAD ({slug}) — the closer is the client at {rt}. This reply was "
                     f"forwarded to them; they close it by replying to the forwarded email, which "
                     f"goes straight to the prospect. You only oversee, never reply yourself.")
        else:
            owner = "OUR LEAD (aureon) — you are the closer."
        lines.append(f'{i+1}. From {r.get("from_addr","?")} | Subject: {r.get("subject","")[:70]} | '
                     f'They wrote: "{body}" | {status} | {owner}')
    block = "\n".join(lines)
    system = (
        "You are a sales assistant producing a HANDOFF to-do list for the human closer. Our AI "
        "has already replied to most prospects and done the upfront work (answered questions, "
        "restated the offer, removed friction). Your job is the SINGLE next step to take TODAY to "
        "move each lead toward CLOSE, never to send another first reply. "
        "OWNERSHIP MATTERS: every lead is tagged OUR LEAD or CLIENT LEAD. "
        "For a CLIENT LEAD: the CLIENT is the closer and the reply is already forwarded to them, so "
        "they close it by replying to the forwarded email (which reaches the prospect directly). Your "
        "action is OVERSIGHT only, addressed to the operator about the client, for example 'Check the "
        "client closed X; nudge them if it stalls'. NEVER tell anyone to reply to the prospect on a "
        "CLIENT LEAD. "
        "For an OUR LEAD marked WE ALREADY REPLIED: the action is to take the warmed lead and close it, "
        "for example 'Jump on the call with X to lock the deal' or 'Confirm the package and terms with "
        "X and get them to sign', referencing what they want. "
        "For an OUR LEAD marked NOT yet answered: the action is the direct follow-up needed (answer "
        "them, send what they asked for, or get the handle/number/time). Be specific to what THEY said. "
        "No em-dashes. Return a JSON array of {\"who\":\"<email>\",\"action\":\"<imperative instruction>\"} "
        "and nothing else."
    )
    prompt = f"Turn these replies into a CLOSER handoff to-do list:\n\n{block}\n\nReturn only the JSON array."
    workdir = tempfile.mkdtemp(prefix="les_todo_")
    try:
        proc = subprocess.run(
            [CLAUDE, "-p", "--system-prompt", system,
             "--disallowedTools", "Bash,Read,Glob,Grep,Edit,Write,WebFetch,WebSearch",
             "--setting-sources", "user"],
            input=prompt, capture_output=True, text=True, timeout=120,
            encoding="utf-8", errors="replace", cwd=workdir,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (proc.stdout or "").strip()
        m = re.search(r"\[.*\]", out, re.S)
        if m:
            items = json.loads(m.group(0))
            return [{"who": it.get("who", ""), "action": it.get("action", "")} for it in items if it.get("action")]
    except Exception as e:
        print(f"  (action items skipped: {str(e)[:80]})")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    return []


# ─── HTML render ──────────────────────────────────────────────────────────

GOLD   = "#d4af37"
DARK   = "#050505"
CARD   = "#ffffff"
TEXT   = "#0a0a0a"
MUTED  = "#9ca3af"
RULE   = "#e5e7eb"
GREEN  = "#16a34a"
RED    = "#dc2626"
AMBER  = "#d97706"
BLUE   = "#2563eb"


def reply_handling(r: dict) -> tuple[str, str]:
    """How the reply pipeline handled this reply, for the report's remark
    column. Reads the raw_headers that reply-autodraft.py stamps."""
    rh = r.get("raw_headers") or {}
    if rh.get("autoreply_sent"):
        return ("auto-replied · Calendly", GREEN)
    skip = rh.get("autodraft_skipped")
    if skip:
        if str(skip).startswith("suppressed"):
            return ("suppressed", RED)
        return {
            "too_terse":                  ("manual review", AMBER),
            "not_active_prospect":        ("not a prospect", MUTED),
            "already_autoreplied":        ("already booked", GREEN),
            "list_request_deliver_first": ("deliver list first", AMBER),
        }.get(skip, (str(skip), MUTED))
    if rh.get("autodraft_sent"):
        return ("drafted for approval", BLUE)
    return ("pending", AMBER)


def pct(n: int, d: int, digits: int = 1) -> str:
    if not d: return "—"
    return f"{(n / d) * 100:.{digits}f}%"


def kpi_card(label: str, value: str, sub: str = "", accent: str | None = None) -> str:
    accent_style = f"color:{accent};" if accent else f"color:{TEXT};"
    return (
        f'<td style="padding:14px 16px;border:1px solid {RULE};background:{CARD};'
        f'border-radius:6px;vertical-align:top;">'
        f'<div style="font-size:11px;color:{MUTED};text-transform:uppercase;'
        f'letter-spacing:.6px;">{escape(label)}</div>'
        f'<div style="font-size:24px;font-weight:700;{accent_style}margin-top:4px;">'
        f'{escape(str(value))}</div>'
        f'<div style="font-size:11px;color:{MUTED};margin-top:2px;">{escape(sub)}</div>'
        f'</td>'
    )


def kpi_row(cards: list[str]) -> str:
    # 4-up grid via table cells
    rows = []
    for i in range(0, len(cards), 4):
        cells = cards[i:i+4]
        # pad to 4 with empty cells for alignment
        cells += [f'<td style="border:none;"></td>'] * (4 - len(cells))
        rows.append(f'<tr>{"".join(cells)}</tr>')
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="6" width="100%"'
        f' style="margin-bottom:8px;">'
        f'{"".join(rows)}</table>'
    )


def table(headers: list[str], rows: list[list[str]], col_align: list[str] | None = None) -> str:
    col_align = col_align or ["left"] * len(headers)
    th_html = "".join(
        f'<th style="text-align:{col_align[i]};padding:8px 12px;background:#f5f5f5;'
        f'border-bottom:2px solid {RULE};font-size:11px;text-transform:uppercase;'
        f'letter-spacing:.4px;color:{MUTED};">{escape(h)}</th>'
        for i, h in enumerate(headers)
    )
    body_html = ""
    for r in rows:
        cells = "".join(
            f'<td style="text-align:{col_align[i]};padding:8px 12px;'
            f'border-bottom:1px solid {RULE};font-size:13px;color:{TEXT};">{c}</td>'
            for i, c in enumerate(r)
        )
        body_html += f'<tr>{cells}</tr>'
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" width="100%"'
        f' style="margin-bottom:16px;border-collapse:collapse;">'
        f'<thead><tr>{th_html}</tr></thead><tbody>{body_html}</tbody></table>'
    )


def section(title: str, sub: str, inner_html: str) -> str:
    return (
        f'<div style="margin-bottom:24px;background:{CARD};border:1px solid {RULE};'
        f'border-radius:6px;padding:18px 20px;">'
        f'<div style="font-size:15px;font-weight:700;color:{TEXT};margin-bottom:2px;">{escape(title)}</div>'
        f'<div style="font-size:12px;color:{MUTED};margin-bottom:14px;">{escape(sub)}</div>'
        f'{inner_html}'
        f'</div>'
    )


def colored(text: str, color: str) -> str:
    return f'<span style="color:{color};font-weight:600;">{escape(text)}</span>'


def render_html(a: dict, client_mode: dict | None = None) -> str:
    # client_mode = {"name": "LK Advertising", "accent": "#3d4848", "dark": "#2b2a2b"} when this
    # is a CLIENT-FACING report: it drops every cross-client / internal-ops section so the client
    # sees ONLY their own campaign, and rebrands the header/footer. None = the full internal report.
    today = a["today"]; w7 = a["last_7"]; w30 = a["last_30"]

    # ── Headline KPIs (today) ──
    headline = kpi_row([
        kpi_card("Sent today", f"{today['sent']:,}", f"{today['unique_to']:,} unique"),
        kpi_card("Delivered",  pct(today["delivered"], today["sent"]),
                 f"{today['delivered']:,} delivered", GREEN),
        kpi_card("Open rate",  pct(today["opened"], today["delivered"]),
                 "of delivered (tracker)"),
        kpi_card("Replies",    f"{today['real_replies']:,}",
                 pct(today["real_replies"], today["sent"]), GREEN),
        kpi_card("Bounce rate", pct(today["bounced"], today["sent"]),
                 "target < 5%",
                 RED if today["sent"] and today["bounced"] / today["sent"] > 0.05 else GREEN),
        kpi_card("Complaint",  pct(today["complained"], today["sent"], 2),
                 "target < 0.1%",
                 RED if today["sent"] and today["complained"] / today["sent"] > 0.001 else GREEN),
        kpi_card("Click rate", pct(today["clicked"], today["delivered"]), "of delivered"),
        kpi_card("Unique recip.", f"{today['unique_to']:,}", "today"),
    ])
    headline_block = section(
        "Today at a glance (last 24h)",
        "Snapshot of activity since yesterday, with the same metrics surfaced in the dashboard.",
        headline,
    )

    # ── Window comparison ──
    window_table = table(
        ["Window", "Sent", "Delivered", "Open %", "Reply %", "Bounce %", "Unsub-equivalent"],
        [
            ["Last 24h",
             f"{today['sent']:,}",  f"{today['delivered']:,}",
             pct(today["opened"], today["delivered"]),
             pct(today["real_replies"], today["sent"]),
             pct(today["bounced"], today["sent"]),
             f"{today['complained']:,}"],
            ["Last 7d",
             f"{w7['sent']:,}",  f"{w7['delivered']:,}",
             pct(w7["opened"], w7["delivered"]),
             pct(w7["real_replies"], w7["sent"]),
             pct(w7["bounced"], w7["sent"]),
             f"{w7['complained']:,}"],
            ["Last 30d",
             f"{w30['sent']:,}", f"{w30['delivered']:,}",
             pct(w30["opened"], w30["delivered"]),
             pct(w30["real_replies"], w30["sent"]),
             pct(w30["bounced"], w30["sent"]),
             f"{w30['complained']:,}"],
        ],
        ["left", "right", "right", "right", "right", "right", "right"],
    )
    window_block = section(
        "Time-window comparison",
        "Trend across today / week / month. Watch open + reply rates climb as warmup ramps up.",
        window_table,
    )

    # ── Reply intent ──
    intents = a["intents"]
    total_replies = sum(intents.values())
    if total_replies == 0:
        intent_inner = '<div style="color:#666;padding:8px;">No real replies in the last 30 days yet.</div>'
    else:
        intent_inner = kpi_row([
            kpi_card("Positive",    f"{intents.get('positive', 0):,}",
                     pct(intents.get("positive", 0), total_replies), GREEN),
            kpi_card("Neutral",     f"{intents.get('neutral', 0):,}",
                     pct(intents.get("neutral", 0), total_replies)),
            kpi_card("Negative",    f"{intents.get('negative', 0):,}",
                     pct(intents.get("negative", 0), total_replies), AMBER),
            kpi_card("Auto-reply",  f"{intents.get('auto_reply', 0):,}",
                     pct(intents.get("auto_reply", 0), total_replies)),
            kpi_card("Unsubscribe", f"{intents.get('unsubscribe', 0):,}",
                     pct(intents.get("unsubscribe", 0), total_replies), RED),
        ])
    intent_block = section(
        "Reply quality (last 30d)",
        "Live-classified intent of every reply. Positive + Neutral are conversations worth working.",
        intent_inner,
    )

    # ── Per-step funnel ──
    if a["step_funnel"]:
        rows = []
        for step, r in a["step_funnel"].items():
            rows.append([
                f"step {step}",
                f"{r['sent']:,}",
                f"{r['delivered']:,}",
                pct(r["opened"], r["delivered"]),
                pct(r["replied"], r["delivered"]),
                colored(str(r["positive"]), GREEN) if r["positive"] else "—",
                pct(r["positive"], r["delivered"], 2),
            ])
        step_inner = table(
            ["Step", "Sent", "Delivered", "Open %", "Reply %", "Positive", "Pos %"],
            rows,
            ["left", "right", "right", "right", "right", "right", "right"],
        )
    else:
        step_inner = '<div style="color:#666;padding:8px;">No step-tagged sends in window.</div>'
    step_block = section(
        "Per-step engagement funnel (last 30d)",
        "Where the conversation actually happens. If step 6+ shows healthy sent but tiny Positive, cut the cadence.",
        step_inner,
    )

    # ── Subdomain health ──
    # MIN_SAMPLE: below this, a bounce/complaint % is statistical noise (1 bad
    # address out of 8 sends is 12.5% but means nothing). The 3-day send
    # safeguard uses the same floor; the report must too, or warming subdomains
    # show scary false ALERTs (e.g. "26%" on 19 sends) every morning.
    GREY = "#94a3b8"
    MIN_SAMPLE = 20
    sd_rows = []
    for dom, r in sorted(a["sub_health"].items(),
                         key=lambda kv: (-(kv[1]["bounced"] / max(kv[1]["sent"], 1)),
                                         -kv[1]["sent"])):
        if r["sent"] == 0: continue
        bounce_rate = r["bounced"] / r["sent"] if r["sent"] else 0
        complaint_rate = r["complained"] / r["sent"] if r["sent"] else 0
        low_vol = r["sent"] < MIN_SAMPLE
        is_bad  = (not low_vol) and (bounce_rate > 0.05 or complaint_rate > 0.001)
        is_warn = (not low_vol) and (bounce_rate > 0.025 or complaint_rate > 0.0005)
        if low_vol:   status_html = colored(f"low-vol", GREY)
        elif is_bad:  status_html = colored("ALERT", RED)
        elif is_warn: status_html = colored("warn", AMBER)
        else:         status_html = colored("OK", GREEN)
        # bounce-% cell: only colour red/amber once the sample is meaningful
        bp = pct(r["bounced"], r["sent"])
        if low_vol:                bounce_cell = f'{bp} <span style="color:{GREY}">(n={r["sent"]})</span>'
        elif bounce_rate > 0.05:   bounce_cell = colored(bp, RED)
        elif bounce_rate > 0.025:  bounce_cell = colored(bp, AMBER)
        else:                      bounce_cell = bp
        sd_rows.append([
            f'<code style="font-family:monospace;font-size:12px;">{escape(dom)}</code>',
            escape(r["profile"]),
            f"{r['sent']:,}",
            f"{r['delivered']:,}",
            bounce_cell,
            colored(pct(r["complained"], r["sent"], 2), RED) if (not low_vol and complaint_rate > 0.001)
              else pct(r["complained"], r["sent"], 2),
            pct(r["opened"], r["delivered"]),
            status_html,
        ])
    sd_inner = table(
        ["Subdomain", "Client", "7d Sent", "Delivered", "Bounce %", "Complaint %", "Open %", "Status"],
        sd_rows or [["(no data)", "", "", "", "", "", "", ""]],
        ["left", "left", "right", "right", "right", "right", "right", "center"],
    )
    sd_block = section(
        "Subdomain health (rolling 7d)",
        "Early-warning view: bounce ≥ 5% or complaint ≥ 0.1% will get a subdomain auto-deactivated by Resend.",
        sd_inner,
    )

    # ── Persona head-to-head ──
    pp_rows = []
    for persona, r in sorted(a["persona_perf"].items(), key=lambda kv: -kv[1]["sent"]):
        pp_rows.append([
            f'<span style="background:#f5f5f5;padding:2px 8px;border-radius:3px;'
            f'font-family:monospace;font-size:12px;">{escape(persona)}</span>',
            escape(r["profile"]),
            f"{r['sent']:,}",
            pct(r["delivered"], r["sent"]),
            pct(r["opened"], r["delivered"]),
            pct(r["replied"], r["delivered"]),
            colored(str(r["positive"]), GREEN) if r["positive"] else "—",
            pct(r["positive"], r["delivered"], 2),
        ])
    pp_inner = table(
        ["Persona", "Client", "Sent (30d)", "Delivery %", "Open %", "Reply %", "Positive", "Pos %"],
        pp_rows or [["(no data)", "", "", "", "", "", "", ""]],
        ["left", "left", "right", "right", "right", "right", "right", "right"],
    )
    pp_block = section(
        "Persona head-to-head (last 30d)",
        "Diverging open rates between personas signal copy/signature differences worth copying. Diverging delivery rates signal IP/domain reputation isolated to one persona.",
        pp_inner,
    )

    # ── Per client + per niche ──
    pc_rows = []
    for slug, r in sorted(a["per_client"].items(), key=lambda kv: -kv[1]["sent"]):
        if r["sent"] == 0 and r["unsubs"] == 0: continue
        pc_rows.append([
            escape(r["name"]),
            f"{r['sent']:,}",
            f"{r['delivered']:,}",
            pct(r["opened"], r["delivered"]),
            f"{r.get('real_replies', 0):,} ({pct(r.get('real_replies', 0), r['sent'])})",
            colored(pct(r["bounced"], r["sent"]), RED) if r["sent"] and r["bounced"] / r["sent"] > 0.05
              else pct(r["bounced"], r["sent"]),
            f"{r['unsubs']:,}",
        ])
    pc_inner = table(
        ["Client", "Sent (30d)", "Delivered", "Open %", "Replies (30d)", "Bounce %", "Unsubs"],
        pc_rows or [["(no data)", "", "", "", "", "", ""]],
        ["left", "right", "right", "right", "right", "right", "right"],
    )
    pc_block = section(
        "Per client (last 30d)",
        "Cross-client comparison. Replies (30d) = actual prospect replies received (from the "
        "replies table), so a client getting replies never reads as zero. Watch for any client "
        "trending high on bounce or complaint, or stuck at 0 replies (deliverability or offer).",
        pc_inner,
    )

    pn_rows = []
    for niche, r in sorted(a["per_niche"].items(), key=lambda kv: -kv[1]["sent"]):
        if r["sent"] == 0 and r["prospects"] < 5: continue
        pn_rows.append([
            f'<code style="font-family:monospace;font-size:12px;">{escape(niche)}</code>',
            f"{r['prospects']:,}",
            f"{r['sent']:,}",
            f"{r['delivered']:,}",
            pct(r["replied"], r["sent"]),
            pct(r["bounced"], r["sent"]),
        ])
    pn_inner = table(
        ["Niche", "Prospects", "Sent (30d)", "Delivered", "Reply %", "Bounce %"],
        pn_rows or [["(no data)", "", "", "", "", ""]],
        ["left", "right", "right", "right", "right", "right"],
    )
    pn_block = section(
        "Per niche (last 30d)",
        "Conversion by lead source. Niches with lower reply rates need copy or targeting changes.",
        pn_inner,
    )

    # ── Pipeline ──
    pl_rows = []
    for r in a["pipeline"]:
        pl_rows.append([
            escape(r["name"]),
            f"{r['total_prospects']:,}",
            f"{r['verified_active']:,}",
            f"{r['enrolled']:,}",
            colored(f"{r['eligible_unenrolled']:,}", GREEN) if r["eligible_unenrolled"] > 0
              else "0",
        ])
    pl_inner = table(
        ["Client", "Total prospects", "Verified+active", "Enrolled", "Eligible (ready)"],
        pl_rows or [["(no data)", "", "", "", ""]],
        ["left", "right", "right", "right", "right"],
    )
    pl_block = section(
        "Pipeline snapshot",
        "Prospects sitting in DB ready to be enrolled by tomorrow's 09:30 orchestrator pass.",
        pl_inner,
    )

    # ── Lead geography (ties to the referral give-first engine) ──
    g = a["geography"]
    if g["total"]:
        grows = []
        for metro, r in list(g["by_metro"].items())[:12]:
            cov = colored("ready", GREEN) if r["covered"] else colored("queue", AMBER)
            grows.append([escape(metro), escape(r["state"] or "—"),
                          f'{r["leads"]:,}', pct(r["leads"], g["total"]), cov])
        geo_inner = table(
            ["Metro (phone-derived)", "State", "Leads", "Share", "Curated list"],
            grows, ["left", "left", "right", "right", "center"])
    else:
        geo_inner = '<div style="color:#666;padding:8px;">No Aureon leads with usable geography yet.</div>'
    geo_block = section(
        f"Lead geography — {pct(g['covered'], g['total'])} in a ready metro ({g['covered']:,}/{g['total']:,})",
        "Where Aureon leads sit, by phone area code. 'ready' = a curated attorney list exists "
        "so a LIST/PROBATE reply from that metro auto-fulfils; 'queue' = the next list to build.",
        geo_inner,
    )

    # ── Your action items (to-do list from today's replies) ──
    items = a.get("action_items") or []
    if items:
        li = "".join(
            f'<li style="margin:0 0 10px;padding:0 0 0 4px;line-height:1.5;">'
            f'<span style="font-weight:600;">{escape(it.get("action",""))}</span>'
            + (f'<br><span style="color:#777;font-size:12px;">Reply from {escape(it.get("who",""))}</span>' if it.get("who") else "")
            + '</li>'
            for it in items)
        todo_inner = f'<ol style="margin:0;padding:0 0 0 20px;">{li}</ol>'
    else:
        todo_inner = '<div style="color:#666;padding:8px;">No leads ready to hand off right now.</div>'
    todo_block = section(
        "Leads to close today",
        ("We have already replied and warmed these leads. Each item is the next step for you "
         "(the closer) to negotiate and close, so you just pick up where the reply left off."),
        todo_inner,
    )

    # ── Recent replies (full content) ──
    rr = a["recent_replies"]
    if rr:
        rows = []
        for r in rr:
            intent = classify_intent(r.get("subject"), r.get("body_snippet"))
            color = {"positive": GREEN, "neutral": MUTED, "negative": AMBER,
                     "auto_reply": MUTED, "unsubscribe": RED}.get(intent, MUTED)
            handling, hcolor = reply_handling(r)
            snippet = (r.get("body_snippet") or "").replace("\\n", " ").replace("\n", " ")[:210]
            rows.append([
                f'<code style="font-family:monospace;font-size:11px;">{escape(r.get("received_at", "")[:16])}</code>',
                escape(r.get("from_addr", "")),
                escape(r.get("subject", "")[:52]),
                colored(intent, color),
                colored(handling, hcolor),
                f'<span style="color:#444;font-size:12px;">{escape(snippet)}</span>',
            ])
        reply_inner = table(
            ["When (UTC)", "From", "Subject", "Intent", "Handling", "Snippet"],
            rows,
            ["left", "left", "left", "center", "center", "left"],
        )
    else:
        reply_inner = '<div style="color:#666;padding:8px;">No replies in the last 7 days.</div>'
    reply_desc = ("Every reply to your campaign, classified by intent. Positive replies are routed to "
                  "your booking link as they arrive; negatives and unsubscribes are handled automatically."
                  if client_mode else
                  "Every cold-outreach reply, with how the pipeline handled it: auto-replied (Calendly sent from info@), drafted for your approval, suppressed, or pending. Positive Aureon leads are auto-booked; everything else is queued for you. Instant per-reply alerts also fire as they arrive (subject prefix [REPLY ALERT]).")
    reply_block = section(
        "Recent replies (last 7d)",
        reply_desc,
        reply_inner,
    )

    # ── Full inbox digest (everything that hit info@, 24h) ──
    inbox = a["inbox_24h"]
    if inbox:
        irows = []
        for r in inbox:
            klass = r.get("class") or "—"
            kcolor = {"reply": GREEN, "bounce": RED, "complaint": RED,
                      "auto_reply": MUTED, "unrelated": MUTED}.get(klass, MUTED)
            isnip = (r.get("body_snippet") or "").replace("\\n", " ").replace("\n", " ")[:160]
            irows.append([
                f'<code style="font-family:monospace;font-size:11px;">{escape(r.get("received_at", "")[:16])}</code>',
                escape((r.get("from_addr") or "")[:38]),
                escape((r.get("subject") or "")[:50]),
                colored(klass, kcolor),
                f'<span style="color:#444;font-size:12px;">{escape(isnip)}</span>',
            ])
        inbox_inner = table(
            ["When (UTC)", "From", "Subject", "Type", "Snippet"],
            irows, ["left", "left", "left", "center", "left"])
    else:
        inbox_inner = '<div style="color:#666;padding:8px;">No mail to info@ in the last 24h.</div>'
    inbox_block = section(
        f"Full inbox — everything to info@ (last 24h, {len(inbox)})",
        "Every email that landed in info@ since yesterday, across all types. The poller auto-marks these read, so this is your catch-all so nothing slips by.",
        inbox_inner,
    )
    # This "everything that hit info@" digest is an OPERATOR-only catch-all (info@
    # is the agency inbox). It must never appear in a per-client report, even after
    # scoping. Belt-and-braces with the scope_to_profile replies_all fix.
    if client_mode:
        inbox_block = ""

    # ── Alerts ──
    bounces = a["todays_bounces"]
    suppressions = a["new_suppressions"]
    alert_inner = ""
    if bounces:
        rows = [[
            escape(b["to_addr"]),
            f'<code style="font-family:monospace;font-size:11px;">{escape((b.get("from_addr") or "").split("@")[0])}</code>',
            f"step {b.get('step_n','?')}",
            escape((b.get("error") or "").replace('"', "'")[:80]),
        ] for b in bounces[:25]]
        alert_inner += table(
            ["Bounced address", "Sender persona", "Step", "Reason"],
            rows,
            ["left", "left", "left", "left"],
        )
    if suppressions:
        rows = [[escape(p["email"]),
                 escape(p.get("verification_method") or "manual")]
                for p in suppressions[:25]]
        alert_inner += table(
            ["New suppressions today", "Reason"],
            rows,
            ["left", "left"],
        )
    if not alert_inner:
        alert_inner = '<div style="color:#666;padding:8px;">No new bounces or suppressions in the last 24h.</div>'
    alert_block = section(
        "Alerts (last 24h)",
        "Bounced addresses + newly suppressed contacts since yesterday.",
        alert_inner,
    )

    # ── Assemble ──
    if client_mode:
        # CLIENT-FACING: only the client's own campaign sections. Every cross-client / internal
        # section (per-client, per-niche, pipeline, lead-geography, inbox-actions, alerts) is
        # dropped so no Aureon or other-client data is ever exposed.
        cname = escape(client_mode.get("name") or "Your")
        c_accent = client_mode.get("accent") or GOLD
        c_dark = client_mode.get("dark") or DARK
        header_title = f"{cname} Campaign Report"
        sections = f"""
    {headline_block}
    {todo_block}
    {window_block}
    {intent_block}
    {step_block}
    {sd_block}
    {pp_block}
    {reply_block}"""
        footer = "Prepared for you by Aureon Global."
        accent, dark = c_accent, c_dark
        _logo = client_mode.get("logo")
        logo_html = (f'<img src="{escape(_logo)}" alt="{cname}" '
                     f'style="max-height:34px;width:auto;margin-bottom:10px;display:block;">'
                     if _logo else "")
    else:
        header_title = "Outreach Stack — Daily Report"
        # Consolidated system events: drain the ops_digest buffer (watchdog
        # remedies + safeguard trips that USED to email per-event) and show them as
        # ONE section. Drained only here (operator report) so each event shows once.
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sequences"))
            import ops_digest
            ops_block = ('<div style="padding:0 28px;">'
                         + ops_digest.render_html(ops_digest.drain()) + "</div>")
        except Exception:
            ops_block = ""
        sections = f"""
    {headline_block}
    {todo_block}
    {ops_block}
    {window_block}
    {intent_block}
    {step_block}
    {sd_block}
    {pp_block}
    {pc_block}
    {pn_block}
    {pl_block}
    {reply_block}
    {inbox_block}
    {alert_block}"""
        footer = (f'Generated by daily-report.py at {dt.datetime.now().strftime("%H:%M %Z")}. '
                  f'Live data: <a href="http://localhost:5173" style="color:{GOLD};text-decoration:none;">dashboard</a>.')
        accent, dark = GOLD, DARK
        logo_html = ""

    return f"""<!doctype html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:'Inter',-apple-system,'Segoe UI',Roboto,sans-serif;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#f5f5f5;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="800" cellspacing="0" cellpadding="0" border="0" style="max-width:800px;width:100%;">

  <tr><td style="background:{dark};padding:24px 28px;border-radius:6px 6px 0 0;border-top:3px solid {accent};">
    {logo_html}
    <div style="font-size:18px;font-weight:700;color:{accent};letter-spacing:.4px;">{header_title}</div>
    <div style="font-size:11px;color:#888;text-transform:uppercase;letter-spacing:1.4px;margin-top:6px;">
      {dt.datetime.now().strftime("%A, %B %d %Y")}
    </div>
  </td></tr>

  <tr><td style="padding:24px 0;">{sections}
  </td></tr>

  <tr><td style="background:{dark};padding:20px 28px;border-radius:0 0 6px 6px;text-align:center;">
    <div style="font-size:11px;color:#888;line-height:1.6;">{footer}</div>
  </td></tr>

</table>
</td></tr></table>
</body></html>"""


# ─── Send ──────────────────────────────────────────────────────────────────

def send_via_resend(*, to_addr: str, subject: str, html: str, dry: bool) -> None:
    # --to accepts a comma-separated list so a client report can reach BOTH the
    # client and the operator (e.g. "mark@mark-eting.co,info@aureonglobal.de").
    recipients = [a.strip() for a in str(to_addr).split(",") if a.strip()]
    if dry:
        print(f"[dry] would send to {recipients}, subject={subject!r}, html_len={len(html)}")
        return
    payload = {
        "from":    "Outreach Stack <reports@hi.aureonglobal.de>",
        "to":      recipients,
        "subject": subject,
        "html":    html,
        "tags":    [{"name": "kind", "value": "daily_report"}],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {RESEND_SEND_KEY}",
                  "Content-Type": "application/json",
                  "User-Agent": UA},
    )
    try:
        r = urllib.request.urlopen(req, timeout=30)
        body = json.loads(r.read())
        print(f"sent: id={body.get('id')}, to={to_addr}")
    except urllib.error.HTTPError as e:
        print(f"! send failed {e.code}: {e.read().decode()[:300]}")
        sys.exit(1)


# ─── Main ──────────────────────────────────────────────────────────────────

def scope_to_profile(data: dict, profile_slug: str) -> dict:
    """Filter the fetched data down to a SINGLE profile, so the full rich report
    renders client-scoped (e.g. LK Advertising gets the same report Aureon does,
    but only its own sends/replies/prospects). Attribution is by SENDING DOMAIN
    (collision-free), with a persona fallback, mirroring aggregate()._send_profile."""
    profs = [p for p in data["profiles"] if p["slug"] == profile_slug]
    if not profs:
        # NEVER fall back to all-clients data for an unknown slug: that leaks every
        # client's sends/replies into one client's report (2026-07-03 incident, via
        # an orphaned .tmp profile file). Return an EMPTY scope so a bad slug yields
        # an empty report, never a cross-client leak.
        print(f"  ! --profile {profile_slug}: not found; returning EMPTY scope (no cross-client leak)")
        out = dict(data)
        for k in ("profiles", "sends", "replies", "replies_all", "prospects", "sequences"):
            out[k] = []
        return out
    prof = profs[0]
    domains = {fd["domain"].lower()
               for fd in (prof.get("config", {}).get("relay", {}).get("from_domains") or [])
               if fd.get("domain")}
    personas = {p["slug"] for p in (prof.get("config", {}).get("personas") or [])}

    # The persona fallback is ONLY safe for profiles that own NO sending domains
    # of their own (a pure shared-pool rider). For a profile WITH its own domains,
    # domain matching is authoritative and the persona fallback mis-attributes
    # other brands' sends whose generic first-name persona slugs collide (e.g.
    # 'lukas'/'anna' shared across atalsolidrocks/lk/aureon). Confirmed by the
    # 2026-06-11 audit: it inflated atalsolidrocks to 1810 phantom sends.
    use_persona_fallback = not domains

    def belongs(s: dict) -> bool:
        fa = (s.get("from_addr") or "").lower()
        dom = fa.split("@", 1)[1] if "@" in fa else ""
        if dom in domains:
            return True
        if use_persona_fallback:
            return (s.get("persona_slug") or "") in personas
        return False

    prospect_emails = {(p.get("email") or "").lower()
                       for p in data["prospects"] if p.get("profile_slug") == profile_slug}
    def _reply_belongs(r: dict) -> bool:
        ps = r.get("profile_slug")
        if ps == profile_slug:
            return True
        # from_addr fallback ONLY for UNattributed replies. If a reply is already
        # tagged to another client, it is theirs even when the sender also appears
        # in this client's prospect list (overlapping lists) - never pull it in.
        if not ps and (r.get("from_addr") or "").lower() in prospect_emails:
            return True
        return False
    out = dict(data)
    out["profiles"]  = profs
    out["sends"]     = [s for s in data["sends"] if belongs(s)]
    out["replies"]   = [r for r in data["replies"] if _reply_belongs(r)]
    # CRITICAL (cross-client leak fix): replies_all feeds the "inbox to info@"
    # section of the report. It MUST be scoped too, or a per-client report leaks
    # every other client's inbound replies. Do not remove this.
    out["replies_all"] = [r for r in data.get("replies_all", []) if _reply_belongs(r)]
    out["prospects"] = [p for p in data["prospects"] if p.get("profile_slug") == profile_slug]
    out["sequences"] = [q for q in data.get("sequences", []) if q.get("profile_slug") == profile_slug]
    print(f"  scoped to {profile_slug}: sends={len(out['sends'])} "
          f"replies={len(out['replies'])} replies_all={len(out['replies_all'])} "
          f"prospects={len(out['prospects'])}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default="info@aureonglobal.de")
    ap.add_argument("--profile", default=None,
                    help="scope the whole report to one profile (e.g. lk-advertising) — a client report")
    ap.add_argument("--subject", default=None, help="override the email subject")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    print("fetching data from Supabase...")
    data = fetch_all_data()
    print(f"  profiles={len(data['profiles'])} sends={len(data['sends'])} "
          f"replies={len(data['replies'])} prospects={len(data['prospects'])} runs={len(data['runs'])}")

    if args.profile:
        data = scope_to_profile(data, args.profile)

    print("aggregating metrics...")
    agg = aggregate(data)

    print("rendering HTML...")
    client_mode = None
    if args.profile:
        pname = (data["profiles"][0]["name"] if data["profiles"] else args.profile)
        # Strip any stale descriptor tail after a dash so the client header reads cleanly.
        pname = re.split(r"\s+[—–-]\s+", pname)[0].strip()
        client_mode = {"name": pname, "accent": "#3d4848", "dark": "#2b2a2b"}
    html = render_html(agg, client_mode=client_mode)

    if args.subject:
        subject = args.subject
    elif args.profile:
        pname = (data["profiles"][0]["name"] if data["profiles"] else args.profile)
        # Hard no-em-dash rule: strip any em/en dash that slips in via the profile name.
        pname = pname.replace(" — ", " - ").replace("—", "-").replace("–", "-")
        subject = f"{pname} - campaign report - {dt.datetime.now().strftime('%a %b %d')} - {agg['today']['sent']} sent, {agg['today']['real_replies']} replied"
    else:
        subject = f"Outreach Daily Report - {dt.datetime.now().strftime('%a %b %d')} - {agg['today']['sent']} sent, {agg['today']['real_replies']} replied"
    print(f"sending to {args.to} (dry={args.dry})...")
    send_via_resend(to_addr=args.to, subject=subject, html=html, dry=args.dry)
    return 0


if __name__ == "__main__":
    sys.exit(main())
