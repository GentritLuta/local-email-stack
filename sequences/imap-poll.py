"""imap-poll.py — pull replies from info@aureonglobal.de via Hostinger IMAP.

Every cold send sets Reply-To: info@aureonglobal.de, so real human replies land in
that one mailbox. This poller:
  1. Connects to imap.hostinger.com:993 with the same Hostinger creds we use for SMTP
  2. Walks UNSEEN messages
  3. Classifies each (reply / bounce / complaint / unrelated)
  4. Tries to match In-Reply-To / References / In body Message-ID against Supabase
     send_log → resolves the originating run_id
  5. INSERTs a row into Supabase `replies`
  6. If class=reply and we found the run: PATCH runs.status='paused_replied'
  7. Marks the message as Seen so we don't re-process

Designed to run every 5 min as a scheduled task.

Usage:
    py imap-poll.py once                # one pass, exit
    py imap-poll.py loop --interval 300 # forever, every 5 min
"""

from __future__ import annotations

import argparse
import datetime as dt
import email
import email.policy
import imaplib
import json
import os
import re
import smtplib
import ssl
import sys
import time

# Force UTF-8 stdout/stderr on Windows so logging international characters
# (umlauts, dashes, checkmarks etc.) doesn't crash the script with charmap
# codec errors when scheduled-task console encoding is cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import parseaddr, formatdate, make_msgid
from pathlib import Path

import httpx

import sys as _sys
_sys.path.insert(0, str(Path(__file__).resolve().parent))
import suppress  # global do-not-contact list

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─── Config loader ─────────────────────────────────────────────────────────

def load_env(path: Path) -> dict:
    env = dict(os.environ)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def hostinger_creds() -> tuple[str, str]:
    env = load_env(REPO_ROOT / "sequences" / "hostinger.env")
    user = env.get("SMTP_USER", "info@aureonglobal.de")
    password = env.get("SMTP_PASS", "")
    if not password:
        sys.exit("missing SMTP_PASS in sequences/hostinger.env")
    return user, password


def supabase_creds() -> tuple[str, str]:
    env = load_env(REPO_ROOT / "sequences" / "supabase.env")
    url = env.get("SUPABASE_URL", "").rstrip("/")
    key = env.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        sys.exit("missing SUPABASE_URL / SUPABASE_ANON_KEY in sequences/supabase.env")
    return url, key


# ─── Classification ─────────────────────────────────────────────────────────

BOUNCE_FROM = re.compile(r"^(mailer-daemon|postmaster|bounce|noreply|no-reply)@", re.I)
COMPLAINT_FROM = re.compile(r"^(abuse|feedback-loop)@", re.I)
BOUNCE_SUBJ = re.compile(r"(undelivered|delivery (status|failure)|returned mail|mail delivery|address (not found|rejected))", re.I)

# Opt-out intent in a reply. Checked only against the TOP of the reply (text
# before quoted history) so our own quoted unsubscribe footer never self-fires.
UNSUB_RX = re.compile(r"\b(unsubscribe|opt[\s-]?out|remove me|take me off|stop "
                      r"(?:emailing|sending|contacting)|do not (?:contact|email)|"
                      r"no longer.*(?:contact|email)|leave me alone|not interested.*stop)\b", re.I)
# A reply that IS just a bare negative ("NEIN", "No", "Nope") is a hard decline.
# Matched on the WHOLE stripped top-reply so a longer interested reply that merely
# contains the word is not caught. Added after a NEIN reply was pitched (2026-07-17).
_BARE_NO_RX = re.compile(r"^\W*(no|nein|nope|non|stop|kein interesse|nein danke|kein bedarf)\W*$", re.I)


def is_optout_reply(top: str, subject: str) -> bool:
    """True if the prospect's reply signals opt-out/decline: an explicit unsubscribe
    phrase anywhere, OR a bare-negative that is the entire top reply."""
    return bool(UNSUB_RX.search((top or "") + " " + (subject or ""))
                or _BARE_NO_RX.match((top or "").strip()))
# Free/shared email providers — never domain-suppress these on a single opt-out (a person
# replying "unsubscribe" from their personal gmail must not opt out every gmail prospect).
_FREE_EMAIL_DOMAINS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com", "outlook.com",
    "live.com", "msn.com", "icloud.com", "me.com", "aol.com", "proton.me", "protonmail.com",
    "gmx.de", "gmx.net", "web.de", "t-online.de", "mail.com", "yandex.com", "zoho.com",
}
_QUOTE_LINE = re.compile(r"^(_{5,}|-{5,}|from:|sent:|to:|subject:|on .+wrote:|>.*)", re.I)

# Never treat mail from these as a prospect cold reply (no alert, no reply-stop,
# no auto-draft). laso.finance is an ACTIVE LEGAL MATTER that must never be engaged;
# the aureonglobal / diraya domains are our own sending + inbox infra, so a threaded
# "Re:" from them is internal mail, not a prospect.
EXCLUDE_FROM = re.compile(r"@([\w.-]*(?:aureonglobal|diraya)[\w.-]*|laso\.finance)$", re.I)
# Account / transactional mail that threads as "Re:" but is never a cold-email reply.
NOISE_SUBJ = re.compile(r"\b(invoice|settlement|receipt|refund|retoure|chargeback|"
                        r"card on file|\bucof\b|account statement|past due|"
                        r"verification code|reset your password|confirm your email|"
                        r"order\s*#|return\s*#)\b", re.I)


def top_reply_text(body: str) -> str:
    """The sender's own words — everything before the quoted original."""
    out = []
    for ln in (body or "").splitlines():
        s = ln.strip()
        if _QUOTE_LINE.match(s) or "________" in s:
            break
        out.append(ln)
    return "\n".join(out)


ALERT_SUBJECT_PREFIX = "[REPLY ALERT] "

def send_reply_alert(env: dict, *, from_addr: str, original_subject: str,
                     snippet: str, lead_email: str,
                     lead_name: str | None = None,
                     run_id: str | None = None) -> bool:
    """Send an internal alert email to info@aureonglobal.de when a real
    cold-outreach reply lands.

    Routes through Resend (the cold-outreach send infra) rather than
    Hostinger SMTP. Why: Hostinger Email's per-mailbox quota (100/day on
    Business plan) was getting burned by these alerts plus all the
    bounce / auto-reply / vacation-responder inbound traffic, which left
    the user's info@ inbox blocked from any further legitimate
    correspondence. Resend has unlimited send capacity on the Pro plan
    and uses a dedicated subdomain that doesn't conflict with the
    mailbox quota.
    """
    import urllib.request, urllib.error, json as _json
    resend_key = (env.get("RESEND_FULL_ACCESS_API_KEY")
                  or env.get("RESEND_API_KEY"))
    to_addr = env.get("ALERT_TO_ADDR", "info@aureonglobal.de")
    if not resend_key:
        print("  ! alert send skipped: no RESEND_FULL_ACCESS_API_KEY in env")
        return False
    subj = (ALERT_SUBJECT_PREFIX
            + (f"{lead_name or lead_email} replied"
               if lead_email else "new reply landed"))
    body_html = f"""\
<div style="font-family:system-ui,-apple-system,sans-serif;color:#1e293b;max-width:560px">
  <h2 style="margin:0 0 12px 0;color:#16a34a">📨 New prospect reply</h2>
  <p style="margin:0 0 6px 0"><b>From:</b> {from_addr}</p>
  {f'<p style="margin:0 0 6px 0"><b>Lead:</b> {lead_name or lead_email}</p>' if (lead_name or lead_email) else ""}
  <p style="margin:0 0 6px 0"><b>Subject:</b> {original_subject}</p>
  {f'<p style="margin:0 0 6px 0"><b>Run:</b> <code>{run_id}</code></p>' if run_id else ""}
  <hr style="border:none;border-top:1px solid #e2e8f0;margin:16px 0">
  <pre style="white-space:pre-wrap;background:#f8fafc;padding:12px;border-radius:8px;font-family:ui-monospace,monospace;font-size:13px;color:#334155">{snippet[:2000]}</pre>
  <p style="margin:16px 0 0 0;color:#64748b;font-size:12px">
    Sent automatically by imap-poll.py via Resend (not Hostinger SMTP, to
    preserve mailbox quota). The originating sequence run has been
    paused so no further emails fire to this prospect.
  </p>
</div>"""
    payload = {
        "from":    "Reply Alert <alerts@hi.aureonglobal.de>",
        "to":      [to_addr],
        "reply_to": from_addr,  # let the operator reply directly to the prospect
        "subject": subj[:200],
        "html":    body_html,
        "headers": {"X-LES-Alert": "reply-alert"},
        "tags":    [{"name": "kind", "value": "reply_alert"}],
    }
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=_json.dumps(payload).encode(),
        method="POST",
        # Cloudflare bot protection (error 1010) blocks requests with no
        # User-Agent. Mimic the same header daily-report.py uses.
        headers={"Authorization": f"Bearer {resend_key}",
                 "Content-Type": "application/json",
                 "User-Agent": "local-email-stack imap-poll/1.0"},
    )
    try:
        urllib.request.urlopen(req, timeout=15)
        return True
    except urllib.error.HTTPError as e:
        print(f"  ! alert send failed: HTTP {e.code} {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"  ! alert send failed: {e}")
        return False


def classify(msg) -> str:
    sender = parseaddr(msg.get("From", ""))[1].lower()
    subject = msg.get("Subject", "") or ""
    # Our own outbound alert emails — never re-process them.
    if msg.get("X-LES-Alert") or subject.startswith(ALERT_SUBJECT_PREFIX):
        return "self_alert"
    if msg.get("Feedback-Type") or COMPLAINT_FROM.search(sender):
        return "complaint"
    if BOUNCE_FROM.search(sender) or BOUNCE_SUBJ.search(subject):
        return "bounce"
    if msg.get("X-Failed-Recipients"):
        return "bounce"
    if EXCLUDE_FROM.search(sender):
        return "unrelated"               # legal / internal — never a prospect reply
    if msg.get("In-Reply-To") or msg.get("References"):
        if NOISE_SUBJ.search(subject):
            return "unrelated"           # account / transactional, not a cold reply
        return "reply"
    return "unrelated"


def extract_snippet(msg, max_chars: int = 1500) -> str:
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    body = part.get_payload(decode=True)
                    if body:
                        return body.decode(part.get_content_charset() or "utf-8", "ignore")[:max_chars]
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True)
                    if body:
                        # crude strip-tags
                        text = re.sub(r"<[^>]+>", " ", body.decode(part.get_content_charset() or "utf-8", "ignore"))
                        return re.sub(r"\s+", " ", text)[:max_chars]
        else:
            body = msg.get_payload(decode=True) or b""
            return body.decode(msg.get_content_charset() or "utf-8", "ignore")[:max_chars]
    except Exception as e:
        return f"(parse error: {e})"
    return ""


# ─── Supabase access ────────────────────────────────────────────────────────

class Supa:
    def __init__(self, url: str, key: str):
        self.base = f"{url}/rest/v1"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self.client = httpx.Client(headers=self.headers, timeout=20)

    def find_run_by_message_id(self, refs: list[str]) -> tuple[str | None, str | None, str | None]:
        """Given list of candidate Message-IDs from In-Reply-To/References, find the matching
        send_log row (and therefore the run). Returns (run_id, resend_id, send_log_id)."""
        if not refs:
            return None, None, None
        for mid in refs:
            r = self.client.get(f"{self.base}/send_log",
                                params={"message_id": f"eq.{mid}", "select": "id,run_id,resend_id"})
            if r.status_code == 200 and r.json():
                row = r.json()[0]
                return row.get("run_id"), row.get("resend_id"), row.get("id")
        return None, None, None

    def find_send_by_recipient_subject(self, recipient: str, subject: str) -> tuple[str | None, str | None, str | None]:
        """Fallback when In-Reply-To matching fails (Resend overrides our Message-ID
        with their SES one). Strip 'Re:'/'Fwd:' from the inbound subject and look for
        the most recent send_log row where to_addr matches and subject is contained."""
        if not recipient or not subject:
            return None, None, None
        stripped = re.sub(r"^(?:re|fwd|fw|aw|wg)\s*:\s*", "", subject, flags=re.I).strip()
        if len(stripped) < 6:  # too short to be reliable
            return None, None, None
        # ilike with wildcards on either side — handles trailing/leading spaces in subjects.
        pattern = f"*{stripped[:80]}*"
        r = self.client.get(
            f"{self.base}/send_log",
            params={
                "to_addr": f"eq.{recipient.lower()}",
                "subject": f"ilike.{pattern}",
                "select":  "id,run_id,resend_id",
                "order":   "sent_at.desc",
                "limit":   "1",
            },
        )
        if r.status_code == 200 and r.json():
            row = r.json()[0]
            return row.get("run_id"), row.get("resend_id"), row.get("id")
        return None, None, None

    @staticmethod
    def _w(r, what: str):
        """Raise on a failed WRITE. Every write here used to discard the Response,
        so a 4xx PATCH looked like success and stats['errors'] stayed 0 — that is
        how reply-pauses went missing (chad@soldbymarkz.com replied 2026-06-16,
        was never paused, and got step 2 on 06-19 and step 3 on 07-03). Raising
        aborts this message before it is flagged \\Seen, so the next poll retries
        it. Reads still branch on status_code by hand — only writes raise."""
        if r.status_code >= 400:
            raise RuntimeError(f"{what} failed: {r.status_code} {r.text[:200]}")
        return r

    def insert_reply(self, row: dict) -> None:
        self._w(self.client.post(f"{self.base}/replies", json=row), "insert_reply")

    def already_have(self, message_id: str) -> bool:
        if not message_id:
            return False
        r = self.client.get(f"{self.base}/replies",
                            params={"raw_headers->>Message-ID": f"eq.{message_id}", "select": "id"})
        return r.status_code == 200 and bool(r.json())

    def mark_send_replied(self, send_log_id: str) -> None:
        """Set send_log.replied=true on the outbound row this reply answered."""
        self._w(self.client.patch(f"{self.base}/send_log",
                          params={"id": f"eq.{send_log_id}"},
                          json={"replied": True}), "mark_send_replied")

    def mark_send_bounced(self, send_log_id: str) -> None:
        self._w(self.client.patch(f"{self.base}/send_log",
                          params={"id": f"eq.{send_log_id}"},
                          json={"bounced": True, "delivered": False}), "mark_send_bounced")

    def mark_send_complained(self, send_log_id: str) -> None:
        self._w(self.client.patch(f"{self.base}/send_log",
                          params={"id": f"eq.{send_log_id}"},
                          json={"complained": True}), "mark_send_complained")

    def pause_run(self, run_id: str, reason: str) -> None:
        self._w(self.client.patch(f"{self.base}/runs",
                          params={"id": f"eq.{run_id}"},
                          json={"status": f"paused_{reason}"}), "pause_run")

    def pause_runs_for_email(self, email: str) -> int:
        """Robust reply-stop: pause EVERY still-queued run for the prospect at
        `email`, even when In-Reply-To / subject matching could not resolve the
        run_id (Resend rewrites our Message-ID, so header matching often fails).
        The reply's From address IS the prospect's email, so this reliably halts
        the sequence. Returns the number of runs paused."""
        if not email:
            return 0
        ps = self.client.get(f"{self.base}/prospects",
                             params={"email": f"eq.{email.lower()}", "select": "id"})
        if ps.status_code != 200 or not ps.json():
            return 0
        n = 0
        for p in ps.json():
            qr = self.client.get(f"{self.base}/runs",
                                 params={"prospect_id": f"eq.{p['id']}",
                                         "status": "eq.queued", "select": "id"})
            for run in (qr.json() if qr.status_code == 200 else []):
                self._w(self.client.patch(f"{self.base}/runs",
                                 params={"id": f"eq.{run['id']}"},
                                 json={"status": "paused_replied"}), "pause_runs_for_email")
                n += 1
        return n

    def is_known_prospect(self, email: str) -> bool:
        """True if `email` exists in our prospects table. Used to gate genuine cold
        replies from inbox noise (vendor marketing, transactional, mis-threaded mail)."""
        if not email:
            return False
        r = self.client.get(f"{self.base}/prospects",
                            params={"email": f"eq.{email.lower()}", "select": "id", "limit": "1"})
        return r.status_code == 200 and bool(r.json())

    def resolve_profile_slug(self, *, from_addr: str, to_addr: str) -> str | None:
        """Attribute a reply to a client profile so per-client reports can count it.
        Primary: the prospect row's profile_slug (authoritative). Fallback: match the
        root of our receiving address (to_addr = persona@sub.<root>.tld) to a profile's
        sending domains. Fixes the replies.profile_slug=NULL gap (2026-06-11 audit)."""
        fa = (from_addr or "").lower()
        if fa:
            r = self.client.get(f"{self.base}/prospects",
                                params={"email": f"eq.{fa}", "select": "profile_slug", "limit": "1"})
            if r.status_code == 200 and r.json():
                slug = r.json()[0].get("profile_slug")
                if slug:
                    return slug
        # Fallback: our receiving subdomain -> owning profile.
        ta = (to_addr or "").lower()
        sub = ta.split("@", 1)[1] if "@" in ta else ""
        if sub:
            try:
                from profile_lib import list_profiles  # local import to avoid cycle
                for prof in list_profiles():
                    for d in (prof.get("relay") or {}).get("from_domains", []):
                        if (d.get("domain") or "").lower() == sub:
                            return prof.get("slug")
            except Exception:
                pass
        return None

    def unsubscribe_email(self, email: str) -> int:
        """Honor an opt-out: set prospects.unsubscribed=true and cancel every
        run for this address, so NO further email can fire. Returns count."""
        if not email:
            return 0
        email = email.lower()
        ps = self.client.get(f"{self.base}/prospects",
                             params={"email": f"eq.{email}", "select": "id"})
        rows = ps.json() if ps.status_code == 200 else []
        # Cross-address opt-out: people often reply "unsubscribe" from a personal address
        # while we emailed a role inbox (info@/hello@) at the same company. If the exact
        # address is not a prospect, fall back to the company DOMAIN — but never for free
        # providers (would opt out everyone on gmail/outlook/etc).
        if not rows:
            dom = email.split("@", 1)[1] if "@" in email else ""
            if dom and dom not in _FREE_EMAIL_DOMAINS:
                ds = self.client.get(f"{self.base}/prospects",
                                     params={"email": f"ilike.*@{dom}", "select": "id"})
                rows = ds.json() if ds.status_code == 200 else []
        if not rows:
            return 0
        n = 0
        for p in rows:
            # Compliance path (CAN-SPAM / GDPR): a silent 4xx here meant someone
            # who asked to opt out stayed subscribed and kept getting mail. Raise.
            self._w(self.client.patch(f"{self.base}/prospects",
                             params={"id": f"eq.{p['id']}"},
                             json={"unsubscribed": True}), "unsubscribe_prospect")
            runs = self.client.get(f"{self.base}/runs",
                                   params={"prospect_id": f"eq.{p['id']}",
                                           "status": "in.(queued,paused_replied,paused_bounced)",
                                           "select": "id"})
            for run in (runs.json() if runs.status_code == 200 else []):
                self._w(self.client.patch(f"{self.base}/runs", params={"id": f"eq.{run['id']}"},
                                 json={"status": "cancelled"}), "unsubscribe_cancel_run")
            n += 1
        return n


# ─── IMAP loop ──────────────────────────────────────────────────────────────

def split_refs(value: str) -> list[str]:
    if not value:
        return []
    return [s.strip() for s in re.findall(r"<[^>]+>", value)]


def _extract_original_recipient(msg) -> str | None:
    """For a bounce DSN, the original recipient is usually in either an
    `X-Failed-Recipients` header, the `Original-Recipient` line inside the
    delivery-status report, or quoted in the body. Best-effort parse."""
    failed = msg.get("X-Failed-Recipients") or msg.get("Original-Recipient")
    if failed:
        m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", failed)
        if m: return m.group(0).lower()
    try:
        body = extract_snippet(msg, max_chars=5000)
        for line in body.splitlines():
            if "to:" in line.lower() or "recipient" in line.lower() or "<" in line:
                m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", line)
                if m and "aureonglobal.de" not in m.group(0).lower():
                    return m.group(0).lower()
    except Exception:
        pass
    return None


def one_pass(verbose: bool = True) -> dict:
    user, password = hostinger_creds()
    url, key = supabase_creds()
    supa = Supa(url, key)
    # Reload hostinger env for SMTP credentials reused by reply-alert sender
    env = load_env(REPO_ROOT / "sequences" / "hostinger.env")

    stats = {"processed": 0, "reply": 0, "bounce": 0, "complaint": 0, "unrelated": 0,
             "matched_to_run": 0, "runs_paused": 0, "errors": 0}

    # Walk both INBOX and INBOX.Junk — cold-mail replies often get filtered
    # into Junk by Hostinger before a human sees it. We scan messages received
    # in the last SCAN_DAYS days (not just UNSEEN) so that a reply the operator
    # already opened in webmail still gets picked up. Duplicate inserts are
    # prevented by the Message-ID dedupe in supa.already_have().
    FOLDERS   = ["INBOX", "INBOX.Junk"]
    SCAN_DAYS = 14

    since = (dt.datetime.utcnow() - dt.timedelta(days=SCAN_DAYS)).strftime("%d-%b-%Y")

    imap = imaplib.IMAP4_SSL("imap.hostinger.com", 993)
    try:
        imap.login(user, password)
        for folder in FOLDERS:
            sel_typ, _ = imap.select(folder, readonly=False)
            if sel_typ != "OK":
                if verbose: print(f"  (skip folder {folder}: {sel_typ})")
                continue
            typ, data = imap.search(None, "SINCE", since)
            if typ != "OK":
                continue
            nums = data[0].split() if data and data[0] else []
            if verbose and nums:
                print(f"  -- {folder}: {len(nums)} unseen --")
            for num in nums:
                try:
                    typ, msg_data = imap.fetch(num, "(RFC822)")
                    if typ != "OK" or not msg_data or not msg_data[0]:
                        continue
                    raw = msg_data[0][1]
                    msg = email.message_from_bytes(raw, policy=email.policy.default)
                    stats["processed"] += 1
                    klass = classify(msg)
                    stats[klass] = stats.get(klass, 0) + 1

                    from_addr = parseaddr(msg.get("From", ""))[1] or "(unknown)"
                    to_addr   = parseaddr(msg.get("To", ""))[1] or user
                    subject   = msg.get("Subject", "") or ""
                    msg_id    = msg.get("Message-ID", "")
                    in_reply  = split_refs(msg.get("In-Reply-To", ""))
                    references = split_refs(msg.get("References", ""))

                    if supa.already_have(msg_id):
                        if verbose: print(f"  ↩ skip (already recorded): {msg_id}")
                        imap.store(num, "+FLAGS", "\\Seen")
                        continue

                    # First try In-Reply-To/References (precise). Resend tends to
                    # override our Message-ID with the SES one on the wire, so
                    # this often fails — fall back to recipient + subject.
                    # For bounces the sender is mailer-daemon, so the subject
                    # fallback uses the *original recipient* address (parsed
                    # from the bounce body's "X-Failed-Recipients" or the
                    # quoted body), which our send_log already keys on via to_addr.
                    run_id, resend_id, send_log_id = supa.find_run_by_message_id(in_reply + references)
                    match_via = "header"
                    if not send_log_id and klass in ("reply", "bounce", "complaint"):
                        candidate_recipient = from_addr if klass == "reply" else _extract_original_recipient(msg) or from_addr
                        run_id, resend_id, send_log_id = supa.find_send_by_recipient_subject(candidate_recipient, subject)
                        if send_log_id: match_via = "subject"
                    # Reporting + safety gate: a threaded "reply" matching none of our
                    # sends and not from a known prospect is inbox noise (vendor marketing,
                    # transactional, mis-threaded), never a cold reply. Downgrade it so it
                    # cannot pause a run, alert the operator, or trigger an auto-draft.
                    if klass == "reply" and not send_log_id and not supa.is_known_prospect(from_addr):
                        klass = "unrelated"
                    # Symmetric UPGRADE: a message with no In-Reply-To/References lands as
                    # "unrelated" even when it is a genuine prospect reply (some clients drop
                    # threading headers, or the prospect starts a fresh mail to our reply-to).
                    # If the sender IS a known prospect and it is not bounce/complaint/self/
                    # excluded (those were already decided in classify, which applies the
                    # laso.finance/own-infra EXCLUDE gate), treat it as a real reply.
                    elif (klass == "unrelated" and not EXCLUDE_FROM.search(from_addr.lower())
                          and not NOISE_SUBJ.search(subject) and supa.is_known_prospect(from_addr)):
                        klass = "reply"
                        # try the recipient+subject fallback now that we know it's a reply
                        if not send_log_id:
                            run_id, resend_id, send_log_id = supa.find_send_by_recipient_subject(from_addr, subject)
                            if send_log_id: match_via = "subject"
                    if run_id:
                        stats["matched_to_run"] += 1

                    snippet = extract_snippet(msg)

                    # The `replies` row is now inserted LAST, just before \Seen —
                    # see the COMMIT MARKER block below. Its Message-ID is the
                    # already_have() dedupe key, so writing it here made any later
                    # failure permanent: the next poll matched the key, skipped the
                    # message, and the reply-pause was never retried.

                    if send_log_id:
                        if   klass == "reply":     supa.mark_send_replied(send_log_id)
                        elif klass == "bounce":    supa.mark_send_bounced(send_log_id)
                        elif klass == "complaint": supa.mark_send_complained(send_log_id)
                    if klass == "reply":
                        # Robust reply-stop: pause every queued run for this
                        # sender. Does NOT depend on resolving run_id (header /
                        # subject matching is unreliable because Resend rewrites
                        # Message-IDs) — this is what guarantees a reply halts
                        # the sequence. Falls back to the matched run_id only if
                        # the email lookup finds no prospect (e.g. alias reply).
                        paused = supa.pause_runs_for_email(from_addr)
                        if run_id and paused == 0:
                            supa.pause_run(run_id, "replied"); paused = 1
                        stats["runs_paused"] += paused
                        # Global do-not-contact: a prospect who replied is never
                        # cold-emailed again by ANY profile, including a future
                        # re-scrape into another brand's pool.
                        try:
                            suppress.add_email(from_addr, "replied")
                        except Exception as _se:
                            print(f"  ! suppress add failed for {from_addr}: {_se}")
                        # Honor opt-out requests. Check only the TOP of the reply
                        # (+ subject) so our own quoted unsubscribe footer can not
                        # self-trigger. A genuine "unsubscribe/stop/remove me" ->
                        # suppress the prospect + cancel all runs (compliance).
                        if is_optout_reply(top_reply_text(snippet), subject):
                            u = supa.unsubscribe_email(from_addr)
                            if u:
                                stats["unsubscribed"] = stats.get("unsubscribed", 0) + u
                                if verbose: print(f"  ⊘ unsubscribed {from_addr} (opt-out reply)")
                            # Downgrade class so the row is NOT picked up as a prospect
                            # reply: reply-autodraft (class=eq.reply) would draft an answer
                            # and pop the operator to approve a reply to someone who just
                            # asked to be removed, and forward-replies would forward it to
                            # the client as a lead. The opt-out is already honored above.
                            klass = "optout"
                    elif klass == "bounce" and run_id:
                        supa.pause_run(run_id, "bounced")
                        stats["runs_paused"] += 1
                    # Opt-out can arrive on a NON-reply class too: a phone reply that drops
                    # the In-Reply-To header is classed 'unrelated', so the reply-branch
                    # opt-out check above never runs. An unsubscribe is ALWAYS honored, by
                    # exact address or the company domain (unsubscribe_email handles both).
                    if klass not in ("reply", "bounce", "complaint", "self_alert", "optout") and \
                       is_optout_reply(top_reply_text(snippet), subject):
                        u = supa.unsubscribe_email(from_addr)
                        if u:
                            stats["unsubscribed"] = stats.get("unsubscribed", 0) + u
                            if verbose:
                                print(f"  ⊘ unsubscribed {from_addr} (opt-out, class={klass})")

                    # Send internal alert email to info@aureonglobal.de for real
                    # prospect replies (not bounces / complaints). Lets the operator
                    # see in their inbox + get any client-side rules to trigger.
                    if klass == "reply":
                        try:
                            sent_alert = send_reply_alert(
                                env,
                                from_addr=from_addr,
                                original_subject=subject,
                                snippet=snippet,
                                lead_email=from_addr,
                                lead_name=None,
                                run_id=run_id,
                            )
                            if sent_alert:
                                stats.setdefault("alerts_sent", 0)
                                stats["alerts_sent"] += 1
                        except Exception as e:
                            if verbose: print(f"  ! reply-alert error: {e}")

                    # COMMIT MARKER — must stay the LAST write before \Seen.
                    # mark_send_replied / pause_runs_for_email / unsubscribe_email
                    # now raise on a 4xx (Supa._w), which aborts this message
                    # before it is flagged Seen, so the next poll replays it whole.
                    # Those writes are idempotent and already_have() stays False
                    # until this row lands, so the replay actually re-runs them.
                    supa.insert_reply({
                        "run_id":       run_id,
                        "profile_slug": supa.resolve_profile_slug(from_addr=from_addr, to_addr=to_addr),
                        "from_addr":    from_addr,
                        "to_addr":      to_addr,
                        "subject":      subject[:500],
                        "class":        klass,
                        "body_snippet": snippet,
                        "raw_headers":  {"Message-ID":  msg_id,
                                         "In-Reply-To": msg.get("In-Reply-To", ""),
                                         "References":  msg.get("References", ""),
                                         "Folder":      folder,
                                         "Matched-Via": match_via if send_log_id else "none"},
                    })

                    imap.store(num, "+FLAGS", "\\Seen")
                    if verbose:
                        tag = "run" if run_id else ("send" if send_log_id else "no")
                        print(f"  ✓ [{folder:11}] {klass:9} from {from_addr[:34]:34}  matched={tag} via={match_via if send_log_id else '-'}")
                except Exception as e:
                    stats["errors"] += 1
                    if verbose: print(f"  ! error on msg {num} in {folder}: {e}")
    finally:
        try: imap.logout()
        except Exception: pass
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once")
    p_loop = sub.add_parser("loop")
    p_loop.add_argument("--interval", type=int, default=300)
    args = ap.parse_args()

    if args.cmd == "once":
        stats = one_pass()
        print(json.dumps(stats, indent=2))
        return 0
    while True:
        try:
            stats = one_pass()
            print(f"[{dt.datetime.now():%H:%M:%S}] {stats}")
        except Exception as e:
            print(f"[{dt.datetime.now():%H:%M:%S}] error: {e}")
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
