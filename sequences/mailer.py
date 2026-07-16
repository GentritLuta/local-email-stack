# -*- coding: utf-8 -*-
"""mailer.py — one place to send operator/client email in the stack.

Resend over HTTPS is the PRIMARY transport, because the production VPS blocks the
outbound SMTP ports (25/465/587); Hostinger SMTP is a laptop-only fallback. Every
notification / handoff sender should call send() instead of using smtplib directly,
so a port-blocked box can never silently drop mail again.

    from mailer import send
    send(to="info@aureonglobal.de", subject="...", html="...", text="...")

The root aureonglobal.de is NOT verified on Resend (only the subdomains), so `from`
defaults to info@send.aureonglobal.de; set reply_to="info@aureonglobal.de" when a
human should reply to the operator inbox.
"""
from __future__ import annotations
import base64, json, ssl, smtplib, urllib.request
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

_ENV: dict[str, str] = {}
_ENV_PATH = Path(__file__).resolve().parent / "hostinger.env"
if _ENV_PATH.exists():
    for _l in _ENV_PATH.read_text(encoding="utf-8").splitlines():
        if "=" in _l and not _l.strip().startswith("#"):
            _k, _v = _l.split("=", 1)
            _ENV[_k.strip()] = _v.strip()

DEFAULT_FROM = "Aureon Global <info@send.aureonglobal.de>"
OPERATOR_ADDR = "info@aureonglobal.de"


def _as_list(x) -> list:
    if not x:
        return []
    return [x] if isinstance(x, str) else list(x)


def send(*, to, subject, html=None, text=None, from_addr=DEFAULT_FROM,
         reply_to=None, cc=None, bcc=None, attachments=None) -> bool:
    """Send one email. Resend (HTTPS) primary, Hostinger SMTP fallback. Returns True if sent.

    to / cc / bcc : str or list of addresses.
    attachments   : list of (filename, bytes | str-path | Path).
    """
    to, cc, bcc = _as_list(to), _as_list(cc), _as_list(bcc)
    atts = []
    for fn, data in (attachments or []):
        if isinstance(data, (str, Path)):
            data = Path(data).read_bytes()
        atts.append((fn, data))

    key = (_ENV.get("RESEND_NEW_ACCOUNT_API_KEY")
           or _ENV.get("RESEND_FULL_ACCESS_API_KEY")
           or _ENV.get("RESEND_API_KEY"))
    if key:
        payload: dict = {"from": from_addr, "to": to, "subject": subject}
        if html:
            payload["html"] = html
        if text:
            payload["text"] = text
        if reply_to:
            payload["reply_to"] = reply_to
        if cc:
            payload["cc"] = cc
        if bcc:
            payload["bcc"] = bcc
        if atts:
            payload["attachments"] = [{"filename": fn, "content": base64.b64encode(d).decode()}
                                      for fn, d in atts]
        try:
            req = urllib.request.Request(
                "https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                         "User-Agent": "aureon-mailer/1.0"})
            with urllib.request.urlopen(req, timeout=30) as r:
                if r.status in (200, 201):
                    return True
            print("    ! Resend send did not return 200/201")
        except Exception as e:
            print(f"    ! Resend send error: {e}")

    # Fallback: Hostinger SMTP (works on the laptop; blocked on the VPS).
    user = _ENV.get("SMTP_USER") or OPERATOR_ADDR
    pw = _ENV.get("SMTP_PASS")
    if not pw:
        print("    (no SMTP_PASS and Resend unavailable — email not sent)")
        return False
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    if reply_to:
        msg["Reply-To"] = reply_to
    alt = MIMEMultipart("alternative")
    if text:
        alt.attach(MIMEText(text, "plain", "utf-8"))
    if html:
        alt.attach(MIMEText(html, "html", "utf-8"))
    msg.attach(alt)
    for fn, d in atts:
        part = MIMEApplication(d)
        part.add_header("Content-Disposition", "attachment", filename=fn)
        msg.attach(part)
    try:
        with smtplib.SMTP_SSL("smtp.hostinger.com", 465, context=ssl.create_default_context()) as s:
            s.login(user, pw)
            s.sendmail(user, to + cc + bcc, msg.as_string())
        return True
    except Exception as e:
        print(f"    ! SMTP send failed: {e}")
        return False
