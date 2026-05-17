"""persona-rotate-send.py — single-mailbox sender that rotates From-display-names.

Authenticates ONCE as info@aureonglobal.de via Hostinger SMTPS, but each send picks
a different persona (Daniel / Anna / Marco) for the From-header display name. The
actual email address stays info@. All replies route back to info@.

Why: when the Hostinger plan only allows 1 mailbox and Resend domain verification
isn't yet set up, this is the cleanest way to give cold outreach a "named human" feel
while respecting the constraints.

Usage:
    py persona-rotate-send.py aureon --variants <variants.json> --variant-n <N> --to <addr>
    py persona-rotate-send.py aureon --variants sequences/aureon-20-variants/variants.json --variant-n 1 --to g-luta@web.de
    py persona-rotate-send.py aureon --variants <p> --variant-n 1 --to <a> --force-persona anna
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


def _persona_log(slug: str) -> Path:
    return POOL_STATE / f"{slug}.personas.jsonl"


def load_smtp_password(env_path: Path, key: str = "SMTP_PASS") -> str:
    if not env_path.exists():
        sys.exit(f"missing {env_path}")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    sys.exit(f"{key} not found in {env_path}")


def pick_persona(profile: dict) -> dict:
    personas = profile.get("personas", [])
    if not personas:
        sys.exit("profile has no personas")
    rotation = profile.get("rotation", {})
    quota = int(rotation.get("max_sends_per_persona_per_day", 30))
    min_gap = int(rotation.get("min_seconds_between_sends_same_persona", 60))

    now = time.time()
    today_start = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    log = _persona_log(profile["slug"])
    usage = {p["slug"]: {"count_today": 0, "last_ts": 0.0} for p in personas}
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            slug = row.get("persona")
            ts = float(row.get("ts", 0))
            if slug in usage:
                if ts >= today_start:
                    usage[slug]["count_today"] += 1
                usage[slug]["last_ts"] = max(usage[slug]["last_ts"], ts)

    candidates = []
    for p in personas:
        u = usage[p["slug"]]
        if u["count_today"] >= quota:
            continue
        if (now - u["last_ts"]) < min_gap:
            continue
        candidates.append((u["count_today"], u["last_ts"], p))
    if not candidates:
        sys.exit("all personas either over daily quota or in cooldown")
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]


def build_message(persona: dict, to_addr: str, subject: str, body_plain: str) -> tuple[bytes, str]:
    from_addr = persona["from_addr"]
    from_name = persona["from_name"]
    domain = from_addr.split("@", 1)[1]
    msg_id = f"<{uuid.uuid4().hex}.{int(time.time())}@{domain}>"

    msg = MIMEMultipart("alternative")
    msg["From"]                  = email.utils.formataddr((from_name, from_addr))
    msg["To"]                    = to_addr
    msg["Subject"]               = subject
    msg["Reply-To"]              = persona.get("reply_to", from_addr)
    msg["Date"]                  = email.utils.formatdate(localtime=True)
    msg["Message-ID"]            = msg_id
    msg["MIME-Version"]          = "1.0"
    msg["X-Mailer"]              = "Local Email Stack 0.4 (persona-rotate)"
    msg["List-Unsubscribe"]      = f"<mailto:{from_addr}?subject=unsubscribe>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"

    body_with_sig = body_plain + "\n\n" + persona.get("signature", "")
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


def send_via_smtps(profile: dict, persona: dict, smtp_pass: str, raw: bytes, to: str) -> dict:
    auth = profile["auth_mailbox"]
    host = auth["smtp_host"]; port = int(auth["smtp_port"])
    user = auth["smtp_user"]
    report = {"host": host, "port": port, "persona": persona["slug"],
              "from": f'{persona["from_name"]} <{persona["from_addr"]}>',
              "smtp_auth_as": user, "to": to, "delivered": False, "phase": None,
              "smtp_response": None, "started_at": dt.datetime.now().isoformat()}
    try:
        with smtplib.SMTP_SSL(host, port, timeout=30, context=ssl.create_default_context()) as s:
            report["phase"] = "ehlo"; s.ehlo()
            report["phase"] = "login"; s.login(user, smtp_pass)
            report["phase"] = "mail_from"; s.mail(user)
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
                report["delivered"] = True; report["phase"] = "delivered"
            else:
                report["error"] = f"DATA rejected {code}"
    except smtplib.SMTPAuthenticationError as e:
        report["error"] = f"AUTH failed: {e.smtp_code} {e.smtp_error.decode(errors='ignore') if e.smtp_error else e}"
    except smtplib.SMTPException as e:
        report["error"] = f"smtp exception: {e}"
    except Exception as e:
        report["error"] = f"unexpected: {e}"
    return report


def record_send(profile_slug: str, persona_slug: str, to: str, ok: bool, err: str | None) -> None:
    row = {"ts": time.time(), "persona": persona_slug, "to": to, "delivered": ok, "error": err}
    with _persona_log(profile_slug).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--variants", required=True)
    ap.add_argument("--variant-n", type=int, required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--force-persona", default=None)
    ap.add_argument("--save-eml", default=None)
    args = ap.parse_args()

    profile = load_profile(args.slug)
    persona = (next((p for p in profile["personas"] if p["slug"] == args.force_persona), None)
               if args.force_persona else pick_persona(profile))
    if not persona:
        sys.exit(f"no persona '{args.force_persona}' in profile")

    smtp_pass_path = Path(__file__).resolve().parent.parent / profile["auth_mailbox"]["smtp_pass_source"]
    smtp_pass = load_smtp_password(smtp_pass_path)

    variants = json.loads(Path(args.variants).read_text(encoding="utf-8"))
    variant = next((v for v in variants["variants"] if v["n"] == args.variant_n), None)
    if not variant:
        sys.exit(f"variant {args.variant_n} not found")

    raw, msg_id = build_message(persona, args.to, variant["subject"], variant["body"])

    print(f"\n=== persona-rotate send ===")
    print(f"  persona:    {persona['slug']} ({persona['from_name']})")
    print(f"  from:       {persona['from_name']} <{persona['from_addr']}>")
    print(f"  smtp auth:  {profile['auth_mailbox']['smtp_user']}")
    print(f"  to:         {args.to}")
    print(f"  subject:    {variant['subject']}")
    print(f"  msgid:      {msg_id}\n")

    if args.save_eml:
        Path(args.save_eml).write_bytes(raw)

    report = send_via_smtps(profile, persona, smtp_pass, raw, args.to)
    record_send(args.slug, persona["slug"], args.to, report["delivered"], report.get("error"))

    print("=== report ===")
    print(json.dumps({k: v for k, v in report.items() if "pass" not in k.lower()}, indent=2, default=str))
    if report["delivered"]:
        print(f"\n[ok] SMTP accepted: {report['smtp_response']}")
        return 0
    print(f"\n[fail] {report.get('error')}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
