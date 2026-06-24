"""meeting-followup.py — post-Calendly-meeting outcome capture + follow-up.

Built 2026-06-12 at user request. Closes the loop after a Calendly meeting:

  scan    Read Calendly "New Event" emails from info@'s inbox (IMAP), parse the
          invitee name + email + meeting datetime + duration, resolve which
          client/profile the invitee belongs to, and upsert into the local
          meeting store (out/meetings.json). Deduped by (email, meeting_at).

  prompt  For each meeting whose END time has passed and whose outcome is still
          unset, pop a Windows GUI dialog asking what occurred (no-show /
          showed-interested / showed-not-fit / rescheduled) + a free-text notes
          box. On submit it (a) emails a note to the operator, and (b) DRAFTS the
          appropriate follow-up and queues it to the operator for one-click
          approval (never auto-sends to the prospect). Outcome branches:
            no-show      -> "sorry we missed each other, rebook" + value
            interested   -> recap + next-step / close
            not-fit      -> polite close, door left open
            rescheduled  -> timed nudge to re-engage at the date the operator gives

Local store, not a DB table: meeting outcomes are operator-local and we avoid a
schema change (see SUPABASE_RLS deferral). out/meetings.json is the source of truth.

Usage:
    py sequences/meeting-followup.py scan            # parse inbox -> store
    py sequences/meeting-followup.py prompt           # GUI pop-up for due meetings
    py sequences/meeting-followup.py prompt --dry      # show what would pop, no GUI/send
    py sequences/meeting-followup.py run               # scan then prompt (the scheduled entry)
    py sequences/meeting-followup.py list              # print the store

Scheduled as LES-meeting-followup (every ~30 min). The GUI only appears when a
meeting is actually awaiting an outcome, so it is silent the rest of the time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email
import email.policy
import email.utils
import imaplib
import json
import re
import smtplib
import ssl
import subprocess
import sys
import urllib.request
import urllib.error
import urllib.parse
from email.mime.text import MIMEText
from email.utils import parseaddr
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
STORE = REPO / "out" / "meetings.json"
_os = __import__("os")
_CLAUDE_EXE = r"D:\npm-global\node_modules\@anthropic-ai\claude-code\bin\claude.exe"
CLAUDE_CMD = _os.environ.get("CLAUDE_CLI") or (_CLAUDE_EXE if _os.path.exists(_CLAUDE_EXE) else r"D:\npm-global\claude.cmd")
OPERATOR_ADDR = "info@aureonglobal.de"
UA = "curl/8.0"

# Calendly subject: "New Event: <Name> - <HH:MM> <Day, DD Mon YYYY> - <duration> Meeting"
SUBJ_RX = re.compile(
    r"New Event:\s*(?P<name>.+?)\s*-\s*(?P<time>\d{1,2}:\d{2})\s+"
    r"(?P<dow>\w{3}),\s*(?P<day>\d{1,2})\s+(?P<mon>\w{3})\s+(?P<year>\d{4})\s*-\s*"
    r"(?P<dur>\d+)\s*Minute",
    re.I,
)
_MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
EMAIL_RX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_OWN_EMAIL_BITS = ("calendly", "aureonglobal", "example.com", "sentry", "no-reply", "noreply")

# Zoom "participant joined" subject (the BACKSTOP signal). When Calendly's own
# "New Event" notification never reaches info@ (lapsed plan / notifications off),
# this is the only email that proves a meeting actually happened. Calendly's
# Zoom integration auto-names the meeting topic "<Invitee>: <duration> Minute
# Meeting", so the topic carries the invitee name + duration. German and English
# both seen on this account:
#   DE: "<Name> ist dem Meeting beigetreten - <Topic>"
#   EN: "<Name> has joined ... - <Topic>"  /  "<Name> joined ... - <Topic>"
ZOOM_SUBJ_RX = re.compile(
    r"(?P<joiner>.+?)\s+(?:ist dem Meeting beigetreten|has joined|joined)\b.*?-\s*"
    r"(?P<topic>.+?)\s*:\s*(?P<dur>\d+)\s*Minute",
    re.I,
)

# Direct Google Calendar / Outlook invite (the THIRD meeting channel). When a
# prospect schedules the call on THEIR side, they send info@ an .ics invite
# (METHOD:REQUEST). It is neither a Calendly booking nor a Zoom-joined ping, so
# the other two scans miss it. The subject is "Invitation: <title> @ <when>".
# We parse the .ics for the real start/end/organizer rather than the subject.
GCAL_SUBJ_HINT_RX = re.compile(r"\b(?:Invitation|Einladung|Updated invitation):", re.I)


# ─── env / store ─────────────────────────────────────────────────────────────

def load_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


HOST = load_env(REPO / "sequences" / "hostinger.env")
SUPA = load_env(REPO / "sequences" / "supabase.env")
SUPA_URL = SUPA.get("SUPABASE_URL", "").rstrip("/")
SUPA_KEY = SUPA.get("SUPABASE_ANON_KEY", "")
SUPA_H = {"apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}"}
RESEND_KEY = (HOST.get("RESEND_NEW_ACCOUNT_API_KEY")
              or HOST.get("RESEND_FULL_ACCESS_API_KEY")
              or HOST.get("RESEND_API_KEY", ""))


def load_store() -> dict:
    if STORE.exists():
        try:
            return json.loads(STORE.read_text(encoding="utf-8"))
        except Exception:
            return {"meetings": []}
    return {"meetings": []}


def save_store(store: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def supa_get(path: str) -> list:
    try:
        req = urllib.request.Request(f"{SUPA_URL}/rest/v1/{path}", headers=SUPA_H)
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception:
        return []


# ─── scan: Calendly emails -> store ──────────────────────────────────────────

def _body_text(msg) -> str:
    html = ""
    plain = ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        ct = part.get_content_type()
        if ct == "text/plain" and not plain:
            try: plain = part.get_content()
            except Exception: pass
        elif ct == "text/html" and not html:
            try: html = part.get_content()
            except Exception: pass
    if plain:
        return plain
    return re.sub(r"<[^>]+>", " ", html)


def _invitee_email(body: str) -> str | None:
    for e in EMAIL_RX.findall(body):
        el = e.lower()
        if not any(b in el for b in _OWN_EMAIL_BITS):
            return el
    return None


def _parse_meeting_dt(m: re.Match) -> str | None:
    try:
        hh, mm = m.group("time").split(":")
        mon = _MONTHS.get(m.group("mon").capitalize())
        if not mon:
            return None
        d = dt.datetime(int(m.group("year")), mon, int(m.group("day")),
                        int(hh), int(mm))
        return d.isoformat()
    except Exception:
        return None


def resolve_profile(email_addr: str) -> str | None:
    """Which client does this invitee belong to? Match the prospects table."""
    if not email_addr:
        return None
    rows = supa_get(f"prospects?email=eq.{urllib.parse.quote(email_addr)}&select=profile_slug&limit=1")
    return rows[0]["profile_slug"] if rows else None


def scan(verbose: bool = True) -> int:
    user = HOST.get("SMTP_USER", OPERATOR_ADDR)
    pw = HOST.get("SMTP_PASS", "")
    if not pw:
        print("missing SMTP_PASS in hostinger.env"); return 0
    store = load_store()
    known = {(mt["invitee_email"], mt["meeting_at"]) for mt in store["meetings"]}
    added = 0
    since = (dt.datetime.utcnow() - dt.timedelta(days=30)).strftime("%d-%b-%Y")
    imap = imaplib.IMAP4_SSL("imap.hostinger.com", 993)
    try:
        imap.login(user, pw)
        for folder in ("INBOX", "INBOX.Junk"):
            if imap.select(folder, readonly=True)[0] != "OK":
                continue
            typ, data = imap.search(
                None, f'(FROM "notifications@calendly.com" SUBJECT "New Event" SINCE {since})')
            nums = data[0].split() if data and data[0] else []
            for num in nums:
                typ, md = imap.fetch(num, "(RFC822)")
                if typ != "OK" or not md or not md[0]:
                    continue
                msg = email.message_from_bytes(md[0][1], policy=email.policy.default)
                subj = msg.get("Subject", "") or ""
                m = SUBJ_RX.search(subj)
                if not m:
                    continue
                meeting_at = _parse_meeting_dt(m)
                if not meeting_at:
                    continue
                body = _body_text(msg)
                inv_email = _invitee_email(body)
                if not inv_email:
                    continue
                if (inv_email, meeting_at) in known:
                    continue
                rec = {
                    "invitee_name": m.group("name").strip(),
                    "invitee_email": inv_email,
                    "meeting_at": meeting_at,
                    "duration_min": int(m.group("dur")),
                    "profile_slug": resolve_profile(inv_email),
                    "booked_subject": subj,
                    "outcome": None,
                    "notes": None,
                    "reengage_at": None,
                    "handled_at": None,
                    "scanned_at": dt.datetime.utcnow().isoformat() + "Z",
                }
                store["meetings"].append(rec)
                known.add((inv_email, meeting_at))
                added += 1
                if verbose:
                    print(f"  + {rec['invitee_name']} <{inv_email}> "
                          f"{meeting_at} [{rec['profile_slug'] or 'unmatched'}]")
                # Double-notify: instant confirmation on top of Calendly's own email.
                _send_booking_alert(rec, dry=False)
    finally:
        try: imap.logout()
        except Exception: pass
    save_store(store)
    if verbose:
        print(f"scan: +{added} new meetings ({len(store['meetings'])} total in store)")
    return added


# ─── scan_zoom: Zoom "joined" emails -> store (the blindspot backstop) ────────

def _norm_name(name: str) -> str:
    """Loose key for matching a Zoom topic name to a Calendly invitee name.
    Calendly uses the booking name ('Andrew Barr'); Zoom may show a display
    name ('Crypto Rapper') or the topic ('The Crypto Rapper'). Compare on a
    lowercased, alphanumeric-only form so small differences don't double-count."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _send_blindspot_alert(mt: dict, dry: bool) -> None:
    """A meeting happened that Calendly never told the operator about. Fire an
    immediate heads-up to info@ so this is never silent again. Mirrors the
    Resend alert recipe in imap-poll.send_reply_alert (sender, UA, quota note)."""
    when = mt["meeting_at"].replace("T", " ")
    body = (
        f"A meeting was detected from a Zoom 'joined' notification, but NO Calendly\n"
        f"'New Event' email ever arrived at info@ for it. You were not invited / notified\n"
        f"the normal way. This is the exact failure that hid the crypto-rapper meeting.\n\n"
        f"Invitee/topic : {mt['invitee_name']}\n"
        f"Detected at   : {when} (when they joined the Zoom call)\n"
        f"Client        : {mt.get('profile_slug') or 'unmatched'}\n"
        f"Source        : Zoom participant-joined email (Calendly notification missing)\n\n"
        f"What to check: Calendly > Account > Notifications (host email ON, to info@) and\n"
        f"that the Calendly plan/trial is active. The booking itself worked; only the\n"
        f"notification to you failed.\n"
    )
    ok = _resend_send(
        OPERATOR_ADDR, f"[Meeting MISSED-INVITE] {mt['invitee_name']}",
        body, "Aureon Meeting Bot", "drafts@hi.aureonglobal.de", dry)
    if not dry:
        print(f"  ! BLINDSPOT alert {'sent' if ok else 'FAILED'} to {OPERATOR_ADDR} "
              f"for {mt['invitee_name']}")


def _send_booking_alert(mt: dict, dry: bool) -> None:
    """Double-notify: fire an instant confirmation to info@ the moment a Calendly
    booking is ingested, ON TOP of Calendly's own 'New Event' email. The operator
    asked for redundant notifications so no booking is ever missed again. Mirrors
    the Resend alert recipe in imap-poll.send_reply_alert."""
    when = mt["meeting_at"].replace("T", " ")
    body = (
        f"NEW BOOKING confirmed. (This is the stack's own alert, sent in addition\n"
        f"to Calendly's 'New Event' email, so you always get a redundant heads-up.)\n\n"
        f"Invitee : {mt['invitee_name']} <{mt['invitee_email']}>\n"
        f"When    : {when} ({mt.get('duration_min', 30)} min)\n"
        f"Client  : {mt.get('profile_slug') or 'unmatched'}\n"
        f"Source  : Calendly 'New Event' email\n\n"
        f"The outcome dialog will pop after the meeting ends to capture how it went.\n"
    )
    ok = _resend_send(
        OPERATOR_ADDR, f"[New booking] {mt['invitee_name']} - {when}",
        body, "Aureon Meeting Bot", "drafts@hi.aureonglobal.de", dry)
    if not dry:
        print(f"  > booking alert {'sent' if ok else 'FAILED'} to {OPERATOR_ADDR} "
              f"for {mt['invitee_name']}")


def scan_zoom(verbose: bool = True) -> int:
    """Backstop scan: catch Zoom 'X joined your meeting' emails. The Zoom email
    fires at join time, so we treat its Date as the meeting time. Any Zoom-joined
    meeting that does NOT already match a Calendly booking in the store (same
    person, same day) is a blindspot: the meeting happened with no Calendly
    notification -> record it AND alert the operator immediately."""
    user = HOST.get("SMTP_USER", OPERATOR_ADDR)
    pw = HOST.get("SMTP_PASS", "")
    if not pw:
        print("missing SMTP_PASS in hostinger.env"); return 0
    store = load_store()
    # Existing meetings indexed by (normalized name, date) so a Calendly booking
    # already captured does NOT get re-added from its Zoom-joined twin.
    seen_day = {(_norm_name(mt["invitee_name"]), mt["meeting_at"][:10])
                for mt in store["meetings"]}
    # Avoid duplicate Zoom records too.
    known_zoom = {(mt["invitee_email"], mt["meeting_at"])
                  for mt in store["meetings"] if mt.get("source") == "zoom"}
    added = 0
    since = (dt.datetime.utcnow() - dt.timedelta(days=30)).strftime("%d-%b-%Y")
    imap = imaplib.IMAP4_SSL("imap.hostinger.com", 993)
    try:
        imap.login(user, pw)
        for folder in ("INBOX", "INBOX.Junk"):
            if imap.select(folder, readonly=True)[0] != "OK":
                continue
            typ, data = imap.search(
                None, f'(FROM "no-reply@zoom.us" SINCE {since})')
            nums = data[0].split() if data and data[0] else []
            for num in nums:
                typ, md = imap.fetch(num, "(RFC822)")
                if typ != "OK" or not md or not md[0]:
                    continue
                msg = email.message_from_bytes(md[0][1], policy=email.policy.default)
                subj = msg.get("Subject", "") or ""
                m = ZOOM_SUBJ_RX.search(subj)
                if not m:
                    continue  # not a "joined" email (verification code, app, etc.)
                # Meeting time = when the Zoom email was sent (= join time).
                try:
                    msg_dt = email.utils.parsedate_to_datetime(msg.get("Date"))
                    meeting_at = msg_dt.replace(tzinfo=None).isoformat(timespec="seconds")
                except Exception:
                    continue
                # The topic is the real meeting label ("The Crypto Rapper"); the
                # joiner field is the Zoom display name. Prefer the topic name.
                inv_name = m.group("topic").strip() or m.group("joiner").strip()
                day = meeting_at[:10]
                nkey = _norm_name(inv_name)
                # Already covered by a Calendly booking on the same day? skip silently.
                if (nkey, day) in seen_day:
                    continue
                # A joiner that is the operator themselves on a known day is the
                # operator joining their own booked call; the Calendly twin check
                # above handles real bookings, so anything left here is a blindspot.
                if (inv_name, meeting_at) in known_zoom:
                    continue
                rec = {
                    "invitee_name": inv_name,
                    "invitee_email": "(unknown - from Zoom)",
                    "meeting_at": meeting_at,
                    "duration_min": int(m.group("dur")),
                    "profile_slug": None,
                    "booked_subject": subj,
                    "outcome": None,
                    "notes": None,
                    "reengage_at": None,
                    "source": "zoom",
                    "scanned_at": dt.datetime.utcnow().isoformat() + "Z",
                }
                store["meetings"].append(rec)
                seen_day.add((nkey, day))
                known_zoom.add((inv_name, meeting_at))
                added += 1
                if verbose:
                    print(f"  + [ZOOM/blindspot] {inv_name} {meeting_at} "
                          f"(no Calendly notification found)")
                _send_blindspot_alert(rec, dry=False)
    finally:
        try: imap.logout()
        except Exception: pass
    save_store(store)
    if verbose:
        print(f"scan_zoom: +{added} blindspot meeting(s) "
              f"({len(store['meetings'])} total in store)")
    return added


# ─── scan_gcal: direct calendar invites (.ics REQUEST) -> store ──────────────

def _ics_unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: a leading space/tab continues the previous line."""
    out = []
    for raw in text.splitlines():
        if raw[:1] in (" ", "\t") and out:
            out[-1] += raw[1:]
        else:
            out.append(raw)
    return out


def _ics_field(lines: list[str], name: str) -> str | None:
    """Return the value of an ICS property (matches 'NAME' or 'NAME;params:')."""
    for ln in lines:
        if ln.upper().startswith(name.upper()):
            head, _, val = ln.partition(":")
            # Confirm it's the property, not a longer name (e.g. DTSTART vs DTSTAMP).
            key = head.split(";", 1)[0].upper()
            if key == name.upper():
                return val.strip()
    return None


def _ics_event_time(lines: list[str], prop: str) -> str | None:
    """Pull the *event* DTSTART/DTEND (the one with TZID or a Z time), not the
    VTIMEZONE rule lines. Returns naive ISO 'YYYY-MM-DDTHH:MM:SS' (invite local)."""
    cand = None
    for ln in lines:
        if not ln.upper().startswith(prop.upper()):
            continue
        head, _, val = ln.partition(":")
        val = val.strip()
        # VTIMEZONE rule DTSTARTs are bare 'YYYYMMDDT020000' with no TZID and
        # often year 1970/2038. The real event time carries TZID= or ends Z.
        if "TZID=" in head.upper() or val.endswith("Z"):
            cand = val
            break
    if not cand:
        return None
    m = re.match(r"(\d{4})(\d{2})(\d{2})T(\d{2})(\d{2})(\d{2})", cand)
    if not m:
        return None
    y, mo, d, hh, mm, ss = m.groups()
    return f"{y}-{mo}-{d}T{hh}:{mm}:{ss}"


def _ics_dtstart(lines: list[str]) -> str | None:
    return _ics_event_time(lines, "DTSTART")


def _ics_join_info(lines: list[str]) -> dict:
    """Extract everything needed to JOIN the meeting from the .ics, so the alert
    is a self-contained backup: the video link, phone dial-in + PIN, and the
    reschedule/cancel links. Google puts the clean video URL in
    X-GOOGLE-CONFERENCE and the dial-in inside the (escaped) DESCRIPTION."""
    info = {"video": None, "phone": None, "more_phones": None,
            "reschedule": None, "cancel": None}
    # Clean machine-readable video link (Google Meet / Zoom / Teams).
    for ln in lines:
        u = ln.upper()
        if u.startswith("X-GOOGLE-CONFERENCE") or u.startswith("X-MICROSOFT-SKYPETEAMSMEETINGURL"):
            info["video"] = ln.partition(":")[2].strip()
            break
    # DESCRIPTION holds the dial-in + reschedule/cancel. ICS escapes \n \, \;.
    desc_raw = _ics_field(lines, "DESCRIPTION") or ""
    desc = (desc_raw.replace("\\n", "\n").replace("\\,", ",")
            .replace("\\;", ";").replace("\\\\", "\\"))
    if not info["video"]:
        m = re.search(r"https://(?:meet\.google\.com|[\w.]*zoom\.us|teams\.microsoft\.com)\S+", desc)
        if m:
            info["video"] = m.group(0).rstrip(".")
    m = re.search(r"Or dial:\s*(.+?PIN:\s*[\d#]+)", desc)
    if m:
        info["phone"] = m.group(1).strip()
    m = re.search(r"More phone numbers:\s*(https?://\S+)", desc)
    if m:
        info["more_phones"] = m.group(1).strip()
    m = re.search(r"Reschedule:\s*(https?://\S+)", desc)
    if m:
        info["reschedule"] = m.group(1).strip()
    m = re.search(r"Cancel:\s*(https?://\S+)", desc)
    if m:
        info["cancel"] = m.group(1).strip()
    return info


def _local_when(meeting_at: str, tzid: str | None) -> str:
    """Render the meeting time in BOTH the invite's timezone and the operator's
    local timezone (Pristina, GMT+2) so there is no mental math at join time."""
    base = meeting_at.replace("T", " ")
    if not tzid:
        return base
    try:
        from zoneinfo import ZoneInfo
        src = dt.datetime.fromisoformat(meeting_at).replace(tzinfo=ZoneInfo(tzid))
        local = src.astimezone(ZoneInfo("Europe/Belgrade"))  # GMT+2, == Pristina
        return (f"{base} ({tzid})  =  "
                f"{local.strftime('%Y-%m-%d %H:%M')} (your time, Pristina)")
    except Exception:
        return f"{base} ({tzid})"


def _send_gcal_alert(mt: dict, dry: bool) -> None:
    """Double-notify for a direct calendar invite. Fires the moment we see the
    .ics REQUEST in info@, so a prospect-scheduled meeting (Google Calendar /
    Outlook) is never silent. Carries ALL join info so the alert works as a
    standalone backup. Same Resend recipe as the other alerts."""
    when = _local_when(mt["meeting_at"], mt.get("tz"))
    j = mt.get("join") or {}
    join_block = "HOW TO JOIN (this email is your backup, save it):\n"
    join_block += f"  Video link : {j.get('video') or mt.get('location') or '(see original invite)'}\n"
    if j.get("phone"):
        join_block += f"  Phone dial : {j['phone']}\n"
    if j.get("more_phones"):
        join_block += f"  More dial-in numbers: {j['more_phones']}\n"
    extra = ""
    if j.get("reschedule"):
        extra += f"  Reschedule : {j['reschedule']}\n"
    if j.get("cancel"):
        extra += f"  Cancel     : {j['cancel']}\n"
    body = (
        f"MEETING INVITE received (direct calendar invite, NOT Calendly/Zoom).\n"
        f"A prospect scheduled a call and sent info@ a calendar invite. Here is your\n"
        f"redundant heads-up WITH the full join details so this email alone is enough.\n\n"
        f"Title    : {mt['invitee_name']}\n"
        f"When     : {when}\n"
        f"Organizer: {mt['invitee_email']}\n"
        f"Client   : {mt.get('profile_slug') or 'unmatched'}\n\n"
        f"{join_block}"
        + (f"\n{extra}" if extra else "")
        + f"\nACTION: open the original invite email and RSVP (Accept) so it also lands on\n"
        f"your calendar. The stack cannot RSVP for you on Google Calendar.\n"
    )
    ok = _resend_send(
        OPERATOR_ADDR, f"[Meeting invite] {mt['invitee_name']} - {mt['meeting_at'][:10]}",
        body, "Aureon Meeting Bot", "drafts@hi.aureonglobal.de", dry)
    if not dry:
        print(f"  > gcal-invite alert {'sent' if ok else 'FAILED'} to {OPERATOR_ADDR} "
              f"for {mt['invitee_name']}")


def scan_gcal(verbose: bool = True) -> int:
    """Catch direct calendar invites: emails carrying a text/calendar part with
    METHOD:REQUEST (Google Calendar, Outlook). Parses the .ics for the real
    start time + organizer + location, logs it (source: gcal-invite), and fires
    the double-notify. Dedups by ICS UID (stable across update resends) and by
    (organizer, start). Ignores invites from our own / Calendly / Zoom senders
    so we only capture genuine prospect-scheduled meetings."""
    user = HOST.get("SMTP_USER", OPERATOR_ADDR)
    pw = HOST.get("SMTP_PASS", "")
    if not pw:
        print("missing SMTP_PASS in hostinger.env"); return 0
    store = load_store()
    known_uid = {mt.get("ics_uid") for mt in store["meetings"] if mt.get("ics_uid")}
    known_org = {(mt.get("invitee_email"), mt["meeting_at"])
                 for mt in store["meetings"]}
    added = 0
    since = (dt.datetime.utcnow() - dt.timedelta(days=30)).strftime("%d-%b-%Y")
    imap = imaplib.IMAP4_SSL("imap.hostinger.com", 993)
    try:
        imap.login(user, pw)
        for folder in ("INBOX", "INBOX.Junk"):
            if imap.select(folder, readonly=True)[0] != "OK":
                continue
            # Calendar invites set Content-Type text/calendar; search by subject
            # hint (server-side BODY search on .ics is unreliable across servers).
            typ, data = imap.search(None, f'(SUBJECT "Invitation" SINCE {since})')
            nums = data[0].split() if data and data[0] else []
            for num in nums:
                typ, md = imap.fetch(num, "(RFC822)")
                if typ != "OK" or not md or not md[0]:
                    continue
                msg = email.message_from_bytes(md[0][1], policy=email.policy.default)
                from_addr = parseaddr(msg.get("From", ""))[1].lower()
                if any(b in from_addr for b in _OWN_EMAIL_BITS) or "zoom.us" in from_addr:
                    continue  # our own / calendly / zoom, not a prospect invite
                # Find the text/calendar part.
                ics = None
                for part in (msg.walk() if msg.is_multipart() else [msg]):
                    if part.get_content_type() == "text/calendar" or \
                       (part.get_filename() or "").lower().endswith(".ics"):
                        try:
                            ics = part.get_content()
                        except Exception:
                            payload = part.get_payload(decode=True)
                            ics = payload.decode("utf-8", "replace") if payload else None
                        if isinstance(ics, bytes):
                            ics = ics.decode("utf-8", "replace")
                        break
                if not ics:
                    continue
                lines = _ics_unfold(ics)
                method = (_ics_field(lines, "METHOD") or "").upper()
                if method and method != "REQUEST":
                    continue  # cancellations / replies, not a new booking
                meeting_at = _ics_dtstart(lines)
                if not meeting_at:
                    continue
                uid = _ics_field(lines, "UID")
                summary = _ics_field(lines, "SUMMARY") or msg.get("Subject", "Meeting")
                organizer = _ics_field(lines, "ORGANIZER") or from_addr
                org_email = organizer.split("mailto:")[-1].strip().lower() \
                    if "mailto:" in organizer.lower() else from_addr
                location = _ics_field(lines, "LOCATION")
                tzid = None
                for ln in lines:
                    if ln.upper().startswith("DTSTART") and "TZID=" in ln.upper():
                        tzid = ln.split("TZID=", 1)[1].split(":", 1)[0]
                        break
                if uid and uid in known_uid:
                    continue
                if (org_email, meeting_at) in known_org:
                    continue
                # Duration from DTEND if present.
                dur = 30
                dtend = _ics_event_time(lines, "DTEND")
                try:
                    if dtend:
                        a = dt.datetime.fromisoformat(meeting_at)
                        b = dt.datetime.fromisoformat(dtend)
                        dur = max(1, int((b - a).total_seconds() // 60))
                except Exception:
                    pass
                join = _ics_join_info(lines)
                rec = {
                    "invitee_name": summary.strip(),
                    "invitee_email": org_email,
                    "meeting_at": meeting_at,
                    "duration_min": dur,
                    "profile_slug": resolve_profile(org_email),
                    "booked_subject": msg.get("Subject", ""),
                    "location": re.split(r"\\?;", location or "")[0].strip() or None,
                    "tz": tzid,
                    "join": join,
                    "ics_uid": uid,
                    "outcome": None,
                    "notes": None,
                    "reengage_at": None,
                    "source": "gcal-invite",
                    "scanned_at": dt.datetime.utcnow().isoformat() + "Z",
                }
                store["meetings"].append(rec)
                if uid:
                    known_uid.add(uid)
                known_org.add((org_email, meeting_at))
                added += 1
                if verbose:
                    print(f"  + [GCAL-invite] {rec['invitee_name']} <{org_email}> "
                          f"{meeting_at} [{rec['profile_slug'] or 'unmatched'}]")
                _send_gcal_alert(rec, dry=False)
    finally:
        try: imap.logout()
        except Exception: pass
    save_store(store)
    if verbose:
        print(f"scan_gcal: +{added} calendar invite(s) "
              f"({len(store['meetings'])} total in store)")
    return added


# ─── prompt: GUI pop-up for due meetings ─────────────────────────────────────

def _resolved(mt: dict) -> bool:
    """A meeting is fully resolved (won't re-pop) when its outcome is recorded AND
    the follow-up decision is final. The follow-up step adds a `followup_status`:
      sent / queued / skipped / not_sales  -> done, never re-pops.
      later                                 -> deferred; the DRAFT popup re-pops.
    A meeting with an outcome but NO followup_status is a legacy record handled under
    the old code path (no draft popup existed); treat its handled_at as resolved so
    those never spuriously re-pop."""
    oc = mt.get("outcome")
    if oc is None:
        return False                      # outcome not captured yet -> show outcome dialog
    if oc == "not_sales":
        return True                       # not a buyer: no follow-up by design
    fs = mt.get("followup_status")
    if fs in ("sent", "queued", "skipped", "not_sales"):
        return True
    if fs == "later":
        return False                      # deferred -> re-pop the draft popup only
    return bool(mt.get("handled_at"))     # legacy record: handled_at means done


def _due_meetings(store: dict) -> list[dict]:
    now = dt.datetime.utcnow()
    due = []
    for mt in store["meetings"]:
        if _resolved(mt):
            continue
        try:
            end = dt.datetime.fromisoformat(mt["meeting_at"]) + dt.timedelta(
                minutes=mt.get("duration_min", 30))
        except Exception:
            continue
        if end <= now:
            due.append(mt)
    return due


# Injected text (invitee names from external email, AI drafts, subjects) goes into
# the dialogs as LITERAL data via single-quoted PowerShell here-strings (@'...'@) and
# single-quoted strings. Single-quoted PS literals do NOT expand $, $(...) or process
# backticks, so a crafted name/draft/subject cannot execute code. _ps_heredoc guards
# the only thing that can still break a single-quoted here-string: its '@ terminator.
def _ps_heredoc(s: str) -> str:
    """Neutralize the single-quoted here-string terminator so injected text stays inside."""
    return (s or "").replace("'@", "' @")


def _ps_singleline(s: str) -> str:
    """Safe literal for a single-quoted single-line PS string: double embedded
    single quotes and flatten newlines."""
    return (s or "").replace("\r", " ").replace("\n", " ").replace("'", "''")


_PS_DIALOG = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$f = New-Object System.Windows.Forms.Form
$f.Text = "Meeting outcome"
$f.Size = New-Object System.Drawing.Size(460,390)
$f.StartPosition = "CenterScreen"
$f.TopMost = $true
$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = @'
{HEADER}
'@
$lbl.Location = New-Object System.Drawing.Point(15,12)
$lbl.Size = New-Object System.Drawing.Size(420,55)
$f.Controls.Add($lbl)
$grp = New-Object System.Windows.Forms.GroupBox
$grp.Text = "What happened?"
$grp.Location = New-Object System.Drawing.Point(15,72)
$grp.Size = New-Object System.Drawing.Size(420,148)
$opts = @("No-show","Showed - interested","Showed - not a fit","Rescheduled / later","Not sales / not a buyer (no follow-up)")
$y = 20
$radios = @()
foreach ($o in $opts) {
  $r = New-Object System.Windows.Forms.RadioButton
  $r.Text = $o; $r.Location = New-Object System.Drawing.Point(12,$y)
  $r.Size = New-Object System.Drawing.Size(380,22); $grp.Controls.Add($r)
  $radios += $r; $y += 24
}
$radios[0].Checked = $true
$f.Controls.Add($grp)
$nlbl = New-Object System.Windows.Forms.Label
$nlbl.Text = "Notes (free text, optional):"
$nlbl.Location = New-Object System.Drawing.Point(15,228)
$nlbl.Size = New-Object System.Drawing.Size(420,18)
$f.Controls.Add($nlbl)
$tb = New-Object System.Windows.Forms.TextBox
$tb.Multiline = $true; $tb.Location = New-Object System.Drawing.Point(15,248)
$tb.Size = New-Object System.Drawing.Size(420,55); $tb.ScrollBars = "Vertical"
$f.Controls.Add($tb)
$ok = New-Object System.Windows.Forms.Button
$ok.Text = "Submit"; $ok.Location = New-Object System.Drawing.Point(250,312)
$ok.Size = New-Object System.Drawing.Size(85,28)
$ok.DialogResult = [System.Windows.Forms.DialogResult]::OK
$f.Controls.Add($ok); $f.AcceptButton = $ok
$skip = New-Object System.Windows.Forms.Button
$skip.Text = "Skip"; $skip.Location = New-Object System.Drawing.Point(345,312)
$skip.Size = New-Object System.Drawing.Size(85,28)
$skip.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
$f.Controls.Add($skip); $f.CancelButton = $skip
$res = $f.ShowDialog()
if ($res -eq [System.Windows.Forms.DialogResult]::OK) {
  $sel = ($radios | Where-Object { $_.Checked } | Select-Object -First 1).Text
  $out = @{ outcome = $sel; notes = $tb.Text } | ConvertTo-Json -Compress
  Write-Output $out
} else {
  Write-Output '{"outcome":null}'
}
'''

_OUTCOME_MAP = {
    "No-show": "no_show",
    "Showed - interested": "interested",
    "Showed - not a fit": "not_fit",
    "Rescheduled / later": "rescheduled",
    "Not sales / not a buyer (no follow-up)": "not_sales",
}


def _show_dialog(mt: dt.datetime) -> dict | None:
    header = (f"Invitee: {mt['invitee_name']} <{mt['invitee_email']}>\n"
              f"Client: {mt.get('profile_slug') or 'unmatched'}\n"
              f"Meeting was: {mt['meeting_at'].replace('T', ' ')} "
              f"({mt.get('duration_min', 30)} min)")
    script = _PS_DIALOG.replace("{HEADER}", _ps_heredoc(header))
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=600, encoding="utf-8", errors="replace")
        out = (proc.stdout or "").strip()
        line = [l for l in out.splitlines() if l.strip().startswith("{")]
        if not line:
            return None
        data = json.loads(line[-1])
        if not data.get("outcome"):
            return None
        return data
    except Exception as e:
        print(f"  ! dialog failed: {e}")
        return None


# ─── outcome handling: note email + draft follow-up ──────────────────────────

def _resend_send(to_addr: str, subject: str, body: str, from_disp: str,
                 from_addr: str, dry: bool) -> bool:
    if dry:
        print(f"  [DRY] would send to {to_addr}: '{subject}'")
        return True
    payload = {"from": f"{from_disp} <{from_addr}>", "to": [to_addr],
               "subject": subject[:200], "text": body,
               "reply_to": from_addr}
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {RESEND_KEY}",
                 "Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=20)
        return True
    except Exception as e:
        # Fallback to Hostinger SMTP from info@
        try:
            pw = HOST.get("SMTP_PASS", "")
            user = HOST.get("SMTP_USER", OPERATOR_ADDR)
            m = MIMEText(body, "plain", "utf-8")
            m["Subject"] = subject[:200]; m["From"] = f"{from_disp} <{user}>"
            m["To"] = to_addr; m["Reply-To"] = user
            with smtplib.SMTP_SSL("smtp.hostinger.com", 465,
                                  context=ssl.create_default_context()) as s:
                s.login(user, pw)
                s.sendmail(user, [to_addr], m.as_string())
            return True
        except Exception as e2:
            print(f"  ! send failed (resend: {e}; smtp: {e2})")
            return False


def _followup_brief(outcome: str, mt: dict) -> str:
    """The instruction handed to the drafter for each outcome branch."""
    name = mt["invitee_name"].split()[0] if mt.get("invitee_name") else "there"
    if outcome == "no_show":
        return (f"{name} booked a call but did not show up. Write a short, no-blame "
                f"note: acknowledge calls slip, keep the door wide open, restate the "
                f"core value in one line, and give them a one-click way to rebook. "
                f"Hormozi tone: warm, zero guilt-trip, make rebooking the obvious easy step.")
    if outcome == "interested":
        return (f"{name} showed up and was interested. Write a recap-and-next-step note: "
                f"thank them, restate the one outcome they care about, name the single "
                f"clear next step (proposal / start date / a yes), and make saying yes easy.")
    if outcome == "not_fit":
        return (f"{name} showed up but it is not a fit right now. Write a clean, gracious "
                f"close: no hard sell, leave the door open for the future, offer one piece "
                f"of genuine value they can use whether or not we ever work together.")
    if outcome == "rescheduled":
        return (f"{name} wants to talk again later. Write a brief, friendly note confirming "
                f"you will circle back at the right time, restate the value in one line, and "
                f"make it effortless for them to grab a new time now if they prefer.")
    return f"Write a brief, professional follow-up to {name}."


# ─── draft-approval popup ────────────────────────────────────────────────────

_PS_DRAFT_DIALOG = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$f = New-Object System.Windows.Forms.Form
$f.Text = "Follow-up draft - your decision"
$f.Size = New-Object System.Drawing.Size(700,560)
$f.StartPosition = "CenterScreen"
$f.TopMost = $true

$hdr = New-Object System.Windows.Forms.Label
$hdr.Text = @'
{HEADER}
'@
$hdr.Location = New-Object System.Drawing.Point(12,10)
$hdr.Size = New-Object System.Drawing.Size(664,55)
$hdr.Font = New-Object System.Drawing.Font("Segoe UI",9)
$f.Controls.Add($hdr)

$slbl = New-Object System.Windows.Forms.Label
$slbl.Text = "Subject (editable):"
$slbl.Location = New-Object System.Drawing.Point(12,72)
$slbl.Size = New-Object System.Drawing.Size(664,18)
$f.Controls.Add($slbl)

$subj = New-Object System.Windows.Forms.TextBox
$subj.Location = New-Object System.Drawing.Point(12,92)
$subj.Size = New-Object System.Drawing.Size(664,24)
$subj.Text = '{SUBJECT}'
$f.Controls.Add($subj)

$blbl = New-Object System.Windows.Forms.Label
$blbl.Text = "Draft body (edit freely before sending):"
$blbl.Location = New-Object System.Drawing.Point(12,126)
$blbl.Size = New-Object System.Drawing.Size(664,18)
$f.Controls.Add($blbl)

$body = New-Object System.Windows.Forms.TextBox
$body.Multiline = $true; $body.ScrollBars = "Vertical"
$body.Location = New-Object System.Drawing.Point(12,146)
$body.Size = New-Object System.Drawing.Size(664,290)
$body.Font = New-Object System.Drawing.Font("Segoe UI",10)
$body.Text = @'
{DRAFT}
'@
$f.Controls.Add($body)

# Default when the window is closed with no button = "later" (safe: defers, never
# discards or sends). A real "skip" must be an explicit click.
$result = New-Object System.Windows.Forms.TextBox
$result.Visible = $false
$result.Text = "later"

function mk($text,$x,$w,$val) {
  $b = New-Object System.Windows.Forms.Button
  $b.Text = $text
  $b.Location = New-Object System.Drawing.Point($x,456)
  $b.Size = New-Object System.Drawing.Size($w,36)
  $b.Add_Click({ $result.Text = $val; $f.Close() }.GetNewClosure())
  $f.Controls.Add($b)
}
mk "Send to prospect now" 12 158 "send"
mk "Queue as draft email" 178 150 "queue"
mk "Skip (no follow-up)" 336 150 "skip"
mk "Decide later" 494 110 "later"

$f.Add_Shown({ $f.Activate() })
[void]$f.ShowDialog()
$out = @{ action = $result.Text; subject = $subj.Text; body = $body.Text } | ConvertTo-Json -Compress
Write-Output $out
'''


def _show_draft_approval_dialog(mt: dict, outcome: str, draft: str, subj: str) -> dict | None:
    pretty = {"no_show": "No-show", "interested": "Showed, interested",
              "not_fit": "Showed, not a fit", "rescheduled": "Rescheduled / later"}.get(outcome, outcome)
    sender = HOST.get("SMTP_USER", OPERATOR_ADDR)
    header = (
        f"Prospect : {mt['invitee_name']} <{mt['invitee_email']}>\n"
        f"Outcome  : {pretty}   Client: {mt.get('profile_slug') or 'unmatched'}\n"
        f"Sends as Gentrit <{sender}> if you click Send. Edit the draft, then choose."
    )

    script = (_PS_DRAFT_DIALOG
              .replace("{HEADER}", _ps_heredoc(header))
              .replace("{SUBJECT}", _ps_singleline(subj))
              .replace("{DRAFT}", _ps_heredoc(draft)))
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            capture_output=True, text=True, timeout=1800, encoding="utf-8",
            errors="replace")
        out = (proc.stdout or "").strip()
        line = [ln for ln in out.splitlines() if ln.strip().startswith("{")]
        if not line:
            return None
        return json.loads(line[-1])
    except Exception as e:
        print(f"  ! draft-approval dialog failed: {e}")
        return None


def _smtp_send_to_prospect(to_addr: str, subject: str, body_text: str,
                           dry: bool) -> bool:
    if dry:
        print(f"  [DRY] would send to prospect {to_addr}: '{subject}'")
        return True
    pw = HOST.get("SMTP_PASS", "")
    user = HOST.get("SMTP_USER", OPERATOR_ADDR)
    if not pw:
        print("  ! no SMTP_PASS; cannot send to prospect")
        return False
    try:
        m = MIMEText(body_text, "plain", "utf-8")
        m["Subject"] = subject
        m["From"] = f"Gentrit <{user}>"
        m["To"] = to_addr
        m["Reply-To"] = user
        with smtplib.SMTP_SSL("smtp.hostinger.com", 465,
                              context=ssl.create_default_context()) as s:
            s.login(user, pw)
            s.sendmail(user, [to_addr], m.as_string())
        return True
    except Exception as e:
        print(f"  ! SMTP send to prospect failed: {e}")
        return False


def handle_outcome(mt: dict, outcome: str, notes: str, reengage_at: str | None,
                   dry: bool, store: dict | None = None) -> str:
    """Run the follow-up step for a meeting outcome. Returns the follow-up status
    the caller persists as mt['followup_status']: 'sent' / 'queued' / 'skipped' /
    'later' / 'not_sales'. 'later' is the only non-final status (re-pops the draft).

    `store` (when given) is persisted the instant a prospect send succeeds, so a
    crash/kill between the irreversible send and the caller's own save cannot leave
    the meeting un-marked and cause a duplicate send on the next run."""
    slug = mt.get("profile_slug")
    profile = None
    persona = None
    if slug:
        prows = supa_get(f"profiles?slug=eq.{slug}&select=config")
        profile = prows[0]["config"] if prows else None

    # "Not sales / not a buyer" — the operator says this booking is not a sales
    # opportunity (a vendor, a recruiter, a friend, an internal call). NOTHING runs:
    # no follow-up sequence, no draft. Just a one-line record note so it stays logged.
    if outcome == "not_sales":
        note_body = (
            f"Meeting marked NOT sales / not a buyer. No follow-up triggered.\n\n"
            f"Invitee : {mt['invitee_name']} <{mt['invitee_email']}>\n"
            f"When    : {mt['meeting_at'].replace('T', ' ')}\n"
            f"Your notes: {notes or '(none)'}\n"
        )
        _resend_send(OPERATOR_ADDR, f"[Meeting] Not sales - {mt['invitee_name']}",
                     note_body, "Aureon Meeting Bot", "drafts@hi.aureonglobal.de", dry)
        return "not_sales"

    pretty = {"no_show": "No-show", "interested": "Showed, interested",
              "not_fit": "Showed, not a fit", "rescheduled": "Rescheduled / later"}.get(outcome, outcome)

    # 1) Generate the AI draft immediately so it's ready for the popup.
    brief = _followup_brief(outcome, mt)
    if notes:
        brief += f"\n\nThe operator's notes from the call (use these, they are ground truth): {notes}"
    draft = _draft_followup(profile, persona, mt, brief)
    subj = {"no_show": f"Sorry we missed each other, {mt['invitee_name'].split()[0]}",
            "interested": "Following up on our call",
            "not_fit": f"Good talking, {mt['invitee_name'].split()[0]}",
            "rescheduled": "Whenever the timing is right"}.get(outcome, "Following up")

    # 2) Show the draft-approval popup so the operator can review/edit + decide.
    draft_action = "queue"  # default if popup is suppressed (dry mode)
    final_subj = subj
    final_body = draft
    if not dry:
        res = _show_draft_approval_dialog(mt, outcome, draft, subj)
        if res:
            draft_action = res.get("action") or "later"
            final_subj = (res.get("subject") or subj).strip()
            final_body = (res.get("body") or draft).strip()
        else:
            # Dialog subprocess failed (not a user choice). Queue so the operator
            # still gets the draft, rather than silently deferring forever.
            print(f"  ~ draft dialog failed; queuing as email")

    # 2b) "Decide later" — defer with no send and no note. The meeting keeps a
    # followup_status of 'later', so the next run re-pops the draft popup only
    # (the outcome is already saved and is not re-asked).
    if draft_action == "later":
        print(f"  · {mt['invitee_name']}: follow-up deferred (draft re-pops next run)")
        return "later"

    # 3) Act on the operator's decision.
    if draft_action == "send":
        ok = _smtp_send_to_prospect(mt["invitee_email"], final_subj, final_body, dry)
        sent_label = "SENT to prospect" if ok else "SEND FAILED"
        # Persist the resolved state the instant the irreversible send succeeds, so a
        # kill before the caller's own save() cannot re-pop this meeting and double-send.
        if ok and not dry and store is not None:
            mt["followup_status"] = "sent"
            mt["handled_at"] = dt.datetime.utcnow().isoformat() + "Z"
            save_store(store)
        note_body = (
            f"Meeting outcome logged + follow-up {sent_label}.\n\n"
            f"Invitee : {mt['invitee_name']} <{mt['invitee_email']}>\n"
            f"Client  : {slug or 'unmatched'}\n"
            f"When    : {mt['meeting_at'].replace('T', ' ')} ({mt.get('duration_min', 30)} min)\n"
            f"Outcome : {pretty}\n"
            + (f"Re-engage: {reengage_at}\n" if reengage_at else "")
            + f"Your notes: {notes or '(none)'}\n\n"
            f"--- sent subject ---\n{final_subj}\n"
            f"--- sent body ---\n{final_body}\n"
        )
        _resend_send(OPERATOR_ADDR, f"[Meeting] {pretty} - {mt['invitee_name']} ({sent_label})",
                     note_body, "Aureon Meeting Bot", "drafts@hi.aureonglobal.de", dry)
        return "sent"
    elif draft_action == "queue":
        # Original behavior: send note + draft email to operator for manual follow-through.
        note_body = (
            f"Meeting outcome logged.\n\n"
            f"Invitee : {mt['invitee_name']} <{mt['invitee_email']}>\n"
            f"Client  : {slug or 'unmatched'}\n"
            f"When    : {mt['meeting_at'].replace('T', ' ')} ({mt.get('duration_min', 30)} min)\n"
            f"Outcome : {pretty}\n"
            + (f"Re-engage: {reengage_at}\n" if reengage_at else "")
            + f"Your notes: {notes or '(none)'}\n\n"
            f"Draft queued below. Forward to the prospect when ready.\n"
        )
        _resend_send(OPERATOR_ADDR, f"[Meeting] {pretty} - {mt['invitee_name']}",
                     note_body, "Aureon Meeting Bot", "drafts@hi.aureonglobal.de", dry)
        draft_body = (
            f"DRAFT follow-up for {mt['invitee_name']} <{mt['invitee_email']}> ({slug or 'unmatched'})\n"
            f"Outcome: {pretty}\n"
            f"--- suggested subject ---\n{final_subj}\n"
            f"--- suggested body (edit, then send to the prospect) ---\n\n{final_body}\n"
        )
        _resend_send(OPERATOR_ADDR, f"[Draft follow-up] {mt['invitee_name']} - {pretty}",
                     draft_body, "Aureon Meeting Bot", "drafts@hi.aureonglobal.de", dry)
        return "queued"
    else:
        # "skip" — operator chose NO follow-up for this meeting. Log a minimal note
        # so the outcome stays on record, then resolve it permanently (won't re-pop).
        note_body = (
            f"Meeting outcome logged (NO follow-up - skipped by operator).\n\n"
            f"Invitee : {mt['invitee_name']} <{mt['invitee_email']}>\n"
            f"Client  : {slug or 'unmatched'}\n"
            f"When    : {mt['meeting_at'].replace('T', ' ')} ({mt.get('duration_min', 30)} min)\n"
            f"Outcome : {pretty}\n"
            + (f"Re-engage: {reengage_at}\n" if reengage_at else "")
            + f"Your notes: {notes or '(none)'}\n"
        )
        _resend_send(OPERATOR_ADDR, f"[Meeting] {pretty} - {mt['invitee_name']} (no follow-up)",
                     note_body, "Aureon Meeting Bot", "drafts@hi.aureonglobal.de", dry)
        return "skipped"


def _draft_followup(profile: dict | None, persona: dict | None, mt: dict,
                    brief: str) -> str:
    """Drive the local Claude CLI to write the follow-up. Falls back to a
    template. Reuses the proven sandbox recipe from reply-autodraft.py."""
    company = ((profile or {}).get("brand", {}) or {}).get("wordmark") \
        or (profile or {}).get("name", "our team")
    system = (
        "You are an elite B2B sales copywriter embedded in a CRM, writing in the "
        "style of Alex Hormozi. The user just had (or scheduled) a sales call and "
        "needs a short follow-up email to the other person in an ongoing, consented "
        "B2B conversation. You write like a sharp, warm human closer, never like an AI. "
        "HARD RULES: never use an em-dash or en-dash anywhere, use a period or comma. "
        "Never use: delighted, reach out, touch base, synergy, leverage, circle back, "
        "I hope this email finds you, valued. No emojis, no corporate filler. "
        "Output ONLY the email body, nothing else."
    )
    prompt = (
        f"I run {company}. Draft my follow-up email.\n\n"
        f"Situation: {brief}\n\n"
        f"Keep it under 90 words. Concrete and specific. Name one clear, easy next step. "
        f"No subject line, no commentary, no signature line beyond a simple sign-off."
    )
    import tempfile, shutil
    workdir = tempfile.mkdtemp(prefix="les_mtg_")
    try:
        proc = subprocess.run(
            [CLAUDE_CMD, "-p", "--system-prompt", system,
             "--disallowedTools", "Bash,Read,Glob,Grep,Edit,Write,WebFetch,WebSearch",
             "--setting-sources", "user"],
            input=prompt, capture_output=True, text=True, timeout=150,
            encoding="utf-8", errors="replace", cwd=workdir,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if proc.returncode == 0 and proc.stdout.strip():
            text = proc.stdout.strip()
            text = re.sub(r"^Warning: no stdin data received.*?\n", "", text, flags=re.I).strip()
            text = text.replace("—", ", ").replace("–", "-")
            if text:
                return text
    except Exception as e:
        print(f"  ! claude draft failed: {e}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    # Template fallback
    name = mt["invitee_name"].split()[0] if mt.get("invitee_name") else "there"
    return (f"Hi {name},\n\n[Draft engine unavailable, write this one manually based "
            f"on the outcome and notes above.]\n\nBest,\nThe team")


def prompt(dry: bool = False) -> int:
    store = load_store()
    due = _due_meetings(store)
    if not due:
        print("prompt: no meetings awaiting attention")
        return 0
    print(f"prompt: {len(due)} meeting(s) awaiting attention")
    handled = 0
    for mt in due:
        if dry:
            stage = "draft popup" if mt.get("outcome") else "outcome dialog"
            print(f"  [DRY] would pop {stage} for {mt['invitee_name']} "
                  f"<{mt['invitee_email']}> {mt['meeting_at']}")
            continue
        # A due meeting that ALREADY has an outcome is a deferred follow-up
        # (followup_status 'later'): skip the outcome dialog and go straight to the
        # draft popup, so the operator is never re-asked what already was answered.
        if mt.get("outcome"):
            outcome = mt["outcome"]
            notes = (mt.get("notes") or "").strip()
            reengage_at = mt.get("reengage_at")
        else:
            res = _show_dialog(mt)
            if not res:
                print(f"  ~ skipped {mt['invitee_name']}")
                continue
            outcome = _OUTCOME_MAP.get(res["outcome"])
            notes = (res.get("notes") or "").strip()
            reengage_at = None
            if outcome == "rescheduled":
                reengage_at = _ask_reengage_date()
            # Persist the outcome now so a subsequent 'Decide later' never re-asks it.
            mt["outcome"] = outcome
            mt["notes"] = notes
            mt["reengage_at"] = reengage_at
            save_store(store)
        status = handle_outcome(mt, outcome, notes, reengage_at, dry=False, store=store)
        mt["followup_status"] = status
        mt["handled_at"] = dt.datetime.utcnow().isoformat() + "Z"
        save_store(store)
        handled += 1
        if status == "later":
            print(f"  · {mt['invitee_name']}: {outcome} -> follow-up deferred (re-pops next run)")
        elif outcome == "not_sales":
            print(f"  + {mt['invitee_name']}: not_sales -> logged, NO follow-up")
        else:
            print(f"  + {mt['invitee_name']}: {outcome} -> follow-up {status}")
    return handled


def _ask_reengage_date() -> str | None:
    script = (
        'Add-Type -AssemblyName Microsoft.VisualBasic;'
        '$d=[Microsoft.VisualBasic.Interaction]::InputBox('
        '"Re-engage on which date? (YYYY-MM-DD, blank to skip)","Reschedule","");'
        'Write-Output $d')
    try:
        proc = subprocess.run(["powershell", "-NoProfile", "-STA", "-Command", script],
                              capture_output=True, text=True, timeout=300,
                              encoding="utf-8", errors="replace")
        v = (proc.stdout or "").strip()
        return v or None
    except Exception:
        return None


def list_store() -> None:
    store = load_store()
    if not store["meetings"]:
        print("(store empty)"); return
    for mt in sorted(store["meetings"], key=lambda x: x["meeting_at"]):
        st = mt.get("outcome") or "PENDING"
        print(f"  {mt['meeting_at'][:16]}  {mt['invitee_name']:24s} "
              f"<{mt['invitee_email']:30s}> [{mt.get('profile_slug') or '-'}]  {st}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("scan")
    sub.add_parser("scan-zoom")
    sub.add_parser("scan-gcal")
    p_prompt = sub.add_parser("prompt"); p_prompt.add_argument("--dry", action="store_true")
    p_run = sub.add_parser("run"); p_run.add_argument("--dry", action="store_true")
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "scan":
        scan()
        scan_zoom()
        scan_gcal()
    elif a.cmd == "scan-zoom":
        scan_zoom()
    elif a.cmd == "scan-gcal":
        scan_gcal()
    elif a.cmd == "prompt":
        prompt(dry=a.dry)
    elif a.cmd == "run":
        scan()        # Calendly "New Event" first, so the store is populated
        scan_zoom()   # then the Zoom backstop only flags true blindspots
        scan_gcal()   # and direct calendar invites (the third channel)
        prompt(dry=a.dry)
    elif a.cmd == "list":
        list_store()
    return 0


if __name__ == "__main__":
    sys.exit(main())
