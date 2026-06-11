# -*- coding: utf-8 -*-
"""reply-autodraft.py — AI draft-and-queue responder for prospect replies.

When a genuine prospect reply lands (imap-poll.py records it in `replies` with
class='reply' and pauses the sequence), THIS script:

  1. Finds reply rows that have NOT yet been drafted (raw_headers.autodraft_sent
     is absent).
  2. Resolves the brand + persona that originally emailed the prospect (via the
     reply's run_id -> send_log.persona_slug, falling back to the matched profile).
  3. Asks the local Claude CLI (`claude -p`, authed via the user's Max plan — NO
     API key) to draft a short, on-voice reply in that persona's voice.
  4. Emails the DRAFT to the operator (info@aureonglobal.de) via Resend, with the
     prospect's message quoted and the proposed reply ready to copy/edit/send.
     reply_to is set to the prospect so the operator can just hit Reply.
  5. Marks the reply row raw_headers.autodraft_sent=true so it is never re-drafted.

DRAFT + QUEUE FOR APPROVAL ONLY. This script never emails a prospect directly.
The operator reviews every draft and sends it by hand.

Usage:
    py reply-autodraft.py once          # one pass over undrafted replies
    py reply-autodraft.py once --dry    # print drafts, send nothing, mark nothing
    py reply-autodraft.py once --limit 5
"""
from __future__ import annotations

import argparse
import datetime as dt
import html as _html
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path
from email.mime.text import MIMEText

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from profile_lib import load_profile, list_profiles  # noqa: E402
import algoalpha_offer  # noqa: E402  — per-influencer retainer + commission terms

UA = "local-email-stack reply-autodraft/1.0"
OPERATOR_ADDR = "info@aureonglobal.de"
ALERT_FROM = "Reply Draft <drafts@hi.aureonglobal.de>"
# The Claude CLI lives in the user's npm-global on Windows. `claude` is not on the
# bash PATH but the .cmd is directly invokable.
CLAUDE_CMD = os.environ.get("CLAUDE_CLI", r"D:\npm-global\claude.cmd")


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
# The operator draft is sent FROM drafts@hi.aureonglobal.de. That domain is
# verified on the NEW-account Resend key (RESEND_NEW_ACCOUNT_API_KEY), NOT the
# full-access key — sending with the wrong key 403s ("domain not verified").
RESEND_KEY = (HOST.get("RESEND_NEW_ACCOUNT_API_KEY")
              or HOST.get("RESEND_FULL_ACCESS_API_KEY")
              or HOST.get("RESEND_API_KEY", ""))


# ── Hard suppression: addresses/domains that must NEVER be auto-drafted ──────
# Legal cases, our own brand inboxes, and known non-prospect senders. Anything
# here is skipped even if it somehow has a prospect row. Edit this list to add
# more. Matching is case-insensitive on the full address OR the domain.
SUPPRESS_ADDRS = {
    "hunter@laso.finance",            # ACTIVE LEGAL CASE — never reply
    "jake@cbstiles.com",              # user standing rule — never email Jake
}
SUPPRESS_DOMAINS = {
    "laso.finance",                   # active legal case domain
    # our own brands / internal — replies here are not prospects
    "aureonglobal.de", "algoalpha.io", "atalsolidrocks.com", "atalsolidrocks.io",
    "diraya.ca", "wolt.com",
}


def is_suppressed(addr: str) -> str | None:
    """Return a reason string if this address must not be drafted, else None."""
    a = (addr or "").lower().strip()
    if not a:
        return "empty"
    if a in SUPPRESS_ADDRS:
        return "suppressed-address"
    dom = a.split("@", 1)[1] if "@" in a else ""
    if dom in SUPPRESS_DOMAINS:
        return f"suppressed-domain:{dom}"
    return None


# ── Positive call-intent → Calendly auto-reply ──────────────────────────────
# A warm reply that asks to talk/meet gets an immediate Calendly link from
# info@ (no operator step). Order is defensive: opt-out, unsubscribe, negative
# and auto-responder patterns each VETO a positive match, so "not interested"
# or "out of office" can never trigger a booking link.
_AR_AUTO  = re.compile(r"\b(out of office|out-of-office|vacation|automatic(?:ally)?\s+reply|auto[-\s]?reply|away from (?:my )?(?:desk|office|email)|on (?:vacation|holiday|leave)|abwesenheit)\b", re.I)
_AR_UNSUB = re.compile(r"\b(unsubscribe|remove me|please remove|stop sending|stop emailing|stop contacting|do not (?:contact|email)|cease and desist|take me off)\b", re.I)
_AR_NEG   = re.compile(r"\b(not interested|no thanks|no thank you|not relevant|not a fit|not for us|wrong (?:person|contact|number)|please stop|how is this not a pitch|is this (?:a |just a )?pitch|spam)\b", re.I)
_AR_POS   = re.compile(r"\b(interested|let'?s (?:chat|talk|connect|schedule|hop on|jump on)|sounds (?:good|great)|happy to (?:chat|talk|connect|jump|hop)|tell me more|share more|learn more|set up a (?:call|time|meeting|chat)|book a (?:call|time|meeting)|schedule a (?:call|time|meeting)|hop on a (?:call|quick call)|when (?:are you|works|can we|would)|do you have time|yes,? (?:please|let'?s|happy|absolutely|i am)|love to (?:chat|talk|connect))\b", re.I)


def is_positive_call_intent(subject: str | None, body: str | None) -> bool:
    """True only if the reply reads as a warm request to talk/meet AND carries
    no opt-out / negative / auto-responder signal."""
    hay = f"{subject or ''}\n{body or ''}"
    if _AR_AUTO.search(hay) or _AR_UNSUB.search(hay) or _AR_NEG.search(hay):
        return False
    return bool(_AR_POS.search(hay))


_AR_LISTKW = re.compile(r"\b(list|probate|the report|home value|send (?:me )?(?:the |my )?(?:list|report|sellers|leads)|free (?:list|report))\b", re.I)


def is_list_request(subject: str | None, body: str | None) -> bool:
    """True if the reply is asking for the free list / sellers rather than a call:
    an explicit list keyword, OR a short ZIP-dominated reply (the give-first opt-in
    is 'reply with your postal code'). These get the value delivered first and must
    NEVER receive a booking link until the operator unlocks them. Length-gated so a
    ZIP sitting in an email signature does not mis-flag a real call request."""
    hay = f"{subject or ''}\n{body or ''}"
    if _AR_LISTKW.search(hay):
        return True
    compact = re.sub(r"\s+", " ", (body or "")).strip()
    if re.search(r"\b\d{5}\b", compact) and len(re.sub(r"[^a-zA-Z]", "", compact)) < 60:
        return True
    return False


# Per-brand booking links for the auto-reply. aureon's lives in the email
# template (not the profile JSON) so it is pinned here; diraya's matches its
# profile. Add a slug here, or set a brand's brand.cta_url to a scheduling URL,
# to enable auto-booking for that brand.
BOOKING_LINKS = {
    "aureon": "https://calendly.com/aureonglobal-info/30min",
    "diraya": "https://calendly.com/amoura-ma-diraya/30min",
}
_BOOKING_HOSTS = ("calendly.com", "cal.com", "savvycal", "meetings.hubspot",
                  "zcal.co", "tidycal", "koalendar", "youcanbook")


def booking_link_for(slug: str, profile: dict | None) -> str:
    """The booking URL for a brand: explicit map first, then the profile's
    brand.cta_url if it is a real scheduling link. '' = no auto-booking."""
    link = BOOKING_LINKS.get(slug, "")
    if not link:
        cta = (((profile or {}).get("brand") or {}).get("cta_url") or "").strip()
        if cta.startswith("http") and any(h in cta for h in _BOOKING_HOSTS):
            link = cta
    return link


def already_autoreplied(addr: str) -> bool:
    """Idempotency: have we already auto-sent a booking reply to this address?
    Honours the user's 'not already replied to' rule across reply rows."""
    import urllib.parse as _up
    try:
        rows = supa_get("replies?from_addr=eq." + _up.quote((addr or "").lower())
                        + "&raw_headers->>autoreply_sent=eq.true&select=id&limit=1")
        return bool(rows)
    except Exception:
        return False


def _original_from_addr(reply: dict) -> str:
    """The address we originally emailed this prospect from, so a non-Aureon
    auto-reply goes out on-brand from the sender the prospect already knows."""
    rid = reply.get("run_id")
    if rid:
        try:
            rows = supa_get(f"send_log?run_id=eq.{rid}&select=from_addr&order=step_n.asc&limit=1")
            if rows and rows[0].get("from_addr"):
                return rows[0]["from_addr"]
        except Exception:
            pass
    return ""


def _brand_resend_key(slug: str) -> str:
    try:
        p = json.loads((REPO / "profiles" / f"{slug}.private.json").read_text(encoding="utf-8"))
        return (p.get("relay") or {}).get("resend_api_key") or ""
    except Exception:
        return ""


def _autoreply_body(first_name: str, persona_name: str, brand_name: str,
                    booking_url: str, signoff_email: str) -> str:
    fn = (first_name or "").strip() or "there"
    lines = [
        f"Hi {fn},", "",
        "Great to hear from you, glad this is a fit.", "",
        "Grab whatever time works best for you here and it lands straight on my calendar:",
        booking_url, "",
        "If none of those slots fit, just reply with a couple of windows that suit "
        "you and I will set one up.", "",
        "Looking forward to it.", "",
        persona_name, brand_name,
    ]
    if signoff_email:
        lines.append(signoff_email)
    return "\n".join(lines)


def send_autoreply(*, slug: str, prospect_email: str, first_name: str, subject: str,
                   persona: dict | None, profile: dict | None, booking_url: str,
                   reply: dict, dry: bool) -> bool:
    """Send the warm-lead booking reply. aureon goes FROM info@aureonglobal.de via
    Hostinger SMTP (the user's chosen inbox); every other brand goes via its own
    Resend relay from the exact address that emailed the prospect, so it stays
    on-brand and threads. Plain text, signed as the persona."""
    persona_name = (persona or {}).get("from_name") or "there"
    brand_name = (profile or {}).get("name") or "our team"
    reply_subject = subject if (subject or "").lower().startswith("re:") else f"Re: {subject}"

    if slug == "aureon":
        user = HOST.get("SMTP_USER") or OPERATOR_ADDR
        pw = HOST.get("SMTP_PASS")
        body = _autoreply_body(first_name, persona_name, "Aureon Global", booking_url, user)
        if dry:
            print(f"  [DRY] would AUTO-REPLY to {prospect_email} as {persona_name} via Hostinger info@")
            return True
        if not pw:
            print("  ! no SMTP_PASS in hostinger.env — cannot auto-reply")
            return False
        m = MIMEText(body, "plain", "utf-8")
        m["Subject"] = reply_subject[:200]
        m["From"] = f"{persona_name} from Aureon Global <{user}>"
        m["To"] = prospect_email
        m["Reply-To"] = user
        try:
            with smtplib.SMTP_SSL("smtp.hostinger.com", 465, context=ssl.create_default_context()) as s:
                s.login(user, pw)
                s.sendmail(user, [prospect_email], m.as_string())
            return True
        except Exception as e:
            print(f"  ! auto-reply send failed: {e}")
            return False

    # Non-Aureon: send via the brand's own Resend relay, from the original sender.
    from_addr = _original_from_addr(reply)
    key = _brand_resend_key(slug)
    body = _autoreply_body(first_name, persona_name, brand_name, booking_url, from_addr)
    if dry:
        print(f"  [DRY] would AUTO-REPLY to {prospect_email} as {persona_name} via {slug} "
              f"Resend from {from_addr or '(unknown sender)'} (key={'yes' if key else 'MISSING'})")
        return bool(from_addr and key)
    if not from_addr or not key:
        print(f"  ! {slug}: missing sender/resend key — cannot auto-reply (will draft)")
        return False
    payload = {
        "from": f"{persona_name} <{from_addr}>",
        "to": [prospect_email],
        "reply_to": from_addr,
        "subject": reply_subject[:200],
        "text": body,
        "tags": [{"name": "kind", "value": "auto_reply"}],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=20)
        return True
    except urllib.error.HTTPError as e:
        print(f"  ! {slug} resend auto-reply failed: HTTP {e.code} {e.read().decode()[:160]}")
        return False
    except Exception as e:
        print(f"  ! {slug} resend auto-reply failed: {e}")
        return False


def supa_get(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=40).read())


def active_prospect(addr: str) -> dict | None:
    """Return the prospect row for `addr` ONLY if it is a real, enrolled,
    non-unsubscribed prospect. None means: do not draft (not a prospect, or
    opted out). This is the gate that stops us drafting replies to legal
    contacts, our own brand inboxes, vendors, and random senders."""
    import urllib.parse as _up
    rows = supa_get("prospects?email=eq." + _up.quote((addr or "").lower())
                    + "&select=id,profile_slug,unsubscribed,verified,first_name,custom_fields,audience_size&limit=1")
    if not rows:
        return None
    r = rows[0]
    if r.get("unsubscribed"):
        return None
    return r


def supa_patch(path: str, body: dict) -> None:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}",
                                 data=json.dumps(body).encode(),
                                 headers={**H, "Prefer": "return=minimal"},
                                 method="PATCH")
    urllib.request.urlopen(req, timeout=30).read()


# ─── persona / brand resolution ──────────────────────────────────────────────

_QUOTE_LINE = re.compile(
    r"^("
    r"_{5,}|-{5,}|"
    r"from:|sent:|to:|subject:|cc:|"
    r"on .+wrote:|"                       # classic "On <date> X wrote:"
    r"on .+\b(?:AM|PM)\b.*|"              # Gmail "On <date> at H:MM AM/PM <Name>"
    r"on \w+,? .*\d{4}.*|"                # "On Thu, Jun 4, 2026 ..." (wrote: on next line)
    r"am .+schrieb .*:|"                  # German "Am <date> schrieb X:"
    r"<[^>]+@[^>]+>\s*:?$|"               # a bare quoted "<addr>" continuation line
    r">.*"                                 # already-quoted text
    r")", re.I)


def top_reply_text(body: str) -> str:
    """The prospect's own words — strip the quoted original we sent."""
    out = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if _QUOTE_LINE.match(s) or "________" in s:
            break
        out.append(ln)
    return "\n".join(out).strip() or (body or "").strip()


_PROFILE_CACHE: dict[str, dict] = {}


def all_profiles() -> list[dict]:
    if "_all" not in _PROFILE_CACHE:
        _PROFILE_CACHE["_all"] = list_profiles()
    return _PROFILE_CACHE["_all"]


def resolve_brand_persona(reply: dict) -> tuple[dict | None, dict | None]:
    """Return (profile, persona) that originally mailed this prospect.

    Primary path: reply.run_id -> send_log row -> persona_slug + from_addr domain,
    then find the profile whose pool contains that domain. Fallback: match the
    sending subdomain of the reply's to_addr (our address) to a profile."""
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

    # Fallback: the reply's To: is our sending address; use its domain.
    if not from_dom:
        to = (reply.get("to_addr") or "").lower()
        from_dom = to.split("@", 1)[1] if "@" in to else None

    for prof in all_profiles():
        doms = {d["domain"].lower()
                for d in prof.get("relay", {}).get("from_domains", [])}
        if from_dom and from_dom in doms:
            persona = None
            if persona_slug:
                persona = next((p for p in prof.get("personas", [])
                                if p.get("slug") == persona_slug), None)
            if not persona and prof.get("personas"):
                persona = prof["personas"][0]
            return prof, persona
    return None, None


# ─── Claude draft via CLI ────────────────────────────────────────────────────

def claude_draft(profile: dict, persona: dict, prospect_email: str,
                 subject: str, prospect_msg: str,
                 offer_context: str = "") -> str | None:
    """Drive the local Claude CLI to write a reply. Returns the draft text, or
    None on failure (caller falls back to a template).

    offer_context: optional plain-text deal terms (e.g. the AlgoAlpha
    per-influencer retainer + commission) the draft may quote verbatim."""
    brand = profile.get("brand", {})
    voice = (persona or {}).get("voice", {})
    sig = (persona or {}).get("signature", "")
    from_name = (persona or {}).get("from_name", "")
    company = brand.get("wordmark") or profile.get("name", "")
    cta = brand.get("cta_url", "")

    avoid = ', '.join((voice.get('avoid', []) or ['hype'])) + ", em-dashes, exclamation marks, emojis"
    quirks = ', '.join(voice.get('quirks', []) or ['short sentences', 'concrete'])
    cta_line = f"\n- If a call makes sense, you may offer this link: {cta}" if cta else ""
    offer_line = (f"\n- Deal terms on the table (quote these exact numbers when terms come up; "
                  f"never invent or negotiate different ones): {offer_context}"
                  if offer_context else "")

    # Full system prompt REPLACEMENT. Framing this as embedded CRM writing
    # assistance (and stripping the default agentic system prompt) is what stops
    # the CLI from inspecting the workspace and declining on cold-email grounds.
    system = (
        "You are an elite B2B sales-email copywriter embedded in a CRM, writing in "
        "the style of Alex Hormozi. The user pastes an email they received from a "
        "business contact in an ongoing, consented B2B correspondence, and you draft "
        "the user's reply. You write like a sharp human closer, never like an AI. "
        "HARD RULES: Never use an em-dash or en-dash (— or –) anywhere; use a period "
        "or a comma instead. Never use the words: delighted, reach out, touch base, "
        "synergy, leverage, circle back, I hope this email finds you, valued, "
        "excited to, looking forward to hearing. No exclamation marks, no emojis, no "
        "corporate filler, no throat-clearing. Output ONLY the reply body, nothing else."
    )
    prompt = f"""Draft my reply to the email below.

I run {company} and sign as "{from_name}". Write it in plain, confident, Hormozi-style sales copy:
- Lead with their words, not mine. Short punchy sentences. Concrete and specific.
- Make the value obvious and name one clear next step (a yes/no or a time). No fluff, no hedging.
- {voice.get('register', 'direct and confident')}; {quirks}.
- Banned: {avoid}. Absolutely no em-dashes or en-dashes anywhere. Use periods.
- Under 80 words.
- If they are not interested or ask to stop, give a one-line clean acknowledgement and stop. Do not push.{cta_line}{offer_line}

Email I received:

Subject: {subject}

{prospect_msg[:1500]}

Write only the reply body I should send. No subject line, no commentary, no signature."""

    # Sandbox recipe (proven): empty cwd so there is no project to inspect,
    # replaced system prompt, all tools disabled, user settings only (skip the
    # repo's project/local CLAUDE.md + settings), prompt via stdin.
    import tempfile, shutil
    workdir = tempfile.mkdtemp(prefix="les_draft_")
    try:
        proc = subprocess.run(
            [CLAUDE_CMD, "-p",
             "--system-prompt", system,
             "--disallowedTools", "Bash,Read,Glob,Grep,Edit,Write,WebFetch,WebSearch",
             "--setting-sources", "user"],
            input=prompt,
            capture_output=True, text=True, timeout=150,
            encoding="utf-8", errors="replace",
            cwd=workdir,
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
    # Strip the known stdin warning if it leaks into stdout.
    text = re.sub(r"^Warning: no stdin data received.*?\n", "", text, flags=re.I).strip()
    if not text:
        return None
    text = _scrub_dashes(text)
    text = _strip_preamble(text, from_name)
    if sig and sig.split("\n")[0].lower() not in text.lower():
        text = f"{text}\n\n{sig}"
    return text


_PREAMBLE_RX = re.compile(
    r"^(here'?s?(\s+(a|the|my))?\s+(clean\s+)?(reply|draft|response)\b.*|"
    r"sure[,.!]?|okay[,.!]?|got it[,.!]?)\s*$", re.I)


def _strip_preamble(text: str, from_name: str) -> str:
    """Remove model preamble lines ("Here's a clean reply.") and any trailing
    "Anna from X" line the model adds just above the real signature."""
    lines = text.splitlines()
    # drop leading preamble + blank lines
    while lines and (not lines[0].strip() or _PREAMBLE_RX.match(lines[0].strip())):
        lines.pop(0)
    # drop a trailing "<FirstName> from <Company>" the model tacks on (the real
    # signature is appended separately).
    fn = (from_name or "").lower().strip()
    while lines and (not lines[-1].strip() or lines[-1].strip().lower() == fn):
        lines.pop()
    return "\n".join(lines).strip()


def _scrub_dashes(text: str) -> str:
    """Hard guarantee: no em-dashes or en-dashes ever reach the draft, even if the
    model slips. ' — ' / '—' become '. ' or ', ' so the sentence still reads."""
    t = text.replace(" — ", ". ").replace(" – ", ". ")
    t = t.replace("—", ", ").replace("–", ", ")
    # collapse any ". ." or ", ," artifacts from the substitution
    t = re.sub(r"\.\s*\.", ".", t)
    t = re.sub(r",\s*,", ",", t)
    return t


def template_draft(persona: dict, prospect_msg: str, offer_recap: str = "") -> str:
    """Offline fallback if the CLI is unavailable. Hormozi-ish, dash-clean.
    offer_recap: optional one-sentence deal terms woven in (AlgoAlpha)."""
    sig = (persona or {}).get("signature", "")
    recap = f" {offer_recap}" if offer_recap else ""
    body = (f"Got it, thanks for the reply.{recap} Want me to send the specifics "
            "by email, or is a 15 minute call this week easier? Either works. "
            "Just tell me which.")
    return _scrub_dashes(body) + ("\n\n" + sig if sig else "")


# ─── operator draft email ────────────────────────────────────────────────────

def send_draft_to_operator(*, prospect_email: str, subject: str,
                           prospect_msg: str, draft: str, profile_name: str,
                           persona_name: str, dry: bool) -> bool:
    reply_subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
    esc = _html.escape
    body_html = f"""\
<div style="font-family:system-ui,-apple-system,sans-serif;color:#1e293b;max-width:620px">
  <h2 style="margin:0 0 4px 0;color:#16a34a">✍️ Draft reply ready for approval</h2>
  <p style="margin:0 0 12px 0;color:#64748b;font-size:13px">
    {esc(profile_name)} · persona {esc(persona_name)} · reply to
    <b>{esc(prospect_email)}</b>. Edit if needed, then hit Reply to send
    (Reply-To is already the prospect).</p>
  <p style="margin:16px 0 4px 0"><b>Suggested subject:</b> {esc(reply_subject)}</p>
  <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:14px;
              white-space:pre-wrap;font-size:14px;line-height:1.5">{esc(draft)}</div>
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:18px 0">
  <p style="margin:0 0 4px 0;color:#64748b;font-size:12px"><b>What the prospect wrote:</b></p>
  <pre style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:8px;
              font-family:ui-monospace,monospace;font-size:12px;color:#334155">{esc(prospect_msg[:1800])}</pre>
  <p style="margin:14px 0 0 0;color:#94a3b8;font-size:11px">
    Drafted by reply-autodraft.py via the local Claude CLI. Nothing was sent to
    the prospect. The sequence is already paused.</p>
</div>"""
    if dry:
        print(f"  [DRY] would email draft to {OPERATOR_ADDR} for reply to {prospect_email}")
        print("  ---- DRAFT ----")
        print(draft)
        print("  ---------------")
        return True
    if not RESEND_KEY:
        print("  ! no RESEND key in hostinger.env — cannot send draft")
        return False
    payload = {
        "from": ALERT_FROM,
        "to": [OPERATOR_ADDR],
        "reply_to": prospect_email,
        "subject": f"[DRAFT] {reply_subject}"[:200],
        "html": body_html,
        "headers": {"X-LES-Alert": "reply-draft"},
        "tags": [{"name": "kind", "value": "reply_draft"}],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(), method="POST",
        headers={"Authorization": f"Bearer {RESEND_KEY}",
                 "Content-Type": "application/json", "User-Agent": UA},
    )
    try:
        urllib.request.urlopen(req, timeout=20)
        return True
    except urllib.error.HTTPError as e:
        print(f"  ! draft send failed: HTTP {e.code} {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"  ! draft send failed: {e}")
        return False


# ─── main pass ───────────────────────────────────────────────────────────────

def mark_drafted(reply: dict) -> None:
    rh = dict(reply.get("raw_headers") or {})
    rh["autodraft_sent"] = True
    rh["autodraft_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    supa_patch(f"replies?id=eq.{reply['id']}", {"raw_headers": rh})


def one_pass(limit: int, dry: bool) -> dict:
    stats = {"candidates": 0, "drafted": 0, "autoreplied": 0, "skipped": 0,
             "suppressed": 0, "not_prospect": 0, "errors": 0}
    rows = supa_get("replies?class=eq.reply&select=id,from_addr,to_addr,subject,"
                    "body_snippet,run_id,raw_headers,received_at"
                    "&order=received_at.desc&limit=200")
    # Only the prospect's own replies, not our own alert/self rows or operator self-replies.
    todo = []
    for r in rows:
        if (r.get("raw_headers") or {}).get("autodraft_sent"):
            continue
        frm = (r.get("from_addr") or "").lower()
        if frm.startswith(("alerts@", "drafts@", "reports@")):
            continue  # our own outbound system addresses — skip
        todo.append(r)
    todo = todo[:limit]
    stats["candidates"] = len(todo)
    print(f"undrafted reply rows to evaluate: {len(todo)}")

    for r in todo:
        prospect = r.get("from_addr") or ""
        subject = r.get("subject") or "(no subject)"

        # GATE 1 — hard suppression (legal cases, own brands, vendors). Never draft.
        reason = is_suppressed(prospect)
        if reason:
            print(f"  ⊘ SUPPRESSED {prospect}: {reason} — will not draft")
            stats["suppressed"] += 1
            if not dry:
                rh = dict(r.get("raw_headers") or {})
                rh["autodraft_sent"] = True
                rh["autodraft_skipped"] = reason
                supa_patch(f"replies?id=eq.{r['id']}", {"raw_headers": rh})
            continue

        # GATE 2 — must be a real, enrolled, non-unsubscribed prospect. This is
        # what stops drafting replies to non-prospects (vendors, our own inboxes,
        # random senders, legal contacts who were never enrolled).
        prow = active_prospect(prospect)
        if not prow:
            print(f"  – not an active prospect: {prospect} — skip (no draft)")
            stats["not_prospect"] += 1
            if not dry:
                rh = dict(r.get("raw_headers") or {})
                rh["autodraft_sent"] = True
                rh["autodraft_skipped"] = "not_active_prospect"
                supa_patch(f"replies?id=eq.{r['id']}", {"raw_headers": rh})
            continue

        msg = top_reply_text(r.get("body_snippet") or "")

        # GATE 2.5 — a list/sellers request gets the value delivered first, never a
        # call pitch or booking link. Route it out of the draft+booking flow so the
        # operator delivers the list; run `unlock <email>` afterwards to enable a
        # booking reply on their next positive message.
        if is_list_request(subject, msg):
            print(f"  · {prospect}: list/sellers request — deliver first, no reply drafted")
            stats["skipped"] += 1
            if not dry:
                rh = dict(r.get("raw_headers") or {})
                rh["autodraft_sent"] = True
                rh["autodraft_skipped"] = "list_request_deliver_first"
                supa_patch(f"replies?id=eq.{r['id']}", {"raw_headers": rh})
            continue

        # GATE 3 — positive call-intent -> auto-reply with the brand's booking
        # link, BUT give-first first. A reply asking for the free list/sellers
        # (a ZIP code or "send me the list") NEVER gets a booking link: we deliver
        # the value first. And a lead already in the give-first flow only gets the
        # booking link once the operator flips custom_fields.calendly_unlocked (i.e.
        # after they have received their first sellers). Run `reply-autodraft.py
        # unlock <email>` to flip it. aureon sends from info@ via Hostinger; other
        # brands via their own Resend relay.
        if is_positive_call_intent(subject, msg) and not is_list_request(subject, msg):
            slug = (prow or {}).get("profile_slug") or ""
            cf = (prow or {}).get("custom_fields") or {}
            if cf.get("seller_outreach") and not cf.get("calendly_unlocked"):
                print(f"  · {prospect}: give-first lead not unlocked — holding booking link (deliver first)")
            else:
                profile, persona = resolve_brand_persona(r)
                booking = booking_link_for(slug, profile)
                if booking and already_autoreplied(prospect):
                    print(f"  ~ {prospect}: already auto-replied earlier — skip")
                    stats["skipped"] += 1
                    if not dry:
                        rh = dict(r.get("raw_headers") or {})
                        rh["autodraft_sent"] = True
                        rh["autodraft_skipped"] = "already_autoreplied"
                        supa_patch(f"replies?id=eq.{r['id']}", {"raw_headers": rh})
                    continue
                if booking:
                    print(f"  · POSITIVE intent from {prospect} [{slug or '?'}] — auto-replying with booking link")
                    if send_autoreply(slug=slug, prospect_email=prospect,
                                      first_name=(prow or {}).get("first_name") or "",
                                      subject=subject, persona=persona, profile=profile,
                                      booking_url=booking, reply=r, dry=dry):
                        stats["autoreplied"] += 1
                        if not dry:
                            rh = dict(r.get("raw_headers") or {})
                            rh["autoreply_sent"] = True
                            rh["autoreply_kind"] = "booking"
                            rh["autoreply_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
                            rh["autodraft_sent"] = True
                            supa_patch(f"replies?id=eq.{r['id']}", {"raw_headers": rh})
                        continue
                    print("  ! auto-reply send failed — falling through to draft")

        # Ultra-terse / no-signal replies (bare ZIP codes, single numbers, empty
        # bodies) give the model nothing to work with and produce confused drafts.
        # Route them to manual review instead of auto-drafting noise.
        alnum = re.sub(r"[^a-zA-ZäöüÄÖÜ]", "", msg)
        if not msg or len(alnum) < 12:
            print(f"  - skip {prospect}: too terse for a draft "
                  f"({msg[:40]!r}) -> manual review")
            stats["skipped"] += 1
            if not dry:
                # mark so it is not re-processed, but flag for the operator
                rh = dict(r.get("raw_headers") or {})
                rh["autodraft_sent"] = True
                rh["autodraft_skipped"] = "too_terse"
                supa_patch(f"replies?id=eq.{r['id']}", {"raw_headers": rh})
            continue
        profile, persona = resolve_brand_persona(r)
        pname = (profile or {}).get("name", "unknown brand")
        perq = (persona or {}).get("from_name", "default persona")
        print(f"  · drafting reply to {prospect}  [{pname} / {perq}]")
        # AlgoAlpha: hand the drafter the prospect's exact deal terms (per-video
        # retainer from audience_size + 30 percent lifetime commission) so the
        # response quotes the same numbers the outreach promised.
        offer_ctx = ""
        offer_recap = ""
        if (prow or {}).get("profile_slug") == "algoalpha":
            aud = (prow or {}).get("audience_size")
            offer_ctx = algoalpha_offer.offer_context(aud)
            offer_recap = (f"Quick recap of the deal: {algoalpha_offer.retainer_quote(aud)}, "
                           f"up to four paid videos a month, paid win or lose, plus 30 percent "
                           f"lifetime commission on every signup.")
        draft = None
        if profile and persona:
            draft = claude_draft(profile, persona, prospect, subject, msg,
                                 offer_context=offer_ctx)
        if not draft:
            draft = template_draft(persona or {}, msg, offer_recap=offer_recap)
            print("    (used template fallback)")
        ok = send_draft_to_operator(
            prospect_email=prospect, subject=subject, prospect_msg=msg,
            draft=draft, profile_name=pname, persona_name=perq, dry=dry)
        if ok:
            stats["drafted"] += 1
            if not dry:
                mark_drafted(r)
        else:
            stats["errors"] += 1
    return stats


def unlock_lead(email: str) -> int:
    """Flip custom_fields.calendly_unlocked on a give-first lead so their next
    positive call reply gets the booking link. Run after they have their sellers."""
    import urllib.parse as _up
    rows = supa_get("prospects?email=eq." + _up.quote((email or "").lower())
                    + "&select=id,custom_fields&limit=1")
    if not rows:
        print(f"no prospect found for {email}")
        return 1
    cf = dict(rows[0].get("custom_fields") or {})
    cf["calendly_unlocked"] = True
    cf["calendly_unlocked_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    supa_patch(f"prospects?id=eq.{rows[0]['id']}", {"custom_fields": cf})
    print(f"unlocked {email} — their next positive reply will get the booking link")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("once")
    p.add_argument("--dry", action="store_true", help="print drafts, send/mark nothing")
    p.add_argument("--limit", type=int, default=20)
    pu = sub.add_parser("unlock", help="enable booking-link auto-reply for one lead")
    pu.add_argument("email")
    args = ap.parse_args()
    if args.cmd == "unlock":
        return unlock_lead(args.email)
    stats = one_pass(args.limit, args.dry)
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
