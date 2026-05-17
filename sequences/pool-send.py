"""pool-send.py — multi-mailbox send for a profile with a mailbox pool.

Selects a sending mailbox from the profile's pool (round-robin with usage
tracking), authenticates via SMTPS to Hostinger, and sends with full header
hygiene. Each mailbox has its own SMTP credential (read from <slug>.private.json).

Usage:
    py pool-send.py <profile_slug> --variants <variants.json> --variant-n <N> --to <addr>
    py pool-send.py aureon --variants sequences/aureon-20-variants/variants.json --variant-n 1 --to g-luta@web.de
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import smtplib
import ssl
import sys
import time
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from profile_lib import load_profile

POOL_STATE = Path(__file__).resolve().parent.parent / "warmup-state"
POOL_STATE.mkdir(exist_ok=True)


def _pool_log(slug: str) -> Path:
    return POOL_STATE / f"{slug}.pool.jsonl"


def pick_mailbox(profile: dict) -> dict:
    """Round-robin with per-mailbox daily quota + min-interval enforcement."""
    mailboxes = profile.get("mailboxes", [])
    if not mailboxes:
        sys.exit("profile has no mailboxes")
    rotation = profile.get("rotation", {})
    quota = int(rotation.get("max_sends_per_mailbox_per_day", 30))
    min_gap = int(rotation.get("min_seconds_between_sends_from_same_mailbox", 60))

    # Recent usage from log
    now = time.time()
    today_start = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    log = _pool_log(profile["slug"])
    usage = {m["slug"]: {"count_today": 0, "last_ts": 0} for m in mailboxes}
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            mbox = row.get("mailbox")
            ts = float(row.get("ts", 0))
            if mbox in usage:
                if ts >= today_start:
                    usage[mbox]["count_today"] += 1
                usage[mbox]["last_ts"] = max(usage[mbox]["last_ts"], ts)

    # Eligible mailboxes: under daily quota AND past min_gap
    candidates = []
    for m in mailboxes:
        u = usage[m["slug"]]
        if u["count_today"] >= quota:
            continue
        if (now - u["last_ts"]) < min_gap:
            continue
        candidates.append((u["count_today"], u["last_ts"], m))
    if not candidates:
        sys.exit("all mailboxes either over daily quota or in cooldown; try later")

    # Round-robin = pick least-used, oldest-last-used
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]


def credentials_for(profile_slug: str, mailbox_slug: str) -> str:
    """Read app password from <slug>.private.json."""
    priv_path = Path(__file__).resolve().parent.parent / "profiles" / f"{profile_slug}.private.json"
    if not priv_path.exists():
        sys.exit(f"missing {priv_path} — copy from .example and fill in app passwords")
    priv = json.loads(priv_path.read_text(encoding="utf-8"))
    creds = (priv.get("mailbox_credentials") or {}).get(mailbox_slug)
    if not creds or not creds.get("pass"):
        sys.exit(f"no password for mailbox '{mailbox_slug}' in {priv_path}")
    return creds["pass"]


def build_message(mailbox: dict, to_addr: str, subject: str, body_plain: str) -> tuple[bytes, str]:
    from_addr = mailbox["from_addr"]
    from_name = mailbox["from_name"]
    domain = from_addr.split("@", 1)[1]
    msg_id = f"<{uuid.uuid4().hex}.{int(time.time())}@{domain}>"
    msg = MIMEMultipart("alternative")
    msg["From"]                  = email.utils.formataddr((from_name, from_addr))
    msg["To"]                    = to_addr
    msg["Subject"]               = subject
    msg["Reply-To"]              = from_addr
    msg["Date"]                  = email.utils.formatdate(localtime=True)
    msg["Message-ID"]            = msg_id
    msg["MIME-Version"]          = "1.0"
    msg["X-Mailer"]              = "Local Email Stack 0.4 (pool)"
    msg["List-Unsubscribe"]      = f"<mailto:{from_addr}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    body_with_sig = body_plain + "\n\n" + mailbox.get("signature", "")
    html_paras = "".join(f"<p>{esc(p)}</p>" for p in body_with_sig.strip().split("\n\n"))
    html = (
        "<!doctype html><html><head><meta charset='utf-8'></head><body style='"
        "font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;"
        "line-height:1.55;color:#1f2937;max-width:600px'>"
        + html_paras + "</body></html>"
    )
    msg.attach(MIMEText(body_with_sig, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg.as_bytes(), msg_id


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def send_via_smtps(profile: dict, mailbox: dict, password: str, raw: bytes, to: str) -> dict:
    relay = profile.get("relay", {})
    host = relay.get("host", "smtp.hostinger.com")
    port = int(relay.get("port", 465))
    report = {"host": host, "port": port, "mailbox": mailbox["slug"], "from": mailbox["from_addr"], "to": to,
              "delivered": False, "phase": None, "smtp_response": None,
              "started_at": dt.datetime.now().isoformat()}
    try:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context()) as s:
            report["phase"] = "ehlo"
            s.ehlo()
            report["phase"] = "login"
            s.login(mailbox["from_addr"], password)
            report["phase"] = "mail_from"
            s.mail(mailbox["from_addr"])
            report["phase"] = "rcpt_to"
            code, msg = s.rcpt(to)
            report["rcpt"] = f"{code} {msg.decode(errors='ignore').strip()[:200]}"
            if code >= 400:
                report["error"] = f"RCPT rejected {code}"
                return report
            report["phase"] = "data"
            code, msg = s.data(raw)
            report["smtp_response"] = f"{code} {msg.decode(errors='ignore').strip()[:300]}"
            if code < 400:
                report["delivered"] = True
                report["phase"] = "delivered"
            else:
                report["error"] = f"DATA rejected {code}"
    except smtplib.SMTPAuthenticationError as e:
        report["error"] = f"AUTH failed: {e.smtp_code} {e.smtp_error.decode(errors='ignore') if e.smtp_error else e}"
    except smtplib.SMTPException as e:
        report["error"] = f"smtp exception: {e}"
    except Exception as e:
        report["error"] = f"unexpected: {e}"
    return report


def record_send(profile_slug: str, mailbox_slug: str, to: str, ok: bool, err: str | None) -> None:
    row = {"ts": time.time(), "mailbox": mailbox_slug, "to": to, "delivered": ok, "error": err}
    with _pool_log(profile_slug).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--variants", required=True)
    ap.add_argument("--variant-n", type=int, required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--force-mailbox", default=None, help="bypass rotation, use specific mailbox slug")
    ap.add_argument("--save-eml", default=None)
    args = ap.parse_args()

    profile = load_profile(args.slug)
    if args.force_mailbox:
        mailbox = next((m for m in profile["mailboxes"] if m["slug"] == args.force_mailbox), None)
        if not mailbox:
            sys.exit(f"no mailbox '{args.force_mailbox}' in profile")
    else:
        mailbox = pick_mailbox(profile)
    password = credentials_for(args.slug, mailbox["slug"])

    variants = json.loads(Path(args.variants).read_text(encoding="utf-8"))
    variant = next((v for v in variants["variants"] if v["n"] == args.variant_n), None)
    if not variant:
        sys.exit(f"variant {args.variant_n} not found")

    raw, msg_id = build_message(mailbox, args.to, variant["subject"], variant["body"])

    print(f"\n=== pool send via {mailbox['slug']} ===")
    print(f"  from:    {mailbox['from_name']} <{mailbox['from_addr']}>")
    print(f"  to:      {args.to}")
    print(f"  subject: {variant['subject']}")
    print(f"  msgid:   {msg_id}\n")

    if args.save_eml:
        Path(args.save_eml).write_bytes(raw)

    report = send_via_smtps(profile, mailbox, password, raw, args.to)
    record_send(args.slug, mailbox["slug"], args.to, report["delivered"], report.get("error"))

    print("=== report ===")
    print(json.dumps({k: v for k, v in report.items() if "pass" not in k.lower()}, indent=2, default=str))
    if report["delivered"]:
        print(f"\n[ok] SMTP accepted: {report['smtp_response']}")
        return 0
    print(f"\n[fail] {report.get('error')}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
