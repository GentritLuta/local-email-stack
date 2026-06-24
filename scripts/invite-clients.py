# -*- coding: utf-8 -*-
"""invite-clients.py — invite real clients to the AUREON portal and tell them
they can now digitally sign their agreement.

For each (email, company): create/link their portal account via the auth-admin
'invite' action (which sends Supabase's set-password email), then send a branded
Hostinger-SMTP email explaining they can log in and digitally sign.

    py scripts/invite-clients.py            # send to the confirmed list
    py scripts/invite-clients.py --dry      # print, send nothing
"""
from __future__ import annotations
import argparse, json, sys, ssl, smtplib, urllib.request, urllib.error
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
PORTAL = "https://portal.aureonglobal.de"
OPERATOR_ADDR = "info@aureonglobal.de"

# Confirmed recipients (operator-approved 2026-06-16).
RECIPIENTS = [
    ("admin@algoalpha.io",        "AlgoAlpha"),
    ("contact@mark-eting.co",     "Mark-eting"),
    ("info@ener-g-beratung.de",   "ENER-G Beratung"),
    ("skiljodorian@gmail.com",    "Mercury Scales"),
    ("lukas@lk-advertising.com",  "LK Advertising"),
    ("info@atalsolidrocks.com",   "Atal SolidRocks"),
]


def _load_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); out[k.strip()] = v.strip()
    return out


SENV = _load_env(REPO / "sequences" / "supabase.env")
HENV = _load_env(REPO / "sequences" / "hostinger.env")
URL = SENV["SUPABASE_URL"].rstrip("/")
ANON = SENV["SUPABASE_PUBLIC_ANON_KEY"]


def _admin_token() -> str:
    """Sign in as the operator/admin to authorize the invite action."""
    pw = HENV.get("ADMIN_PORTAL_PASS") or "Aureon2026!Admin"
    req = urllib.request.Request(
        f"{URL}/auth/v1/token?grant_type=password",
        data=json.dumps({"email": OPERATOR_ADDR, "password": pw}).encode(),
        headers={"apikey": ANON, "Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=30))["access_token"]


def _invite_account(token: str, email: str, company: str):
    """Create/link the portal account + Supabase set-password email."""
    req = urllib.request.Request(
        f"{URL}/functions/v1/auth-admin",
        data=json.dumps({"action": "invite", "email": email, "company": company}).encode(),
        headers={"Authorization": f"Bearer {token}", "apikey": ANON,
                 "Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=40))


def _email_invite(company: str, to_email: str) -> bool:
    user = HENV.get("SMTP_USER") or OPERATOR_ADDR
    pw = HENV.get("SMTP_PASS")
    if not pw:
        print("    (no SMTP_PASS — branded invite email not sent)")
        return False
    login_url = f"{PORTAL}/login"
    html = f"""<div style="font-family:Inter,Arial,sans-serif;color:#111;max-width:560px">
    <h2 style="margin:0 0 10px">You can now sign your agreement online</h2>
    <p>Hi{(' ' + company) if company else ''}, we've set up your AUREON Global
    client portal. You can now <b>digitally sign your service agreement</b> and
    manage everything in one place:</p>
    <ul style="line-height:1.7">
      <li>Review and <b>sign your agreement</b> online, no printing or scanning</li>
      <li>See your <b>campaign, replies, invoices and sales</b> on your dashboard</li>
      <li>Keep your <b>billing details</b> up to date yourself</li>
    </ul>
    <p style="margin:22px 0">
      <a href="{login_url}" style="background:#d4af37;color:#0a0a0a;padding:12px 22px;
      border-radius:8px;text-decoration:none;font-weight:700">Open your portal</a>
    </p>
    <p style="font-size:13px;color:#555">You'll also receive a separate email to set
    your password. Once that's done, log in any time at portal.aureonglobal.de.</p>
    <p style="font-size:13px;color:#555">Questions? Just reply to this email.</p>
    <p style="font-size:12px;color:#999;margin-top:20px">AUREON Global - Quality Converts</p>
    </div>"""
    text = (f"You can now sign your agreement online.\n\n"
            f"We've set up your AUREON Global client portal. Log in to review and "
            f"digitally sign your service agreement, see your campaign, invoices and "
            f"sales, and manage your billing.\n\nOpen your portal: {login_url}\n"
            f"You'll also get a separate email to set your password.\n\n"
            f"AUREON Global - Quality Converts")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your AUREON portal is ready - sign your agreement online"
    msg["From"] = f"AUREON Global <{user}>"
    msg["To"] = to_email
    msg["Reply-To"] = OPERATOR_ADDR
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.hostinger.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, pw)
        s.sendmail(user, [to_email], msg.as_string())
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="print recipients, send nothing")
    args = ap.parse_args()

    print(f"invite-clients: {len(RECIPIENTS)} recipient(s)")
    for email, company in RECIPIENTS:
        print(f"  - {company:18s} {email}")
    if args.dry:
        print("dry run - nothing sent.")
        return 0

    token = _admin_token()
    ok = 0
    for email, company in RECIPIENTS:
        try:
            r = _invite_account(token, email, company)
            if r.get("error"):
                print(f"  ! {company}: invite account failed: {r['error']}")
            else:
                print(f"  + {company}: portal account invited ({email})")
        except urllib.error.HTTPError as e:
            print(f"  ! {company}: invite HTTP {e.code}: {e.read().decode()[:160]}")
            continue
        try:
            if _email_invite(company, email):
                print(f"    emailed signing invite -> {email}")
                ok += 1
        except Exception as e:
            print(f"    ! email failed: {e}")
    print(f"invite-clients: {ok}/{len(RECIPIENTS)} branded invites sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
