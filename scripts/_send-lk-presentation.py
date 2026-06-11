"""_send-lk-presentation.py -- one-off sender.

Sends the LK Advertising outreach-engine PDF to Lukas Koehler (lukas@lk-advertising.com,
the address on his website) from info@aureonglobal.de, Aureon-branded HTML. SMTP creds
from sequences/hostinger.env.

    py scripts/_send-lk-presentation.py --to info@aureonglobal.de       # test to self FIRST
    py scripts/_send-lk-presentation.py --to lukas@lk-advertising.com   # live
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
PDF_PATH = REPO / "out" / "LK-Advertising-Outreach-Engine.pdf"

SUBJECT = "LK Advertising - your outreach engine and pipeline projection"

PLAIN_BODY = """Hi Lukas,

Attached is the outreach engine we have built for LK Advertising into the US
realtor market, with a full pipeline and revenue projection.

Inside the PDF:

  - how the engine works end to end (sourcing, verification, sending, replies)
  - live deliverability and engagement numbers from our sending stack
    (98.4% delivery, 51% open rate, measured over the last 30 days)
  - a grounded pipeline projection at full ramp: 600 emails a day across 12
    dedicated subdomains, ~18,000 a month
  - an estimated revenue model built on those real rates (estimate, not a guarantee)

Everything is in your brand. Once lk-advertising.site DNS is verified we move
sending onto your own domain and open the ramp. Positive replies route to
cal.com/lk-advertising/15min as agreed.

Have a look in your own time. Reply here with any questions or we cover it on
the kickoff call.

Best,
Gentrit Luta
Aureon Global
info@aureonglobal.de | aureonglobal.de
"""


def html_body() -> str:
    return """<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>LK Advertising - your outreach engine</title></head>
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
        <p style="margin:0 0 16px;">Hi Lukas,</p>
        <p style="margin:0 0 16px;">Attached is the <strong>outreach engine we have built for LK Advertising</strong> into the US realtor market, with a full pipeline and revenue projection. Inside the PDF:</p>
        <ul style="margin:0 0 16px;padding-left:20px;">
          <li style="margin:0 0 8px;">how the engine works end to end (sourcing, verification, sending, replies)</li>
          <li style="margin:0 0 8px;">live deliverability and engagement numbers from our stack (98.4% delivery, 51% open, measured over 30 days)</li>
          <li style="margin:0 0 8px;">a pipeline projection at full ramp: 600 emails a day across 12 dedicated subdomains, ~18,000 a month</li>
          <li style="margin:0 0 8px;">an estimated revenue model built on those real rates (estimate, not a guarantee)</li>
        </ul>
        <p style="margin:0 0 16px;">Everything is in your brand. Once <strong>lk-advertising.site</strong> DNS is verified we move sending onto your own domain and open the ramp. Positive replies route to <strong>cal.com/lk-advertising/15min</strong> as agreed.</p>
        <p style="margin:0 0 16px;">Have a look in your own time. Reply here with any questions, or we cover it on the kickoff call.</p>
        <p style="margin:24px 0 4px;">Best,</p>
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


def build_message(to_addr: str, from_addr: str, from_name: str, cc_addr: str = "") -> MIMEMultipart:
    outer = MIMEMultipart("mixed")
    outer["From"] = f'"{from_name}" <{from_addr}>'
    outer["To"] = to_addr
    if cc_addr:
        outer["Cc"] = cc_addr
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
                   filename="LK-Advertising-Outreach-Engine.pdf")
    outer.attach(att)
    return outer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    ap.add_argument("--cc", default="")
    ap.add_argument("--env", default=str(ENV_PATH))
    args = ap.parse_args()

    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}", file=sys.stderr)
        return 1

    env = load_env(Path(args.env))
    host = env["SMTP_HOST"]; port = int(env.get("SMTP_PORT", "465"))
    user = env["SMTP_USER"]; password = env["SMTP_PASS"]
    from_addr = env.get("FROM_ADDR", user)
    from_name = "Gentrit Luta - Aureon Global"

    msg = build_message(args.to, from_addr, from_name, args.cc)
    rcpts = [args.to] + ([args.cc] if args.cc else [])
    print(f"Connecting to {host}:{port} as {user} ...")
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(host, port, timeout=30, context=ctx) as s:
        s.login(user, password)
        s.send_message(msg, from_addr=from_addr, to_addrs=rcpts)
    print(f"OK -- sent to {args.to}" + (f" cc {args.cc}" if args.cc else "") + f" from {from_addr}")
    print(f"     subject: {SUBJECT}")
    print(f"     attached: {PDF_PATH.name} ({PDF_PATH.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
