"""send-atal-invoice.py -- one-off transactional sender.

Sends the Anzahlungsrechnung AG-ATAL-2026-001 (PDF, 500 EUR deposit on the
1000 EUR Landing Page project) plus the Aureon onboarding form link via
Hostinger SMTP, from info@aureonglobal.de.

Run a test to yourself first, eyeball it, then re-run with the real recipient:

    py scripts/send-atal-invoice.py --to info@aureonglobal.de        # test
    py scripts/send-atal-invoice.py --to atal.solidrocks@gmail.com   # live

Reads SMTP creds from sequences/hostinger.env (SMTP_HOST, SMTP_PORT,
SMTP_USER, SMTP_PASS). PDF path is hardcoded to the invoice file at
C:\\Aureon Invoices\\Rechnung_AG-ATAL-2026-001_Atal-Solidrocks_Anzahlung_500EUR.pdf.
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
PDF_PATH = Path(r"C:\Aureon Invoices\Rechnung_AG-ATAL-2026-001_Atal-Solidrocks_Anzahlung_500EUR.pdf")
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSdg0Zwyy6qV39ziUXINSKaV0qCnqLDaucLVuNZnwqInta4Hzw/viewform"

SUBJECT = "Aureon Global – Anzahlungsrechnung AG-ATAL-2026-001 und Onboarding-Fragebogen"

PLAIN_BODY = """Lieber Atal,

vielen Dank für das Vertrauen in Aureon Global. Im Anhang finden Sie die
Anzahlungsrechnung AG-ATAL-2026-001 über 500,00 EUR (50 Prozent Anzahlung
auf das Gesamtauftragsvolumen von 1.000,00 EUR für Konzeption, Design und
Implementierung Ihrer neuen Landing Page).

Damit wir parallel zur Bezahlung sofort mit der Strategiephase starten
können, bitte ich Sie, den Onboarding-Fragebogen auszufüllen:

  {form_url}

Der Fragebogen dauert rund 10 Minuten und deckt Zielgruppe, Angebot,
Conversion-Logik und alles Weitere ab, was wir für die Strategie brauchen.
Oben im Fragebogen sehen Sie außerdem den genauen Ablauf der nächsten Wochen,
damit Sie wissen, was wann passiert.

RECHNUNGSDETAILS

  Rechnungsnummer    AG-ATAL-2026-001
  Betrag             500,00 EUR (Ausfuhr, 0,00 EUR USt.)
  Fällig bis         02.06.2026
  Verwendungszweck   AG-ATAL-2026-001

  Kontoinhaber       Aureon Global L.L.C.
  IBAN               XK05 1110 3652 6500 0111
  BIC                PRBKXKPR
  Bank               ProCredit Bank SH.A., Kosovo
  Währung            EUR

Sobald die Anzahlung eingegangen und der Fragebogen ausgefüllt ist,
buchen wir den 30-minütigen Kickoff-Call und starten mit der
Conversion-Copy und dem Design.

Bei Fragen einfach auf diese E-Mail antworten.

Beste Grüße
Gentrit Luta
Geschäftsführer, Aureon Global L.L.C.
info@aureonglobal.de | aureonglobal.de
""".format(form_url=FORM_URL)


def html_body() -> str:
    return f"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Aureon Global – Anzahlungsrechnung und Onboarding</title>
</head>
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
      <td style="padding:32px 32px 8px;font-size:14px;line-height:1.6;color:#1f2937;">
        <p style="margin:0 0 16px;">Lieber Atal,</p>
        <p style="margin:0 0 16px;">vielen Dank für das Vertrauen in Aureon Global. Im Anhang finden Sie die <strong>Anzahlungsrechnung AG-ATAL-2026-001</strong> über <strong>500,00 &euro;</strong> (50 Prozent Anzahlung auf das Gesamtauftragsvolumen von 1.000,00 &euro; für Konzeption, Design und Implementierung Ihrer neuen Landing Page).</p>
        <p style="margin:0 0 16px;">Damit wir parallel zur Bezahlung sofort mit der Strategiephase starten können, bitte ich Sie, den Onboarding-Fragebogen auszufüllen. Er dauert rund 10 Minuten und deckt Zielgruppe, Angebot, Conversion-Logik und alles Weitere ab. Oben im Fragebogen sehen Sie außerdem den genauen Ablauf der nächsten Wochen, damit Sie wissen, was wann passiert.</p>
      </td>
    </tr>
    <tr>
      <td align="center" style="padding:8px 32px 28px;">
        <a href="{FORM_URL}" style="display:inline-block;background:#d4af37;color:#050505;text-decoration:none;font-weight:700;font-size:14px;letter-spacing:0.04em;padding:14px 28px;border-radius:4px;">Onboarding-Fragebogen ausfüllen</a>
        <div style="font-size:11px;color:#94a3b8;margin-top:10px;">Ca. 10 Minuten. Antworten landen direkt bei uns.</div>
      </td>
    </tr>
    <tr>
      <td style="padding:0 32px 8px;">
        <div style="font-size:11px;letter-spacing:0.18em;color:#d4af37;text-transform:uppercase;font-weight:700;border-top:1px solid #e5e7eb;padding-top:24px;">Rechnungsdetails</div>
      </td>
    </tr>
    <tr>
      <td style="padding:8px 32px 4px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;color:#1f2937;line-height:1.7;">
          <tr><td style="color:#475569;width:170px;">Rechnungsnummer</td><td><strong>AG-ATAL-2026-001</strong></td></tr>
          <tr><td style="color:#475569;">Betrag</td><td><strong>500,00 &euro;</strong> (Ausfuhr, 0,00 &euro; USt.)</td></tr>
          <tr><td style="color:#475569;">Fällig bis</td><td><strong>02.06.2026</strong></td></tr>
          <tr><td style="color:#475569;">Verwendungszweck</td><td style="font-family:'SFMono-Regular',Menlo,Consolas,monospace;">AG-ATAL-2026-001</td></tr>
        </table>
      </td>
    </tr>
    <tr>
      <td style="padding:20px 32px 4px;">
        <div style="font-size:11px;letter-spacing:0.18em;color:#d4af37;text-transform:uppercase;font-weight:700;">Zahlungsinformationen</div>
      </td>
    </tr>
    <tr>
      <td style="padding:8px 32px 28px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:13px;color:#1f2937;line-height:1.7;background:#fafafa;border:1px solid #e5e7eb;border-radius:4px;padding:14px;">
          <tr><td style="color:#475569;padding:10px 14px;width:140px;">Kontoinhaber</td><td style="padding:10px 14px;"><strong>Aureon Global L.L.C.</strong></td></tr>
          <tr><td style="color:#475569;padding:10px 14px;">IBAN</td><td style="padding:10px 14px;font-family:'SFMono-Regular',Menlo,Consolas,monospace;">XK05 1110 3652 6500 0111</td></tr>
          <tr><td style="color:#475569;padding:10px 14px;">BIC / SWIFT</td><td style="padding:10px 14px;font-family:'SFMono-Regular',Menlo,Consolas,monospace;">PRBKXKPR</td></tr>
          <tr><td style="color:#475569;padding:10px 14px;">Bank</td><td style="padding:10px 14px;">ProCredit Bank SH.A., Kosovo</td></tr>
          <tr><td style="color:#475569;padding:10px 14px;">Währung</td><td style="padding:10px 14px;">EUR</td></tr>
        </table>
      </td>
    </tr>
    <tr>
      <td style="padding:0 32px 32px;font-size:14px;line-height:1.6;color:#1f2937;">
        <p style="margin:0 0 16px;">Sobald die Anzahlung eingegangen und der Fragebogen ausgefüllt ist, buchen wir den 30-minütigen Kickoff-Call und starten mit der Conversion-Copy und dem Design.</p>
        <p style="margin:0 0 16px;">Bei Fragen einfach auf diese E-Mail antworten.</p>
        <p style="margin:24px 0 4px;">Beste Grüße</p>
        <p style="margin:0;"><strong>Gentrit Luta</strong><br>Geschäftsführer, Aureon Global L.L.C.</p>
      </td>
    </tr>
    <tr>
      <td style="background:#050505;color:#94a3b8;font-size:11px;line-height:1.6;padding:20px 32px;">
        <strong style="color:#d4af37;">Aureon Global L.L.C.</strong> &middot; Dushkaja 20, 71000 Kaçanik, Republic of Kosovo<br>
        Geschäftsführer Gentrit Luta &middot; <a href="mailto:info@aureonglobal.de" style="color:#94a3b8;text-decoration:underline;">info@aureonglobal.de</a> &middot; <a href="https://aureonglobal.de" style="color:#94a3b8;text-decoration:underline;">aureonglobal.de</a> &middot; Reg.-Nr. 812368240
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
    pdf_attachment = MIMEApplication(pdf_bytes, _subtype="pdf")
    pdf_attachment.add_header("Content-Disposition", "attachment", filename=PDF_PATH.name)
    outer.attach(pdf_attachment)

    return outer


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True, help="recipient email")
    ap.add_argument("--env", default=str(ENV_PATH))
    args = ap.parse_args()

    if not PDF_PATH.exists():
        print(f"ERROR: PDF not found at {PDF_PATH}", file=sys.stderr)
        return 1

    env = load_env(Path(args.env))
    host = env["SMTP_HOST"]
    port = int(env.get("SMTP_PORT", "465"))
    user = env["SMTP_USER"]
    password = env["SMTP_PASS"]
    from_addr = env.get("FROM_ADDR", user)
    from_name = env.get("FROM_NAME", "Aureon Global")

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
