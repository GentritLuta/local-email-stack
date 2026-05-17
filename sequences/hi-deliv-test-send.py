"""hi-deliv-test-send.py — single-message, maximum-hygiene direct-to-MX sender.

This is the best you can do without a real relay (Resend / SES / Postal). It applies
every content + header best practice that doesn't require infrastructure you don't
have. It is NOT a substitute for a verified sender — see DELIVERABILITY.md for that.

What it does right:
  - Proper Message-ID rooted at the sender domain
  - Date header with full RFC-2822 timezone
  - List-Unsubscribe + List-Unsubscribe-Post (RFC 8058 one-click)
  - Reply-To aligned with From
  - Plain text + minimal HTML alternative
  - X-Mailer that doesn't scream "spam tool"
  - HELO/EHLO uses the sender's apex domain (not the host's name)
  - STARTTLS if MX offers it
  - One recipient per SMTP transaction (no BCC fanouts)
  - Single-attempt with informative SMTP-response capture

What still goes wrong (these need actual infrastructure):
  - SPF will fail — your home IP isn't authorized to send for the From domain
  - DKIM is absent — no cryptographic signature
  - DMARC alignment fails because of the above
  - Sending IP is on residential ranges (Spamhaus PBL)
  Expected outcome: most providers route to spam folder; some (web.de, Outlook)
  may accept and inbox a one-shot test; some (Hostinger MXes that already
  rate-limited us) will time out.

Usage:
    py hi-deliv-test-send.py --to <addr> [--from-name "Bernhard"] [--from "bernhard@mail.insaneaiautomation.xyz"] [--subject "..."] [--body-file path]

If --body-file is omitted, sends a clean inbox-placement test email.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import socket
import smtplib
import ssl
import sys
import time
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

try:
    import dns.resolver
    HAVE_DNS = True
except ImportError:
    HAVE_DNS = False


DEFAULT_BODY_PLAIN = """hi,

quick test from bernhard — just verifying my outbound mail reaches your inbox cleanly. no action needed.

if you see this in spam, please drag it to inbox once if you don't mind. helps with reputation.

bernhard
"""


def resolve_mx(domain: str) -> list[str]:
    if HAVE_DNS:
        try:
            answers = dns.resolver.resolve(domain, "MX")
            return [str(r.exchange).rstrip(".") for r in sorted(answers, key=lambda x: x.preference)]
        except Exception as e:
            print(f"  ! dnspython failed: {e}")
    import subprocess
    out = subprocess.run(["nslookup", "-type=mx", domain], capture_output=True, text=True, timeout=10)
    hosts = []
    for line in out.stdout.splitlines():
        if "mail exchanger" in line.lower():
            parts = line.split("=")
            if len(parts) >= 2:
                hosts.append(parts[-1].strip().rstrip("."))
    return hosts


def build_message(from_name: str, from_addr: str, to_addr: str,
                  subject: str, body_plain: str, list_unsub_mailto: str) -> tuple[bytes, str]:
    """Build the MIME message and return (raw_bytes, message_id)."""
    sender_domain = from_addr.split("@", 1)[1]
    msg_id = f"<{uuid.uuid4().hex}.{int(time.time())}@{sender_domain}>"

    msg = MIMEMultipart("alternative")
    msg["From"] = email.utils.formataddr((from_name, from_addr))
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Reply-To"] = from_addr
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = msg_id
    msg["MIME-Version"] = "1.0"
    msg["X-Mailer"] = "Local Email Stack 0.4"
    # RFC 2369 list management + RFC 8058 one-click unsubscribe support
    msg["List-Unsubscribe"] = f"<mailto:{list_unsub_mailto}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    # Auto-Submitted is the IETF way to tag automated mail truthfully — neutral
    # for transactional/test sends, harmful to claim 'no' on bulk marketing.

    # HTML alt: minimal — just <p> wrap. Mirrors plain text exactly.
    html_paragraphs = "".join(f"<p>{esc_html(p)}</p>" for p in body_plain.strip().split("\n\n"))
    html_doc = (
        "<!doctype html><html><head><meta charset='utf-8'></head><body style='"
        "font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;"
        "line-height:1.55;color:#1f2937;max-width:600px'>"
        + html_paragraphs +
        "</body></html>"
    )
    msg.attach(MIMEText(body_plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_doc, "html", "utf-8"))
    return msg.as_bytes(), msg_id


def esc_html(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def send_one(raw: bytes, from_addr: str, to_addr: str, helo_name: str) -> dict:
    """Attempt SMTP delivery direct to the recipient's MX. Return a structured report."""
    domain = to_addr.split("@", 1)[1]
    report = {
        "to": to_addr, "from": from_addr, "helo": helo_name,
        "mx_hosts": [], "attempts": [], "delivered": False, "final_mx": None,
        "final_response": None, "started_at": dt.datetime.now().isoformat(),
    }
    hosts = resolve_mx(domain)
    report["mx_hosts"] = hosts
    if not hosts:
        report["attempts"].append({"mx": None, "phase": "mx_lookup", "error": "no MX records"})
        return report
    for mx in hosts:
        att = {"mx": mx, "phase": None, "starttls": False, "response_lines": []}
        try:
            with smtplib.SMTP(mx, 25, timeout=20) as s:
                # Capture the server greeting
                # (smtplib already did EHLO during construction implicitly? no — we control it)
                att["phase"] = "ehlo"
                code, msg = s.ehlo(helo_name)
                att["response_lines"].append(f"EHLO -> {code} {msg.decode(errors='ignore').strip()[:200]}")
                # STARTTLS if available
                if s.has_extn("starttls"):
                    att["phase"] = "starttls"
                    try:
                        s.starttls(context=ssl.create_default_context())
                        s.ehlo(helo_name)
                        att["starttls"] = True
                    except Exception as e:
                        att["response_lines"].append(f"STARTTLS failed: {e} (continuing plaintext)")
                att["phase"] = "mail_from"
                s.mail(from_addr)
                att["phase"] = "rcpt_to"
                code, msg = s.rcpt(to_addr)
                att["response_lines"].append(f"RCPT TO -> {code} {msg.decode(errors='ignore').strip()[:200]}")
                if code >= 400:
                    att["error"] = f"RCPT rejected {code}"
                    report["attempts"].append(att)
                    continue
                att["phase"] = "data"
                code, msg = s.data(raw)
                final = f"{code} {msg.decode(errors='ignore').strip()[:300]}"
                att["response_lines"].append(f"DATA -> {final}")
                if code < 400:
                    report["delivered"] = True
                    report["final_mx"] = mx
                    report["final_response"] = final
                    report["attempts"].append(att)
                    return report
                att["error"] = f"DATA rejected {code}"
                report["attempts"].append(att)
        except smtplib.SMTPException as e:
            att["error"] = f"smtp exception: {e}"
            report["attempts"].append(att)
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            att["error"] = f"network error: {e}"
            report["attempts"].append(att)
    return report


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--from-addr", default="bernhard@mail.insaneaiautomation.xyz")
    ap.add_argument("--from-name", default="Bernhard")
    ap.add_argument("--subject", default="quick test")
    ap.add_argument("--body-file", default=None)
    ap.add_argument("--helo", default=None, help="EHLO/HELO name (default: from-addr's domain)")
    ap.add_argument("--list-unsub-mailto", default=None,
                    help="address used for List-Unsubscribe (default: from-addr)")
    ap.add_argument("--save-eml", default=None, help="also save the raw .eml to this path")
    args = ap.parse_args()

    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else DEFAULT_BODY_PLAIN
    helo = args.helo or args.from_addr.split("@", 1)[1]
    list_unsub = args.list_unsub_mailto or args.from_addr

    raw, msg_id = build_message(args.from_name, args.from_addr, args.to, args.subject, body, list_unsub)
    print(f"\n=== sending ===")
    print(f"  from:   {args.from_name} <{args.from_addr}>")
    print(f"  to:     {args.to}")
    print(f"  helo:   {helo}")
    print(f"  msgid:  {msg_id}")
    print(f"  bytes:  {len(raw)}\n")

    if args.save_eml:
        Path(args.save_eml).write_bytes(raw)
        print(f"  saved → {args.save_eml}")

    report = send_one(raw, args.from_addr, args.to, helo)
    print(f"\n=== report ===")
    print(json.dumps(report, indent=2, default=str))
    if report["delivered"]:
        print(f"\n[ok] SMTP accepted: {report['final_response']}")
        print("[note] Acceptance ≠ inbox. Verify by checking the recipient's INBOX AND SPAM folder.")
        return 0
    else:
        print("\n[fail] no MX accepted the message")
        return 2


if __name__ == "__main__":
    sys.exit(main())
