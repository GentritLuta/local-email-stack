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
    finally:
        try: imap.logout()
        except Exception: pass
    save_store(store)
    if verbose:
        print(f"scan: +{added} new meetings ({len(store['meetings'])} total in store)")
    return added


# ─── prompt: GUI pop-up for due meetings ─────────────────────────────────────

def _due_meetings(store: dict) -> list[dict]:
    now = dt.datetime.utcnow()
    due = []
    for mt in store["meetings"]:
        if mt.get("outcome"):
            continue
        try:
            end = dt.datetime.fromisoformat(mt["meeting_at"]) + dt.timedelta(
                minutes=mt.get("duration_min", 30))
        except Exception:
            continue
        if end <= now:
            due.append(mt)
    return due


_PS_DIALOG = r'''
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$f = New-Object System.Windows.Forms.Form
$f.Text = "Meeting outcome"
$f.Size = New-Object System.Drawing.Size(460,390)
$f.StartPosition = "CenterScreen"
$f.TopMost = $true
$lbl = New-Object System.Windows.Forms.Label
$lbl.Text = @"
{HEADER}
"@
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
    script = _PS_DIALOG.replace("{HEADER}", header)
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


def handle_outcome(mt: dict, outcome: str, notes: str, reengage_at: str | None,
                   dry: bool) -> None:
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
        return
    # 1) NOTE email to the operator
    pretty = {"no_show": "No-show", "interested": "Showed, interested",
              "not_fit": "Showed, not a fit", "rescheduled": "Rescheduled / later"}.get(outcome, outcome)
    note_body = (
        f"Meeting outcome logged.\n\n"
        f"Invitee : {mt['invitee_name']} <{mt['invitee_email']}>\n"
        f"Client  : {slug or 'unmatched'}\n"
        f"When    : {mt['meeting_at'].replace('T', ' ')} ({mt.get('duration_min', 30)} min)\n"
        f"Outcome : {pretty}\n"
        + (f"Re-engage: {reengage_at}\n" if reengage_at else "")
        + f"Your notes: {notes or '(none)'}\n\n"
        f"Follow-up: a draft has been queued below for your approval. Review and "
        f"forward to the prospect if it looks good.\n"
    )
    _resend_send(OPERATOR_ADDR, f"[Meeting] {pretty} - {mt['invitee_name']}",
                 note_body, "Aureon Meeting Bot",
                 "drafts@hi.aureonglobal.de", dry)

    # 2) DRAFT the follow-up (queued to operator, NOT sent to prospect)
    brief = _followup_brief(outcome, mt)
    if notes:
        brief += f"\n\nThe operator's notes from the call (use these, they are ground truth): {notes}"
    draft = _draft_followup(profile, persona, mt, brief)
    subj = {"no_show": f"Sorry we missed each other, {mt['invitee_name'].split()[0]}",
            "interested": f"Following up on our call",
            "not_fit": f"Good talking, {mt['invitee_name'].split()[0]}",
            "rescheduled": f"Whenever the timing is right"}.get(outcome, "Following up")
    draft_body = (
        f"DRAFT follow-up for {mt['invitee_name']} <{mt['invitee_email']}> ({slug or 'unmatched'})\n"
        f"Outcome: {pretty}\n"
        f"--- suggested subject ---\n{subj}\n"
        f"--- suggested body (edit, then send to the prospect) ---\n\n{draft}\n"
    )
    _resend_send(OPERATOR_ADDR, f"[Draft follow-up] {mt['invitee_name']} - {pretty}",
                 draft_body, "Aureon Meeting Bot", "drafts@hi.aureonglobal.de", dry)


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
        print("prompt: no meetings awaiting an outcome")
        return 0
    print(f"prompt: {len(due)} meeting(s) awaiting outcome")
    handled = 0
    for mt in due:
        if dry:
            print(f"  [DRY] would pop dialog for {mt['invitee_name']} "
                  f"<{mt['invitee_email']}> {mt['meeting_at']}")
            continue
        res = _show_dialog(mt)
        if not res:
            print(f"  ~ skipped {mt['invitee_name']}")
            continue
        outcome = _OUTCOME_MAP.get(res["outcome"])
        notes = (res.get("notes") or "").strip()
        reengage_at = None
        if outcome == "rescheduled":
            reengage_at = _ask_reengage_date()
        handle_outcome(mt, outcome, notes, reengage_at, dry=False)
        mt["outcome"] = outcome
        mt["notes"] = notes
        mt["reengage_at"] = reengage_at
        mt["handled_at"] = dt.datetime.utcnow().isoformat() + "Z"
        save_store(store)
        handled += 1
        if outcome == "not_sales":
            print(f"  + {mt['invitee_name']}: not_sales -> logged, NO follow-up (note only to {OPERATOR_ADDR})")
        else:
            print(f"  + {mt['invitee_name']}: {outcome} -> note + draft queued to {OPERATOR_ADDR}")
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
    p_prompt = sub.add_parser("prompt"); p_prompt.add_argument("--dry", action="store_true")
    p_run = sub.add_parser("run"); p_run.add_argument("--dry", action="store_true")
    sub.add_parser("list")
    a = ap.parse_args()
    if a.cmd == "scan":
        scan()
    elif a.cmd == "prompt":
        prompt(dry=a.dry)
    elif a.cmd == "run":
        scan()
        prompt(dry=a.dry)
    elif a.cmd == "list":
        list_store()
    return 0


if __name__ == "__main__":
    sys.exit(main())
