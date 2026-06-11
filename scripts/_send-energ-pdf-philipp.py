"""_send-energ-pdf-philipp.py -- one-off sender.

Sends the ENER-G email-campaign PDF to Philipp Loisha (philipp.loisha@gmail.com,
the contact email he gave on the onboarding form) from info@aureonglobal.de,
using the Aureon brand HTML. Reads SMTP creds from sequences/hostinger.env.

    py scripts/_send-energ-pdf-philipp.py --to info@aureonglobal.de        # test to self
    py scripts/_send-energ-pdf-philipp.py --to philipp.loisha@gmail.com    # live
"""
from __future__ import annotations

import argparse
import smtplib
import ssl
import sys
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV_PATH = REPO / "sequences" / "hostinger.env"
PDF_PATH = REPO / "out" / "energ-default-render" / "ENER-G-Beratung-Email-Campaign.pdf"

SUBJECT = "ENER-G – Ihre E-Mail-Kampagne von Aureon"

PLAIN_BODY = """Hallo Philipp,

anbei wie besprochen die fertige E-Mail-Kampagne für ENER-G.

Im PDF finden Sie:

  - eine Uebersicht der Zielgruppe (ICP), der Beweise und der Lead-Magnete
  - eine Leistungsprognose bei 600 E-Mails pro Tag (Schaetzung, keine Garantie)
  - die komplette 7-teilige E-Mail-Sequenz, genau im Design Ihrer Website
    ener-g-beratung.de

So sehen die E-Mails aus, die Ihre potenziellen Kunden erhalten werden.

Sobald der DNS-Zugang fuer ener-g-beratung.de / .org / .com / .store steht,
richten wir die Versanddomains ein und starten den Warmup. Positive Antworten
laufen wie vereinbart auf loisha@energieberatung-schwabenland.de.

Schauen Sie sich das PDF in Ruhe an. Bei Fragen einfach auf diese E-Mail
antworten, oder wir klaeren es im Kickoff-Call (Sie sind ja abends ab 19:00
Uhr frei).

Beste Gruesse
Gentrit Luta
Aureon Global
info@aureonglobal.de | aureonglobal.de
"""


def html_body() -> str:
    return """<!doctype html>
<html lang="de">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>ENER-G – Ihre E-Mail-Kampagne</title></head>
<body style="margin:0;padding:0;background:#fafafa;font-family:Inter,'Segoe UI',Roboto,sans-serif;color:#0a0a0a;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fafafa;">
<tr><td align="center" style="padding:32px 16px;">
  <table role="presentation" width="640" cellpadding="0" cellspacing="0" style="max-width:640px;width:100%;background:#ffffff;border-radius:6px;overflow:hidden;border:1px solid #e5e7eb;">
    <tr>
      <td style="background:#050505;padding:28px 32px;border-bottom:3px solid #d4af37;">
        <div style="font-size:11px;letter-spacing:0.18em;color:#d4af37;text-transform:uppercase;font-weight:700;">Aureon Global</div>
        <div style="font-size:10px;letter-spacing:0.22em;color:#94a3b8;text-transform:uppercase;margin-top:4px;">Quality Converts</div>
      </td>
    </tr>
    <tr>
      <td style="padding:32px 32px 8px;font-size:14px;line-height:1.65;color:#1f2937;">
        <p style="margin:0 0 16px;">Hallo Philipp,</p>
        <p style="margin:0 0 16px;">anbei wie besprochen die fertige <strong>E-Mail-Kampagne für ENER-G</strong>. Im PDF finden Sie:</p>
        <ul style="margin:0 0 16px;padding-left:20px;">
          <li style="margin:0 0 8px;">eine Übersicht der Zielgruppe (ICP), der Beweise und der Lead-Magnete</li>
          <li style="margin:0 0 8px;">eine Leistungsprognose bei 600 E-Mails pro Tag (Schätzung, keine Garantie)</li>
          <li style="margin:0 0 8px;">die komplette 7-teilige E-Mail-Sequenz, genau im Design Ihrer Website <strong>ener-g-beratung.de</strong></li>
        </ul>
        <p style="margin:0 0 16px;">So sehen die E-Mails aus, die Ihre potenziellen Kunden erhalten werden.</p>
        <p style="margin:0 0 16px;">Sobald der DNS-Zugang für die vier Domains steht, richten wir die Versanddomains ein und starten den Warmup. Positive Antworten laufen wie vereinbart auf <strong>loisha@energieberatung-schwabenland.de</strong>.</p>
        <p style="margin:0 0 16px;">Schauen Sie sich das PDF in Ruhe an. Bei Fragen einfach auf diese E-Mail antworten, oder wir klären es im Kickoff-Call.</p>
        <p style="margin:24px 0 4px;">Beste Grüße</p>
        <p style="margin:0;"><strong>Gentrit Luta</strong><br>Aureon Global</p>
      </td>
    </tr>
    <tr>
      <td style="background:#050505;color:#94a3b8;font-size:11px;line-height:1.6;padding:20px 32px;">
        <strong style="color:#d4af37;">Aureon Global L.L.C.</strong> &middot;
        <a href="mailto:info@aureonglobal.de" style="color:#94a3b8;text-decoration:underline;">info@aureonglobal.de</a> &middot;
        <a href="https://aureonglobal.de" style="color:#94a3b8;text-decoration:underline;">aureonglobal.de</a>
      </td>
    </tr>
  </table>
</td></tr>
</table>
</body>
</html>"""


def load_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def build_message(to_addr: str, from_addr: str, from_name: str) -> MIMEMultipart:
    outer = MIMEMultipart("mixed")
    outer["From"] = f'"{from_name}" <{from_addr}>'
    outer["To"] = to_addr
    outer["Subject"] = SUBJECT
    outer["Date"] = formatdate(localtime=True)
    outer["Message-ID"] = make_msgid(domain="aureonglobal.de")
    outer["Reply-To"] = from_addr

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(PLAIN_BODY, "plain", "utf-8"))
    alt.attach(MIMEText(html_body(), "html", "utf-8"))
    outer.attach(alt)

    pdf_bytes = PDF_PATH.read_bytes()
    att = MIMEApplication(pdf_bytes, _subtype="pdf")
    att.add_header("Content-Disposition", "attachment",
                   filename="ENER-G-Email-Kampagne-Aureon.pdf")
    outer.attach(att)
    return outer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--env", default=str(ENV_PATH))
    args = ap.parse_args()

    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}", file=sys.stderr)
        return 1

    env = load_env(Path(args.env))
    host = env["SMTP_HOST"]; port = int(env.get("SMTP_PORT", "465"))
    user = env["SMTP_USER"]; password = env["SMTP_PASS"]
    from_addr = env.get("FROM_ADDR", user)
    from_name = "Gentrit Luta – Aureon Global"

    msg = build_message(args.to, from_addr, from_name)
    print(f"Connecting to {host}:{port} as {user} ...")
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, timeout=30, context=ctx) as s:
        s.login(user, password)
        s.send_message(msg)
    print(f"OK -- sent to {args.to} from {from_addr}")
    print(f"     subject: {SUBJECT}")
    print(f"     attached: {PDF_PATH.name} ({PDF_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
