# -*- coding: utf-8 -*-
"""seller-outreach.py — when a prospect REPLIES (e.g. with their postal code or
interest), draft a unique, company-specific FOLLOW-UP in the original persona's
voice that drives to the operator's Calendly, queue it for the operator's
approval, and email a per-lead tracking digest.

This is the "seller outreach" layer on top of reply-autodraft.py. Difference:
  - reply-autodraft writes a generic short reply.
  - seller-outreach RESEARCHES the prospect's company (scrapes their website),
    builds a unique pitch referencing their actual business + what they wrote,
    injects the operator's Calendly link, tracks per-lead status, and sends the
    operator a richer digest (company, website, persona, full prior thread,
    what they wrote, the proposed follow-up).

SAFETY (unchanged from the stack's design):
  - APPROVE-FIRST. Never emails the prospect directly. The operator reviews
    every draft and hits send (reply_to is the prospect).
  - Hard suppression: laso.finance + own-brand domains are never engaged.
  - Only real, enrolled, non-unsubscribed prospects are drafted.
  - Opt-out text in the reply -> acknowledge-and-stop, no pitch.

STATUS TRACKING (no schema migration — stored in prospects.custom_fields.seller_outreach):
    { "status": "replied|drafted|sent|booked|returned",
      "site_summary": "...", "drafted_at": "...", "sent_at": "...",
      "booked_at": "...", "returned_at": "..." }

LEAD RETURN: `seller-outreach.py return <prospect_email>` emails the end-client
(per-brand return_to address) the handed-back lead with the full context, and
stamps status=returned.

CONFIG:
  - SELLER_OUTREACH_CALENDLY in sequences/hostinger.env = the operator's Calendly
    link injected into every follow-up (one link for all brands). Until set, a
    visible <<SET CALENDLY LINK>> placeholder is used and the digest flags it.

USAGE:
    py seller-outreach.py once               # one pass over undrafted replies (LIVE queue)
    py seller-outreach.py once --dry         # print drafts + digests, send/write nothing
    py seller-outreach.py once --limit 5
    py seller-outreach.py return <email>     # hand a closed lead back to the client
"""
from __future__ import annotations

import argparse
import datetime as dt
import html as _html
import json
import os
import re
import shutil
import smtplib
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from profile_lib import list_profiles  # noqa: E402

try:
    import httpx  # used for the website scrape only
except Exception:
    httpx = None

UA = "local-email-stack seller-outreach/1.0"
OPERATOR_ADDR = "info@aureonglobal.de"

# REVIEW GATE: by default, queue seller-outreach follow-ups for the human review popup
# (reply-review.py) instead of auto-sending, so EVERY AI reply to a prospect is gated the
# same way reply-autodraft.py is. Set LES_REVIEW_GATE=0 to restore the old auto-send.
REVIEW_GATE = os.environ.get("LES_REVIEW_GATE", "1") == "1"
ALERT_FROM = "Seller Outreach <drafts@hi.aureonglobal.de>"
_CLAUDE_EXE = r"D:\npm-global\node_modules\@anthropic-ai\claude-code\bin\claude.exe"
CLAUDE_CMD = os.environ.get("CLAUDE_CLI") or (_CLAUDE_EXE if os.path.exists(_CLAUDE_EXE) else r"D:\npm-global\claude.cmd")
CALENDLY_PLACEHOLDER = "<<SET CALENDLY LINK: SELLER_OUTREACH_CALENDLY in hostinger.env>>"


# ─── env / supabase ──────────────────────────────────────────────────────────

def load_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


SUPA = load_env(REPO / "sequences" / "supabase.env")
HOST = load_env(REPO / "sequences" / "hostinger.env")
URL = SUPA["SUPABASE_URL"].rstrip("/")
KEY = SUPA["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
RESEND_KEY = (HOST.get("RESEND_NEW_ACCOUNT_API_KEY")
              or HOST.get("RESEND_FULL_ACCESS_API_KEY")
              or HOST.get("RESEND_API_KEY", ""))
CALENDLY = HOST.get("SELLER_OUTREACH_CALENDLY", "").strip() or CALENDLY_PLACEHOLDER

# Own daily limit for the seller-outreach stage. Counted INSIDE the cold cap (a
# follow-through send is still a send from the same warmed pool), so warm replies
# get drafted first but the combined total never blows per-domain warmup. Override
# with SELLER_OUTREACH_DAILY_CAP in hostinger.env.
try:
    DAILY_CAP = int(HOST.get("SELLER_OUTREACH_DAILY_CAP", "40"))
except ValueError:
    DAILY_CAP = 40


# ── Hard suppression (mirrors reply-autodraft.py) ────────────────────────────
SUPPRESS_ADDRS = {"hunter@laso.finance"}
SUPPRESS_DOMAINS = {
    "laso.finance",
    "aureonglobal.de", "algoalpha.io", "atalsolidrocks.com", "atalsolidrocks.io",
    "diraya.ca", "ener-g-beratung.de", "ener-g-beratung.org",
    "ener-g-beratung.com", "ener-g-beratung.store", "wolt.com",
}


def is_suppressed(addr: str) -> str | None:
    a = (addr or "").lower().strip()
    if not a:
        return "empty"
    if a in SUPPRESS_ADDRS:
        return "suppressed-address"
    dom = a.split("@", 1)[1] if "@" in a else ""
    if dom in SUPPRESS_DOMAINS:
        return f"suppressed-domain:{dom}"
    return None


# Opt-out intent in the prospect's reply -> acknowledge and stop, do not pitch.
_OPTOUT_RX = re.compile(
    r"\b(unsubscribe|opt[\s-]?out|remove me|stop emailing|take me off|"
    r"not interested|no thank|kein interesse|kein bedarf|abmelden|austragen|"
    r"nicht interessiert|nein danke|do not contact|leave me alone)\b", re.I)

# A reply that IS just a bare negative ("NEIN", "No", "Nope", "Non") is a hard
# decline — matched on the WHOLE stripped top-reply so a longer interested reply
# that merely contains the word ("nein, aber Dienstag passt") is NOT caught.
# Added after a NEIN reply got a follow-up auto-sent to it (2026-07-17).
_BARE_NO_RX = re.compile(r"^\W*(no|nein|nope|non|stop|kein interesse|nein danke|kein bedarf)\W*$", re.I)


def is_optout(text: str) -> bool:
    t = (text or "").strip()
    return bool(_OPTOUT_RX.search(t) or _BARE_NO_RX.match(t))

# A reply asking for the free list/sellers (keyword, or a short ZIP-dominated
# reply) gets the value delivered first and is NEVER pitched a Calendly link.
_LISTKW_RX = re.compile(r"\b(list|probate|the report|home value|send (?:me )?(?:the |my )?(?:list|report|sellers|leads)|free (?:list|report))\b", re.I)


def is_list_request(subject: str | None, body: str | None) -> bool:
    hay = f"{subject or ''}\n{body or ''}"
    if _LISTKW_RX.search(hay):
        return True
    compact = re.sub(r"\s+", " ", (body or "")).strip()
    if re.search(r"\b\d{5}\b", compact) and len(re.sub(r"[^a-zA-Z]", "", compact)) < 60:
        return True
    return False


def supa_get(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=40).read())


def supa_patch(path: str, body: dict) -> None:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}",
                                 data=json.dumps(body).encode(),
                                 headers={**H, "Prefer": "return=minimal"},
                                 method="PATCH")
    urllib.request.urlopen(req, timeout=30).read()


def active_prospect(addr: str) -> dict | None:
    rows = supa_get("prospects?email=eq." + urllib.parse.quote((addr or "").lower())
                    + "&select=id,profile_slug,company,website,city,email,"
                      "unsubscribed,custom_fields&limit=1")
    if not rows:
        return None
    r = rows[0]
    if r.get("unsubscribed"):
        return None
    return r


# ─── thread reconstruction ───────────────────────────────────────────────────

_QUOTE_LINE = re.compile(
    r"^(_{5,}|-{5,}|from:|sent:|to:|subject:|cc:|on .+wrote:|on .+\b(?:AM|PM)\b.*|"
    r"on \w+,? .*\d{4}.*|am .+schrieb .*:|<[^>]+@[^>]+>\s*:?$|>.*)", re.I)


def top_reply_text(body: str) -> str:
    out = []
    for ln in (body or "").splitlines():
        if _QUOTE_LINE.match(ln.strip()) or "________" in ln:
            break
        out.append(ln)
    return "\n".join(out).strip() or (body or "").strip()


def prior_thread(run_id: str | None, prospect_email: str) -> str:
    """Reconstruct what WE sent before they replied: the send_log subjects/steps
    for this run, newest first. Gives the operator the full pre-reply context."""
    if not run_id:
        return "(no run_id — could not reconstruct the prior thread)"
    rows = supa_get(f"send_log?run_id=eq.{run_id}&select=step_n,subject,sent_at"
                    f"&order=step_n.asc&limit=20")
    if not rows:
        return "(no prior sends found for this run)"
    lines = []
    for s in rows:
        when = (s.get("sent_at") or "")[:10]
        lines.append(f"  step {s.get('step_n')}  {when}  \"{s.get('subject','')}\"")
    return "\n".join(lines)


# ─── persona / brand resolution ──────────────────────────────────────────────

_PROFILE_CACHE: dict[str, list] = {}


def all_profiles() -> list[dict]:
    if "_all" not in _PROFILE_CACHE:
        _PROFILE_CACHE["_all"] = list_profiles()
    return _PROFILE_CACHE["_all"]


def resolve_brand_persona(reply: dict) -> tuple[dict | None, dict | None]:
    persona_slug = None
    from_dom = None
    run_id = reply.get("run_id")
    if run_id:
        rows = supa_get(f"send_log?run_id=eq.{run_id}&select=persona_slug,from_addr"
                        f"&order=step_n.asc&limit=1")
        if rows:
            persona_slug = rows[0].get("persona_slug")
            fa = (rows[0].get("from_addr") or "").lower()
            from_dom = fa.split("@", 1)[1] if "@" in fa else None
    if not from_dom:
        to = (reply.get("to_addr") or "").lower()
        from_dom = to.split("@", 1)[1] if "@" in to else None
    for prof in all_profiles():
        doms = {d["domain"].lower() for d in prof.get("relay", {}).get("from_domains", [])}
        if from_dom and from_dom in doms:
            persona = None
            if persona_slug:
                persona = next((p for p in prof.get("personas", [])
                                if p.get("slug") == persona_slug), None)
            if not persona and prof.get("personas"):
                persona = prof["personas"][0]
            return prof, persona
    return None, None


# ─── company website research ────────────────────────────────────────────────

_TAG_RX = re.compile(r"<[^>]+>")
_WS_RX = re.compile(r"\s+")


def scrape_company_site(prospect: dict) -> str:
    """Fetch the prospect's company site and return a short plain-text summary
    (first ~1200 chars of visible text) for the copywriter to reference. Best
    effort: returns '' on any failure. Cached nowhere — one fetch per lead."""
    if httpx is None:
        return ""
    url = (prospect.get("website") or "").strip()
    if not url:
        # derive from the email domain
        email = (prospect.get("email") or "")
        dom = email.split("@", 1)[1] if "@" in email else ""
        if dom and "." in dom and not dom.endswith((".gmail.com", "t-online.de")):
            url = f"https://{dom}"
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        with httpx.Client(timeout=15, follow_redirects=True,
                          headers={"User-Agent": UA, "Accept-Language": "de,en;q=0.8"}) as c:
            r = c.get(url)
            if r.status_code >= 400:
                return ""
            html = r.text
    except Exception:
        return ""
    # strip scripts/styles then tags
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.I | re.S)
    text = _WS_RX.sub(" ", _TAG_RX.sub(" ", html)).strip()
    return text[:1200]


# ─── Claude follow-up draft via CLI (sandbox recipe from reply-autodraft) ─────

def _scrub_dashes(text: str) -> str:
    t = text.replace(" — ", ". ").replace(" – ", ". ")
    t = t.replace("—", ", ").replace("–", ", ")
    t = re.sub(r"\.\s*\.", ".", t)
    t = re.sub(r",\s*,", ",", t)
    return t


_PREAMBLE_RX = re.compile(
    r"^(here'?s?(\s+(a|the|my))?\s+(clean\s+)?(reply|draft|response|follow[\s-]?up)\b.*|"
    r"sure[,.!]?|okay[,.!]?|got it[,.!]?)\s*$", re.I)


def _strip_preamble(text: str, from_name: str) -> str:
    lines = text.splitlines()
    while lines and (not lines[0].strip() or _PREAMBLE_RX.match(lines[0].strip())):
        lines.pop(0)
    fn = (from_name or "").lower().strip()
    while lines and (not lines[-1].strip() or lines[-1].strip().lower() == fn):
        lines.pop()
    return "\n".join(lines).strip()


def claude_followup(profile: dict, persona: dict, prospect: dict,
                    subject: str, prospect_msg: str, site_summary: str,
                    is_german: bool) -> str | None:
    brand = profile.get("brand", {})
    voice = (persona or {}).get("voice", {})
    sig = (persona or {}).get("signature", "")
    from_name = (persona or {}).get("from_name", "")
    company = brand.get("wordmark") or profile.get("name", "")
    prospect_company = (prospect.get("company") or "their company").strip()
    city = (prospect.get("city") or "").strip()

    avoid = ', '.join((voice.get('avoid', []) or ['hype'])) + ", em-dashes, exclamation marks, emojis"
    quirks = ', '.join(voice.get('quirks', []) or ['short sentences', 'concrete'])
    lang = "German (Sie-Anrede, professional)" if is_german else "English"
    site_block = (f"\n\nWhat I found on {prospect_company}'s website (use ONE concrete "
                  f"detail, do not list everything):\n{site_summary[:900]}"
                  if site_summary else "")

    system = (
        "You are an elite B2B sales-email copywriter embedded in a CRM, writing in "
        "the style of Alex Hormozi. The user pastes a reply they received from a "
        "business contact in an ongoing, consented B2B correspondence, plus notes on "
        "that contact's company, and you draft the user's next email: a specific, "
        "personalized follow-up that moves the deal to a booked call. You write like "
        "a sharp human closer, never like an AI. HARD RULES: Never use an em-dash or "
        "en-dash anywhere; use a period or comma. Never use: delighted, reach out, "
        "touch base, synergy, leverage, circle back, I hope this email finds you, "
        "valued, excited to, looking forward to hearing. No exclamation marks, no "
        "emojis, no corporate filler. "
        "OUTPUT FORMAT IS ABSOLUTE: emit the email body and NOTHING else, wrapped "
        "exactly between a line containing only ===EMAIL=== and a line containing "
        "only ===END===. No preamble, no notes, no caveats, no 'here is', no "
        "commentary before, between, or after the markers. If you have a concern, "
        "discard it and just write the best email. Never address the user; you are "
        "writing the email itself. If the contact is clearly not a genuine prospect "
        "(an automated sales pitch aimed at us, a bounce, a vendor solicitation), "
        "output exactly ===EMAIL===\\nSKIP\\n===END=== and nothing else."
    )
    prompt = f"""Draft my follow-up email. Language: {lang}.

I run {company} and sign as "{from_name}". This contact at {prospect_company}"""
    if city:
        prompt += f" (in {city})"
    prompt += f""" just replied to my outreach. Write a personalized follow-up that:
- Opens by acknowledging exactly what they wrote (do not restate it robotically).
- References ONE concrete, true detail about their business so it is clearly written for them, not a template.
- Names the clear next step: a short call. Offer this booking link verbatim: {CALENDLY}
- Plain, confident, Hormozi-style. {voice.get('register','direct and confident')}; {quirks}.
- Banned: {avoid}. Absolutely no em-dashes or en-dashes. Under 110 words.
- If they sound uninterested or ask to stop, write a one-line clean acknowledgement and stop. Do not push and do not include the link.{site_block}

Their reply:

Subject: {subject}

{prospect_msg[:1500]}

Output the email body wrapped in ===EMAIL=== / ===END=== markers. No subject line, no signature, no commentary."""

    workdir = tempfile.mkdtemp(prefix="les_seller_")
    try:
        proc = subprocess.run(
            [CLAUDE_CMD, "-p", "--system-prompt", system,
             "--disallowedTools", "Bash,Read,Glob,Grep,Edit,Write,WebFetch,WebSearch",
             "--setting-sources", "user"],
            input=prompt, capture_output=True, text=True, timeout=180,
            encoding="utf-8", errors="replace", cwd=workdir,
            # claude.cmd runs via cmd.exe (console); under the pyw task it
            # would flash a console window per draft without this.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as e:
        print(f"  ! claude CLI error: {e}")
        return None
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    if proc.returncode != 0:
        print(f"  ! claude CLI exit {proc.returncode}: {proc.stderr[:200]}")
        return None
    text = (proc.stdout or "").strip()
    text = re.sub(r"^Warning: no stdin data received.*?\n", "", text, flags=re.I).strip()
    if not text:
        return None
    # Extract ONLY what is between the markers — this strips any model preamble,
    # caveats, or trailing notes that leaked despite the system prompt.
    m = re.search(r"===EMAIL===\s*(.*?)\s*===END===", text, flags=re.S)
    if not m:
        # Model refused the format and wrote commentary instead (usually because
        # the reply is too terse or the Calendly link is still a placeholder).
        # Do NOT dump that meta-text into the operator queue — signal a soft
        # failure so the caller uses the clean template.
        print("     ! model did not emit ===EMAIL=== markers — falling back to template")
        return None
    body = m.group(1).strip()
    # Model signalled this is not a genuine prospect — caller drops it.
    if body.strip().upper() == "SKIP":
        return "__SKIP__"
    body = _scrub_dashes(body)
    body = _strip_preamble(body, from_name)
    if sig and sig.split("\n")[0].lower() not in body.lower():
        body = f"{body}\n\n{sig}"
    return body


def template_followup(persona: dict, is_german: bool) -> str:
    sig = (persona or {}).get("signature", "")
    if is_german:
        body = ("Danke fuer Ihre Antwort. Damit ich nichts doppelt mache: am "
                f"schnellsten klaeren wir das in einem kurzen Gespraech. Suchen Sie "
                f"sich einen Termin aus, der passt: {CALENDLY}")
    else:
        body = ("Thanks for the reply. Quickest way to move this forward is a short "
                f"call. Grab a time that works for you here: {CALENDLY}")
    return _scrub_dashes(body) + ("\n\n" + sig if sig else "")


# ─── status tracking (prospects.custom_fields.seller_outreach) ───────────────

def get_status(prospect: dict) -> dict:
    return dict((prospect.get("custom_fields") or {}).get("seller_outreach") or {})


def set_status(prospect: dict, **fields) -> None:
    cf = dict(prospect.get("custom_fields") or {})
    so = dict(cf.get("seller_outreach") or {})
    so.update(fields)
    cf["seller_outreach"] = so
    supa_patch(f"prospects?id=eq.{prospect['id']}", {"custom_fields": cf})


# ─── operator digest email ───────────────────────────────────────────────────

def _original_from_addr(reply: dict) -> str:
    """The exact subdomain address that first emailed this prospect, so the
    auto-sent follow-up threads in their inbox. Looked up from the run's first
    send_log row; falls back to '' if unknown."""
    rid = reply.get("run_id")
    if not rid:
        return ""
    rows = supa_get(f"send_log?run_id=eq.{rid}&select=from_addr&order=step_n.asc&limit=1")
    if rows and rows[0].get("from_addr"):
        return rows[0]["from_addr"]
    return ""


def auto_send_followup(*, prospect: dict, profile: dict, persona: dict,
                       subject: str, draft: str, reply: dict, dry: bool) -> bool:
    """Send the seller-outreach follow-up STRAIGHT to the prospect, always with a
    copy to info@aureonglobal.de (Bcc) so the operator sees every reply that goes
    out. Routing mirrors reply-autodraft: aureon sends FROM info@aureonglobal.de
    via Hostinger SMTP; every other brand sends via its own Resend relay from the
    exact address that first emailed the prospect (so it threads + stays on-brand).
    Returns True if the prospect send fired."""
    prospect_email = prospect.get("email") or ""
    persona_name = (persona or {}).get("from_name") or "there"
    slug = profile.get("slug")
    reply_subject = subject if (subject or "").lower().startswith("re:") else f"Re: {subject}"

    if slug == "aureon":
        user = HOST.get("SMTP_USER") or OPERATOR_ADDR
        pw = HOST.get("SMTP_PASS")
        if dry:
            print(f"  [DRY] would AUTO-SEND follow-up to {prospect_email} from info@ (Bcc info@)")
            return True
        if not pw:
            print("  ! no SMTP_PASS in hostinger.env — cannot auto-send follow-up")
            return False
        m = MIMEText(draft, "plain", "utf-8")
        m["Subject"] = reply_subject[:200]
        # persona_name already carries the brand ("Anna from Aureon Global"); use
        # it as-is so the From header doesn't double to "... from Aureon Global
        # from Aureon Global".
        m["From"] = f"{persona_name} <{user}>"
        m["To"] = prospect_email
        m["Reply-To"] = user
        try:
            with smtplib.SMTP_SSL("smtp.hostinger.com", 465,
                                  context=ssl.create_default_context()) as s:
                s.login(user, pw)
                # info@ Bcc'd: the copy lands in the operator's webmail.
                s.sendmail(user, [prospect_email, OPERATOR_ADDR], m.as_string())
            print(f"  ✓ AUTO-SENT follow-up to {prospect_email} (copy to info@)")
            return True
        except Exception as e:
            print(f"  ! auto-send follow-up failed: {e}")
            return False

    # Non-aureon: send via the brand's own Resend relay from the original sender.
    if dry:
        print(f"  [DRY] would AUTO-SEND follow-up to {prospect_email} via Resend (Bcc info@)")
        return True
    from_addr = _original_from_addr(reply)
    key = _brand_resend_key(slug)
    if not from_addr or not key:
        print(f"  ! cannot auto-send ({slug}): from_addr={from_addr or 'MISSING'} "
              f"key={'yes' if key else 'MISSING'}")
        return False
    payload = {
        "from": f"{persona_name} <{from_addr}>",
        "to": [prospect_email],
        "bcc": [OPERATOR_ADDR],
        "reply_to": from_addr,
        "subject": reply_subject[:200],
        "text": draft,
        "tags": [{"name": "kind", "value": "seller_outreach_autosend"}],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(payload).encode(),
        method="POST", headers={"Authorization": f"Bearer {key}",
                                "Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=20)
        print(f"  ✓ AUTO-SENT follow-up to {prospect_email} via Resend (copy to info@)")
        return True
    except Exception as e:
        print(f"  ! auto-send follow-up failed ({slug}): {e}")
        return False


def _brand_resend_key(slug: str) -> str:
    """Per-brand Resend key from profiles/<slug>.private.json (relay.resend_api_key),
    falling back to the shared RESEND_KEY."""
    try:
        priv = REPO / "profiles" / f"{slug}.private.json"
        if priv.exists():
            p = json.loads(priv.read_text(encoding="utf-8"))
            k = (p.get("relay") or {}).get("resend_api_key")
            if k:
                return k
    except Exception:
        pass
    return RESEND_KEY


def send_digest(*, prospect: dict, profile: dict, persona: dict, subject: str,
                prospect_msg: str, draft: str, site_summary: str,
                thread: str, dry: bool) -> bool:
    esc = _html.escape
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    company = prospect.get("company") or "(unknown company)"
    website = prospect.get("website") or "(no website on file)"
    persona_name = (persona or {}).get("from_name", "?")
    profile_name = profile.get("name", profile.get("slug", "?"))
    calendly_warn = ("<p style='color:#b91c1c;font-size:12px;margin:8px 0 0'>"
                     "&#9888; No Calendly link set (SELLER_OUTREACH_CALENDLY). The draft "
                     "contains a placeholder &mdash; set the link before sending.</p>"
                     if CALENDLY == CALENDLY_PLACEHOLDER else "")

    body_html = f"""\
<div style="font-family:system-ui,-apple-system,sans-serif;color:#1e293b;max-width:640px">
  <h2 style="margin:0 0 4px 0;color:#16a34a">&#129534; Seller-outreach lead &mdash; follow-up SENT</h2>
  <p style="margin:0 0 12px 0;color:#64748b;font-size:13px">
    {esc(profile_name)} &middot; persona <b>{esc(persona_name)}</b> &middot; auto-sent to
    <b>{esc(prospect.get('email',''))}</b>. This is your copy for the record. To add
    anything, just Reply (Reply-To is the prospect).</p>

  <table style="font-size:13px;border-collapse:collapse;margin:0 0 14px 0">
    <tr><td style="color:#64748b;padding:2px 10px 2px 0">Company</td><td><b>{esc(company)}</b></td></tr>
    <tr><td style="color:#64748b;padding:2px 10px 2px 0">Website</td><td>{esc(website)}</td></tr>
    <tr><td style="color:#64748b;padding:2px 10px 2px 0">Replied to</td><td>{esc(persona_name)} ({esc(profile.get('slug',''))})</td></tr>
  </table>

  <p style="margin:14px 0 4px 0"><b>Suggested subject:</b> {esc(reply_subject)}</p>
  <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:14px;
              white-space:pre-wrap;font-size:14px;line-height:1.5">{esc(draft)}</div>
  {calendly_warn}

  <hr style="border:none;border-top:1px solid #e2e8f0;margin:18px 0">
  <p style="margin:0 0 4px 0;color:#64748b;font-size:12px"><b>What they just wrote:</b></p>
  <pre style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:8px;
              font-family:ui-monospace,monospace;font-size:12px;color:#334155">{esc(prospect_msg[:1800])}</pre>

  <p style="margin:12px 0 4px 0;color:#64748b;font-size:12px"><b>What we sent before they replied:</b></p>
  <pre style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:8px;
              font-family:ui-monospace,monospace;font-size:12px;color:#334155">{esc(thread)}</pre>

  <p style="margin:12px 0 4px 0;color:#64748b;font-size:12px"><b>Company site notes (auto-scraped):</b></p>
  <pre style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:8px;
              font-family:ui-monospace,monospace;font-size:11px;color:#475569">{esc((site_summary or '(none)')[:900])}</pre>

  <p style="margin:14px 0 0 0;color:#94a3b8;font-size:11px">
    Drafted by seller-outreach.py via the local Claude CLI and auto-sent to the
    prospect (you were Bcc'd). After you close it, run
    <code>py seller-outreach.py return {esc(prospect.get('email',''))}</code> to hand the lead back to the client.</p>
</div>"""

    if dry:
        print(f"  [DRY] would email digest to {OPERATOR_ADDR} for {prospect.get('email')}")
        print("  ---- FOLLOW-UP DRAFT ----")
        print(draft)
        print("  -------------------------")
        return True
    if not RESEND_KEY:
        print("  ! no RESEND key — cannot send digest")
        return False
    payload = {
        "from": ALERT_FROM, "to": [OPERATOR_ADDR],
        "reply_to": prospect.get("email"),
        "subject": f"[SELLER LEAD] {company}: {reply_subject}"[:200],
        "html": body_html,
        "headers": {"X-LES-Alert": "seller-outreach"},
        "tags": [{"name": "kind", "value": "seller_outreach"}],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(payload).encode(),
        method="POST", headers={"Authorization": f"Bearer {RESEND_KEY}",
                                "Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=20)
        return True
    except urllib.error.HTTPError as e:
        print(f"  ! digest send failed: HTTP {e.code} {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"  ! digest send failed: {e}")
        return False


# ─── lead return to client ───────────────────────────────────────────────────

def brand_return_to(profile: dict) -> str | None:
    """Where to hand a closed lead back. Prefer a persona reply_to that is NOT an
    own-brand inbox (e.g. ENER-G -> loisha@energieberatung-schwabenland.de), else
    the profile's notices_email."""
    for p in profile.get("personas", []):
        rt = (p.get("reply_to") or "").lower()
        if rt and "aureonglobal.de" not in rt:
            dom = rt.split("@", 1)[1] if "@" in rt else ""
            if dom not in SUPPRESS_DOMAINS:
                return p["reply_to"]
    return (profile.get("company", {}) or {}).get("notices_email")


def cmd_return(email: str, dry: bool) -> int:
    prospect = active_prospect(email)
    if not prospect:
        # allow returning even unsubscribed/closed leads
        rows = supa_get("prospects?email=eq." + urllib.parse.quote(email.lower())
                        + "&select=id,profile_slug,company,website,city,email,custom_fields&limit=1")
        if not rows:
            print(f"no prospect row for {email}")
            return 1
        prospect = rows[0]
    profile = next((p for p in all_profiles()
                    if p.get("slug") == prospect.get("profile_slug")), None)
    if not profile:
        print(f"no profile for {prospect.get('profile_slug')}")
        return 1
    to = brand_return_to(profile)
    if not to:
        print(f"no return-to address for {profile.get('slug')}")
        return 1
    so = get_status(prospect)
    esc = _html.escape
    html = f"""\
<div style="font-family:system-ui,sans-serif;color:#1e293b;max-width:600px">
  <h2 style="color:#16a34a;margin:0 0 8px">Lead handed back from Aureon outreach</h2>
  <p>Here is a qualified lead from the {esc(profile.get('name',''))} campaign.</p>
  <table style="font-size:14px">
    <tr><td style="color:#64748b;padding:2px 10px 2px 0">Company</td><td><b>{esc(prospect.get('company') or '?')}</b></td></tr>
    <tr><td style="color:#64748b;padding:2px 10px 2px 0">Website</td><td>{esc(prospect.get('website') or '?')}</td></tr>
    <tr><td style="color:#64748b;padding:2px 10px 2px 0">Contact</td><td>{esc(prospect.get('email') or '?')}</td></tr>
    <tr><td style="color:#64748b;padding:2px 10px 2px 0">City</td><td>{esc(prospect.get('city') or '?')}</td></tr>
    <tr><td style="color:#64748b;padding:2px 10px 2px 0">Status</td><td>{esc(so.get('status','?'))}</td></tr>
  </table>
  <p style="color:#94a3b8;font-size:11px">Sent by seller-outreach.py return.</p>
</div>"""
    if dry:
        print(f"  [DRY] would return lead {prospect.get('email')} to {to}")
        return 0
    if not RESEND_KEY:
        print("  ! no RESEND key — cannot send return email")
        return 1
    payload = {"from": ALERT_FROM, "to": [to], "reply_to": OPERATOR_ADDR,
               "subject": f"Qualified lead: {prospect.get('company') or prospect.get('email')}"[:200],
               "html": html, "tags": [{"name": "kind", "value": "lead_return"}]}
    req = urllib.request.Request("https://api.resend.com/emails",
                                 data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {RESEND_KEY}",
                                          "Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        print(f"  ! return send failed: {e}")
        return 1
    set_status(prospect, status="returned",
               returned_at=dt.datetime.now(dt.timezone.utc).isoformat())
    print(f"  -> returned {prospect.get('email')} to {to}")
    return 0


# ─── main pass ───────────────────────────────────────────────────────────────

GERMAN_PROFILES = {"energ", "atalsolidrocks"}


def mark_seen(reply: dict, **extra) -> None:
    rh = dict(reply.get("raw_headers") or {})
    rh["seller_outreach_done"] = True
    rh["seller_outreach_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    rh.update(extra)
    supa_patch(f"replies?id=eq.{reply['id']}", {"raw_headers": rh})


def drafted_today() -> int:
    """Count seller-outreach follow-ups DRAFTED+queued today (UTC). A drafted
    follow-up consumes one of the day's shared sends once the operator approves
    it, so we cap drafting to DAILY_CAP/day to stay inside the warmup envelope."""
    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT00:00:00")
    rows = supa_get("replies?class=eq.reply&select=raw_headers&"
                    f"raw_headers->>seller_outreach_at=gte.{today}&limit=500")
    n = 0
    for r in rows:
        rh = r.get("raw_headers") or {}
        # only count actual drafts, not suppressed/skipped/optout marks
        if rh.get("seller_outreach_done") and not rh.get("seller_outreach_skipped"):
            n += 1
    return n


# Funnel stages tracked in prospects.custom_fields.seller_outreach.status:
#   replied -> sourced -> outreach_sent -> drafted -> sent -> booked -> sold -> returned
def funnel_counts() -> dict:
    """Roll up the seller-outreach funnel across all prospects for KPI reporting."""
    rows = supa_get("prospects?custom_fields->>seller_outreach=not.is.null&"
                    "select=custom_fields&limit=2000")
    stages = ["replied", "sourced", "drafted", "outreach_sent", "sent",
              "booked", "sold", "returned", "optout"]
    counts = {s: 0 for s in stages}
    for r in rows:
        so = (r.get("custom_fields") or {}).get("seller_outreach") or {}
        st = so.get("status")
        if st in counts:
            counts[st] += 1
    return counts


def one_pass(limit: int, dry: bool) -> dict:
    stats = {"candidates": 0, "drafted": 0, "suppressed": 0, "not_prospect": 0,
             "optout": 0, "errors": 0}
    rows = supa_get("replies?class=eq.reply&select=id,from_addr,to_addr,subject,"
                    "body_snippet,run_id,raw_headers,received_at"
                    "&order=received_at.desc&limit=200")
    todo = []
    for r in rows:
        if (r.get("raw_headers") or {}).get("seller_outreach_done"):
            continue
        frm = (r.get("from_addr") or "").lower()
        if frm.startswith(("alerts@", "drafts@", "reports@")):
            continue
        todo.append(r)
    # Daily cap: how many more follow-ups may we draft today (shared with cold cap).
    already = drafted_today()
    room = max(0, DAILY_CAP - already)
    eff_limit = min(limit, room)
    todo = todo[:eff_limit]
    stats["candidates"] = len(todo)
    stats["daily_cap"] = DAILY_CAP
    stats["drafted_before_today"] = already
    print(f"undrafted reply rows to evaluate: {len(todo)}  "
          f"(daily cap {DAILY_CAP}, already drafted today {already}, room {room})  "
          f"(Calendly: {'SET' if CALENDLY != CALENDLY_PLACEHOLDER else 'NOT SET — placeholder'})")
    if room <= 0:
        print(f"  daily seller-outreach cap reached ({already}/{DAILY_CAP}) — stopping.")
        return stats

    for r in todo:
        prospect_email = r.get("from_addr") or ""
        subject = r.get("subject") or "(no subject)"
        msg = top_reply_text(r.get("body_snippet") or "")

        reason = is_suppressed(prospect_email)
        if reason:
            print(f"  ⊘ SUPPRESSED {prospect_email}: {reason}")
            stats["suppressed"] += 1
            if not dry:
                mark_seen(r, seller_outreach_skipped=reason)
            continue

        prospect = active_prospect(prospect_email)
        if not prospect:
            print(f"  - not an active prospect: {prospect_email} — skip")
            stats["not_prospect"] += 1
            if not dry:
                mark_seen(r, seller_outreach_skipped="not_prospect")
            continue

        profile, persona = resolve_brand_persona(r)
        if not profile:
            print(f"  - could not resolve brand for {prospect_email} — skip")
            stats["errors"] += 1
            continue
        is_german = profile.get("slug") in GERMAN_PROFILES

        # opt-out -> acknowledge-and-stop draft, no pitch, no link
        if is_optout(msg):
            print(f"  ⚠ opt-out intent from {prospect_email} — acknowledge-only draft")
            stats["optout"] += 1
            sig = (persona or {}).get("signature", "")
            ack = (("Verstanden, ich melde mich nicht mehr. Danke fuer die Rueckmeldung."
                    if is_german else
                    "Understood, I will stop reaching out. Thanks for letting me know.")
                   + ("\n\n" + sig if sig else ""))
            send_digest(prospect=prospect, profile=profile, persona=persona,
                        subject=subject, prospect_msg=msg, draft=ack,
                        site_summary="", thread=prior_thread(r.get("run_id"), prospect_email),
                        dry=dry)
            if not dry:
                set_status(prospect, status="optout")
                mark_seen(r, seller_outreach_skipped="optout")
            continue

        # GATE — give-first first (mirrors reply-autodraft). A list/ZIP/sellers
        # request gets the value delivered first, never a Calendly pitch. And an
        # aureon give-first lead is only pitched once the operator unlocks it
        # (`reply-autodraft.py unlock <email>`), i.e. after it has its sellers.
        cf = prospect.get("custom_fields") or {}
        if is_list_request(subject, msg):
            print(f"  · {prospect_email}: list/sellers request — deliver first, no Calendly pitch")
            stats["skipped"] = stats.get("skipped", 0) + 1
            if not dry:
                set_status(prospect, status="replied")
                mark_seen(r, seller_outreach_skipped="list_request_deliver_first")
            continue
        if profile.get("slug") == "aureon" and not cf.get("calendly_unlocked"):
            print(f"  · {prospect_email}: give-first lead not unlocked — holding Calendly pitch")
            stats["skipped"] = stats.get("skipped", 0) + 1
            if not dry:
                mark_seen(r, seller_outreach_skipped="awaiting_unlock")
            continue

        print(f"  → {prospect_email}  [{profile.get('slug')}/{(persona or {}).get('slug','?')}]"
              f"  company={prospect.get('company')}")
        site = scrape_company_site(prospect)
        if site:
            print(f"     scraped site ok ({len(site)} chars)")
        draft = claude_followup(profile, persona, prospect, subject, msg, site, is_german)
        if draft == "__SKIP__":
            print("     model flagged not-a-genuine-prospect (auto-pitch/vendor) — skip")
            stats["not_prospect"] += 1
            if not dry:
                mark_seen(r, seller_outreach_skipped="not_genuine_prospect")
            continue
        if not draft:
            print("     CLI draft failed — using template")
            draft = template_followup(persona, is_german)
        thread = prior_thread(r.get("run_id"), prospect_email)

        # REVIEW GATE: queue the follow-up for the human popup instead of auto-sending,
        # so the operator approves / edits / blocks before it ever reaches the prospect.
        if REVIEW_GATE:
            if dry:
                print(f"     [DRY] would QUEUE FOR REVIEW: {prospect_email}")
                stats["drafted"] = stats.get("drafted", 0) + 1
                continue
            try:
                import importlib.util as _ilu
                _spec = _ilu.spec_from_file_location("reply_review", REPO / "sequences" / "reply-review.py")
                _rr = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_rr)
                _rr.enqueue(reply_id=r["id"], prospect_email=prospect_email,
                            prospect_name=prospect.get("first_name") or "",
                            prospect_text=msg or (r.get("body_snippet") or ""),
                            subject=subject, slug=profile.get("slug") or "",
                            run_id=r.get("run_id"), persona=persona, profile=profile,
                            draft=draft, deal_context="Seller-outreach follow-up (books to Calendly).",
                            unsub_token=prospect.get("unsubscribe_token"))
                set_status(prospect, status="drafted", site_summary=site[:300],
                           drafted_at=dt.datetime.now(dt.timezone.utc).isoformat())
                mark_seen(r)
                stats["drafted"] = stats.get("drafted", 0) + 1
                print(f"     QUEUED FOR REVIEW (popup will ask you to decide)")
            except Exception as e:
                print(f"     ! review-queue failed ({e}); leaving for next pass")
                stats["errors"] += 1
            continue

        # AUTO-SEND (only when LES_REVIEW_GATE=0): straight to the prospect (with info@
        # copied), then email the operator a record digest with the full context.
        sent = auto_send_followup(prospect=prospect, profile=profile, persona=persona,
                                  subject=subject, draft=draft, reply=r, dry=dry)
        send_digest(prospect=prospect, profile=profile, persona=persona,
                    subject=subject, prospect_msg=msg, draft=draft,
                    site_summary=site, thread=thread, dry=dry)
        if sent:
            stats["sent"] = stats.get("sent", 0) + 1
            if not dry:
                set_status(prospect, status="sent", site_summary=site[:300],
                           drafted_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                           sent_at=dt.datetime.now(dt.timezone.utc).isoformat())
                mark_seen(r)
        else:
            stats["errors"] += 1

    print(f"\n=== seller-outreach summary === {json.dumps(stats)}")
    try:
        print(f"=== funnel (all-time) === {json.dumps(funnel_counts())}")
    except Exception as e:
        print(f"(funnel rollup unavailable: {str(e)[:80]})")
    return stats


def funnel_pass(limit: int, dry: bool) -> dict:
    """Process inbound 'Free Home Value Report' opt-ins (source=home_value_funnel).
    Each is a CONSENTED hand-raiser (the homeowner submitted their own address +
    contact via the agent's branded capture page). For each new opt-in we draft,
    for the operator's approval, the seller-facing email that delivers the value
    report and offers the agent's call — routed to be sent on the agent's behalf.
    The booked appointment goes to the agent (custom_fields.for_agent).

    Honest scope note: the 'home value report' content itself is not auto-computed
    here (no free AVM); the draft frames the report as prepared by the agent and
    the operator/agent fills the number. The engine handles capture -> consented
    outreach -> route-to-agent, which is the real, free, defensible core."""
    stats = {"opt_ins": 0, "drafted": 0, "errors": 0, "daily_cap": DAILY_CAP}
    already = drafted_today()
    room = max(0, DAILY_CAP - already)
    rows = supa_get("prospects?source=eq.home_value_funnel&select=id,email,first_name,"
                    "last_name,company,phone,custom_fields,unsubscribed&limit=200")
    todo = []
    for p in rows:
        if p.get("unsubscribed"):
            continue
        so = (p.get("custom_fields") or {}).get("seller_outreach") or {}
        if so.get("status"):  # already in the funnel (drafted/sent/etc.)
            continue
        todo.append(p)
    todo = todo[:min(limit, room)]
    print(f"home-value opt-ins to process: {len(todo)}  (daily cap {DAILY_CAP}, "
          f"drafted today {already}, room {room}, Calendly "
          f"{'SET' if CALENDLY != CALENDLY_PLACEHOLDER else 'NOT SET'})")
    if room <= 0:
        print(f"  daily cap reached ({already}/{DAILY_CAP}) — stopping."); return stats

    for p in todo:
        stats["opt_ins"] += 1
        agent = (p.get("custom_fields") or {}).get("for_agent", "(unknown agent)")
        addr = (p.get("custom_fields") or {}).get("address") or p.get("company") or ""
        name = (p.get("first_name") or "").strip() or "there"
        sig = "Aureon Global\naureonglobal.de"
        draft = (
            f"Hi {name},\n\n"
            f"Thanks for requesting a home value report for {addr}. I am putting it "
            f"together now and will have your number and a quick read on the local "
            f"market back to you within 24 hours.\n\n"
            f"If it is easier to walk through it live, grab a time here: {CALENDLY}\n\n"
            f"Talk soon,\n{sig}"
        )
        # Queue the draft to the operator (reuse the digest emailer shape via a
        # lightweight Resend send). Reply-to = the homeowner.
        if dry:
            print(f"  [DRY] opt-in {p.get('email')} (agent {agent}, addr {addr[:40]})")
            print("   ---- DRAFT ----"); print("   " + draft.replace("\n", "\n   ")); print("   ---------------")
            stats["drafted"] += 1
            continue
        ok = _send_funnel_draft(homeowner=p, agent=agent, addr=addr, draft=draft)
        if ok:
            stats["drafted"] += 1
            set_status(p, status="drafted", funnel="home_value",
                       for_agent=agent, drafted_at=dt.datetime.now(dt.timezone.utc).isoformat())
        else:
            stats["errors"] += 1
    print(f"\n=== home-value funnel summary === {json.dumps(stats)}")
    return stats


def _send_funnel_draft(*, homeowner: dict, agent: str, addr: str, draft: str) -> bool:
    if not RESEND_KEY:
        print("  ! no RESEND key — cannot queue funnel draft"); return False
    esc = _html.escape
    body = f"""<div style="font-family:system-ui,sans-serif;color:#1e293b;max-width:620px">
  <h2 style="color:#16a34a;margin:0 0 4px">&#127968; Home-value opt-in &mdash; draft ready</h2>
  <p style="color:#64748b;font-size:13px;margin:0 0 12px">Consented inbound lead for agent
    <b>{esc(agent)}</b>. Homeowner <b>{esc(homeowner.get('email',''))}</b> requested a value
    report for <b>{esc(addr)}</b>. Edit, then Reply to send (Reply-To is the homeowner).
    Fill in the actual value number before sending.</p>
  <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:14px;
       white-space:pre-wrap;font-size:14px">{esc(draft)}</div>
  <p style="color:#94a3b8;font-size:11px;margin-top:14px">After the appointment is booked,
    run <code>py seller-outreach.py return {esc(homeowner.get('email',''))}</code> to hand
    the lead to the agent.</p></div>"""
    payload = {"from": ALERT_FROM, "to": [OPERATOR_ADDR], "reply_to": homeowner.get("email"),
               "subject": f"[HOME VALUE] {addr or homeowner.get('email','')} for {agent}"[:200],
               "html": body, "tags": [{"name": "kind", "value": "home_value_funnel"}]}
    req = urllib.request.Request("https://api.resend.com/emails",
                                 data=json.dumps(payload).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {RESEND_KEY}",
                                          "Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=20); return True
    except Exception as e:
        print(f"  ! funnel draft send failed: {e}"); return False


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_once = sub.add_parser("once", help="one pass over undrafted prospect replies")
    p_once.add_argument("--dry", action="store_true")
    p_once.add_argument("--limit", type=int, default=25)
    p_ret = sub.add_parser("return", help="hand a closed lead back to the client")
    p_ret.add_argument("email")
    p_ret.add_argument("--dry", action="store_true")
    p_fun = sub.add_parser("funnel", help="process inbound home-value opt-ins (consented sellers)")
    p_fun.add_argument("--dry", action="store_true")
    p_fun.add_argument("--limit", type=int, default=25)
    sub.add_parser("kpi", help="print the seller-outreach funnel + today's cap usage")
    args = ap.parse_args()
    if args.cmd == "once":
        one_pass(args.limit, args.dry)
        return 0
    if args.cmd == "funnel":
        funnel_pass(args.limit, args.dry)
        return 0
    if args.cmd == "return":
        return cmd_return(args.email, args.dry)
    if args.cmd == "kpi":
        print(f"daily cap: {DAILY_CAP}  |  drafted today: {drafted_today()}")
        print(f"funnel (all-time): {json.dumps(funnel_counts(), indent=2)}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
