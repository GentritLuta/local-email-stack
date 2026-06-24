# -*- coding: utf-8 -*-
"""continuation-issue.py — auto-issue the continuation agreement ~90 days after
the pilot is signed.

For every signed/sealed PILOT contract whose signing is >= CONTINUATION_AFTER_DAYS
old and that has no continuation contract yet:
  1. Generate the continuation agreement (10% commission, EUR 500/mo, 12-mo term,
     Client's jurisdiction) as a draft contracts row (kind='continuation').
  2. Email the client a link to sign it (and CC info@), and remind the operator
     to review the placeholder terms.

Billing-on-file unlocks only after the client SIGNS this continuation (the portal
gates the billing step on a signed continuation).

    py scripts/continuation-issue.py                 # issue all eligible
    py scripts/continuation-issue.py --days 0         # issue immediately (testing)
"""
from __future__ import annotations
import argparse, json, sys, ssl, smtplib, datetime as dt, urllib.request, urllib.error
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from continuation_lib import generate_continuation, make_continuation_ref  # noqa: E402

CONTINUATION_AFTER_DAYS = 90
OPERATOR_ADDR = "info@aureonglobal.de"


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
KEY = SENV["SUPABASE_SERVICE_KEY"]
PORTAL = "https://portal.aureonglobal.de"
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
     "User-Agent": "les-continuation/1.0"}


def _get(path):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H, method="GET")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def _post(path, body):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", data=json.dumps(body).encode(),
                                 headers={**H, "Prefer": "return=minimal"}, method="POST")
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.status


def _patch(path, body):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", data=json.dumps(body).encode(),
                                 headers={**H, "Prefer": "return=minimal"}, method="PATCH")
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.status


def _email_client_to_sign(*, to_email: str, company: str, sub_id: str, ref: str) -> bool:
    user = HENV.get("SMTP_USER") or OPERATOR_ADDR
    pw = HENV.get("SMTP_PASS")
    if not pw:
        print("    (no SMTP_PASS — sign-request email not sent)")
        return False
    sign_url = f"{PORTAL}/continuation/{sub_id}"
    html = f"""<div style="font-family:Inter,Arial,sans-serif;color:#111">
    <h2 style="margin:0 0 8px">Your continuation agreement is ready</h2>
    <p>Hi{(' ' + company) if company else ''}, your pilot with AUREON Global is
    complete. To continue, please review and sign your continuation agreement.</p>
    <p style="margin:18px 0"><a href="{sign_url}"
      style="background:#d4af37;color:#0a0a0a;padding:11px 20px;border-radius:8px;
      text-decoration:none;font-weight:700">Review &amp; sign ({ref})</a></p>
    <p style="font-size:12px;color:#666">After signing you'll add your billing details
    so we can continue your campaign without interruption.</p>
    </div>"""
    text = (f"Your continuation agreement ({ref}) is ready. "
            f"Review and sign: {sign_url}")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Your AUREON continuation agreement is ready to sign"
    msg["From"] = user
    msg["To"] = to_email
    msg["Cc"] = OPERATOR_ADDR
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.hostinger.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, pw)
        s.sendmail(user, [to_email, OPERATOR_ADDR], msg.as_string())
    return True


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=CONTINUATION_AFTER_DAYS,
                    help="issue continuation this many days after the pilot signed")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=args.days)

    # Signed/sealed pilots.
    pilots = _get("contracts?kind=eq.pilot&status=in.(signed,sealed)"
                  "&select=id,client_id,submission_id,signed_at,signer_email,profile_slug")
    if not pilots:
        print("continuation-issue: no signed pilots")
        return 0

    # Existing continuations (skip submissions that already have one).
    conts = _get("contracts?kind=eq.continuation&select=submission_id")
    have = {c["submission_id"] for c in conts}

    made = 0
    for p in pilots:
        sid = p["submission_id"]
        if not sid or sid in have:
            continue
        signed_at = p.get("signed_at")
        if signed_at:
            try:
                sa = dt.datetime.fromisoformat(signed_at.replace("Z", "+00:00"))
            except Exception:
                sa = now
            if sa > cutoff:
                continue  # pilot too recent
        # Pull the submission's answers for the client fields.
        subs = _get(f"onboarding_submissions?id=eq.{sid}&select=raw_answers,client_id")
        if not subs:
            continue
        a = subs[0].get("raw_answers") or {}
        company = a.get("company") or ""
        ref = make_continuation_ref(company)
        try:
            html = generate_continuation(a, ref)
        except Exception as e:
            print(f"  ! generate failed for {sid[:8]}: {e}")
            continue
        row = {
            "client_id": p.get("client_id"), "submission_id": sid,
            "profile_slug": p.get("profile_slug"),
            "contract_ref": ref, "contract_html": html, "status": "draft",
            "kind": "continuation",
            "signer_name": (a.get("rep") or "").strip() or None,
            "signer_email": (a.get("contact_email") or p.get("signer_email") or "").strip() or None,
            "signer_title": (a.get("rep_title") or "").strip() or None,
            "notified_at": now.isoformat(),
        }
        try:
            _post("contracts", row)
        except urllib.error.HTTPError as e:
            print(f"  ! insert failed {sid[:8]}: {e.code} {e.read().decode()[:160]}")
            continue
        to = row["signer_email"]
        if to:
            try:
                _email_client_to_sign(to_email=to, company=company, sub_id=sid, ref=ref)
            except Exception as e:
                print(f"  ! email failed {sid[:8]}: {e}")
        made += 1
        print(f"  + continuation issued for {company} ({ref}) -> {to}")

    print(f"continuation-issue: {made} continuation(s) issued"
          + (f" | REMINDER: review the placeholder terms in continuation_lib.py" if made else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
