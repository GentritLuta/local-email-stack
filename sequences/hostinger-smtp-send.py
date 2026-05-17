"""hostinger-smtp-send.py — authenticated SMTP send via Hostinger.

Reads credentials from sequences/hostinger.env (or env vars). Sends ONE message
per invocation with full header hygiene, using implicit-TLS SMTPS on port 465.

This route bypasses the residential-IP problem entirely: outbound goes from
Hostinger's mail servers, with proper PTR, SPF, DKIM, and DMARC for any
domain Hostinger hosts (including aureonglobal.de).

Usage:
    py hostinger-smtp-send.py --variants <variants.json> --variant-n 1 --to g-luta@web.de
    py hostinger-smtp-send.py --plain-body --subject "..." --body "..." --to <addr>

Auth env file (sequences/hostinger.env), gitignored:
    SMTP_USER=info@aureonglobal.de
    SMTP_PASS=<password>
    SMTP_HOST=smtp.hostinger.com
    SMTP_PORT=465
    FROM_NAME=Aureon
    FROM_ADDR=info@aureonglobal.de
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import os
import smtplib
import ssl
import sys
import time
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path


def load_env(env_path: Path) -> dict:
    env = dict(os.environ)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def build_message(from_name: str, from_addr: str, to_addr: str,
                  subject: str, body_plain: str, list_unsub_mailto: str) -> tuple[bytes, str]:
    sender_domain = from_addr.split("@", 1)[1]
    msg_id = f"<{uuid.uuid4().hex}.{int(time.time())}@{sender_domain}>"
    msg = MIMEMultipart("alternative")
    msg["From"]                  = email.utils.formataddr((from_name, from_addr))
    msg["To"]                    = to_addr
    msg["Subject"]               = subject
    msg["Reply-To"]              = from_addr
    msg["Date"]                  = email.utils.formatdate(localtime=True)
    msg["Message-ID"]            = msg_id
    msg["MIME-Version"]          = "1.0"
    msg["X-Mailer"]              = "Local Email Stack 0.4"
    msg["List-Unsubscribe"]      = f"<mailto:{list_unsub_mailto}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    html_paras = "".join(f"<p>{esc(p)}</p>" for p in body_plain.strip().split("\n\n"))
    html_doc = (
        "<!doctype html><html><head><meta charset='utf-8'></head><body style='"
        "font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;"
        "line-height:1.55;color:#1f2937;max-width:600px'>" + html_paras + "</body></html>"
    )
    msg.attach(MIMEText(body_plain, "plain", "utf-8"))
    msg.attach(MIMEText(html_doc,  "html",  "utf-8"))
    return msg.as_bytes(), msg_id


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_via_smtps(host: str, port: int, user: str, password: str,
                   raw: bytes, from_addr: str, to_addr: str) -> dict:
    """SMTPS = SMTP over implicit TLS (port 465). For Hostinger this is the
    recommended path (port 587 with STARTTLS also works but they prefer 465)."""
    report = {"to": to_addr, "from": from_addr, "host": host, "port": port,
              "delivered": False, "phase": None, "smtp_response": None,
              "started_at": dt.datetime.now().isoformat()}
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, timeout=30, context=context) as s:
            report["phase"] = "ehlo"
            code, msg = s.ehlo()
            report.setdefault("ehlo", []).append(f"{code} {msg.decode(errors='ignore').strip()[:200]}")
            report["phase"] = "login"
            s.login(user, password)
            report["phase"] = "mail_from"
            s.mail(from_addr)
            report["phase"] = "rcpt_to"
            code, msg = s.rcpt(to_addr)
            report.setdefault("rcpt", []).append(f"{code} {msg.decode(errors='ignore').strip()[:200]}")
            if code >= 400:
                report["error"] = f"RCPT rejected: {code}"
                return report
            report["phase"] = "data"
            code, msg = s.data(raw)
            final = f"{code} {msg.decode(errors='ignore').strip()[:300]}"
            report["smtp_response"] = final
            if code < 400:
                report["delivered"] = True
                report["phase"] = "delivered"
            else:
                report["error"] = f"DATA rejected: {code}"
    except smtplib.SMTPAuthenticationError as e:
        report["error"] = f"AUTH failed: {e.smtp_code} {e.smtp_error.decode(errors='ignore') if e.smtp_error else e}"
    except smtplib.SMTPException as e:
        report["error"] = f"smtp exception: {e}"
    except Exception as e:
        report["error"] = f"unexpected: {e}"
    return report


def load_variant(variants_path: Path, n: int) -> dict:
    data = json.loads(variants_path.read_text(encoding="utf-8"))
    for v in data["variants"]:
        if v["n"] == n:
            return {**v, "_sender": data["sender"]}
    sys.exit(f"variant {n} not found in {variants_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--env-file", default=str(Path(__file__).resolve().parent / "hostinger.env"))
    ap.add_argument("--variants", default=None, help="path to variants.json")
    ap.add_argument("--variant-n", type=int, default=1)
    ap.add_argument("--to", required=True)
    ap.add_argument("--subject", default=None, help="override subject")
    ap.add_argument("--body", default=None, help="override body (plain text)")
    ap.add_argument("--body-file", default=None, help="read body from file")
    ap.add_argument("--save-eml", default=None)
    args = ap.parse_args()

    env = load_env(Path(args.env_file))
    user = env.get("SMTP_USER", "").strip()
    password = env.get("SMTP_PASS", "").strip()
    host = env.get("SMTP_HOST", "smtp.hostinger.com").strip()
    port = int(env.get("SMTP_PORT", "465"))
    from_name = env.get("FROM_NAME", "Aureon").strip()
    from_addr = env.get("FROM_ADDR", user).strip()

    if not user or not password:
        sys.exit(f"missing SMTP_USER or SMTP_PASS in {args.env_file}")

    # Compose
    if args.variants:
        v = load_variant(Path(args.variants), args.variant_n)
        subject = args.subject or v["subject"]
        body    = args.body or v["body"]
    else:
        if not args.subject or (not args.body and not args.body_file):
            sys.exit("either --variants/--variant-n or --subject + --body/--body-file")
        subject = args.subject
        body = args.body if args.body else Path(args.body_file).read_text(encoding="utf-8")

    raw, msg_id = build_message(from_name, from_addr, args.to, subject, body, from_addr)
    print(f"\n=== sending via {host}:{port} (SMTPS) ===")
    print(f"  from:    {from_name} <{from_addr}>")
    print(f"  to:      {args.to}")
    print(f"  auth:    {user}")
    print(f"  subject: {subject}")
    print(f"  msgid:   {msg_id}")
    print(f"  bytes:   {len(raw)}\n")

    if args.save_eml:
        Path(args.save_eml).write_bytes(raw)
        print(f"  saved → {args.save_eml}")

    report = send_via_smtps(host, port, user, password, raw, from_addr, args.to)
    print("\n=== report ===")
    # Redact password if it somehow ended up in report (defensive)
    redacted = {k: ("***" if "pass" in k.lower() else v) for k, v in report.items()}
    print(json.dumps(redacted, indent=2, default=str))
    if report.get("delivered"):
        print(f"\n[ok] SMTP accepted: {report.get('smtp_response')}")
        print("[note] Acceptance ≠ inbox. Check recipient's INBOX and SPAM folder.")
        return 0
    else:
        print(f"\n[fail] {report.get('error') or 'unknown'}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
