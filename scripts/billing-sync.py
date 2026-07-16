# -*- coding: utf-8 -*-
"""billing-sync.py — push new billing-on-file profiles into the AUREON invoice
generator and notify info@.

After a client signs their service agreement they complete the billing step in
the portal (/billing/:id): billing identity + funding method (Payoneer email /
IBAN) + a signed charge authorization. That writes a `billing_profiles` row in
Supabase. The Edge runtime can't touch the local generator folder, so this local
task does two things for every newly-authorized profile:

  1. Drop a client-profile JSON into C:\\Aureon Invoices\\clients\\<slug>.json so
     the invoice generator can pick up the new client (name, legal name, address,
     VAT, funding method, email).
  2. Email info@ a notification (with the signed-authorization audit trail).

Idempotent: a row is processed once for the JSON drop (json_dropped_at) and once
for the email (notified_at). Re-signing billing resets both flags (the Edge
Function nulls them on upsert) so updates re-sync.

    py scripts/billing-sync.py
"""
from __future__ import annotations
import json, sys, ssl, smtplib, datetime as dt, urllib.request, urllib.parse
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from mailer import send as send_mail   # Resend primary (VPS blocks SMTP), SMTP fallback
CLIENTS_DIR = Path(r"C:\Aureon Invoices\clients")
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
KEY = SENV["SUPABASE_SERVICE_KEY"]          # service role — bypasses RLS
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
     "User-Agent": "les-billing-sync/1.0"}


def _get(path: str):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H, method="GET")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def _patch(path: str, body: dict):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", data=json.dumps(body).encode(),
                                 headers={**H, "Prefer": "return=minimal"}, method="PATCH")
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.status


def _client(client_id: str) -> dict:
    rows = _get(f"clients?id=eq.{client_id}&select=id,company,email,profile_slug")
    return rows[0] if rows else {}


def _drop_json(bp: dict, client: dict) -> Path:
    """Write the generator's client-profile JSON. Slug-named, overwritten on update."""
    CLIENTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = bp.get("profile_slug") or client.get("profile_slug") or client.get("id")
    profile = {
        "slug": slug,
        "company": client.get("company"),
        "legal_name": bp.get("legal_name") or client.get("company"),
        "billing_name": bp.get("billing_name"),
        "billing_email": bp.get("billing_email") or client.get("email"),
        "address_line": bp.get("address_line"),
        "city": bp.get("city"),
        "postal_code": bp.get("postal_code"),
        "country": bp.get("country"),
        "vat_id": bp.get("vat_id"),
        "funding": {
            "payoneer_email": bp.get("payoneer_email"),
            "iban": bp.get("iban"),
        },
        "charge_authorized": bool(bp.get("authorized")),
        "authorized_at": bp.get("authorized_at"),
        "authorization_sha": bp.get("authorization_sha"),
        "source": "aureon-portal",
        "written_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    safe = "".join(c for c in str(slug) if c.isalnum() or c in "-_") or "client"
    path = CLIENTS_DIR / f"{safe}.json"
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def _notify(bp: dict, client: dict, json_path: Path) -> bool:
    company = client.get("company") or bp.get("legal_name") or "A client"
    fund = bp.get("payoneer_email") or bp.get("iban") or "—"
    rows = "".join(
        f"<tr><td style='padding:4px 12px 4px 0;color:#888'>{k}</td>"
        f"<td style='padding:4px 0'>{(bp.get(v) or '—')}</td></tr>"
        for k, v in [
            ("Billing name", "billing_name"), ("Legal name", "legal_name"),
            ("Billing email", "billing_email"), ("Address", "address_line"),
            ("City", "city"), ("Postal code", "postal_code"), ("Country", "country"),
            ("VAT ID", "vat_id"), ("Payoneer email", "payoneer_email"), ("IBAN", "iban"),
        ])
    html = f"""<div style="font-family:Inter,Arial,sans-serif;color:#111">
    <h2 style="margin:0 0 6px">New billing profile on file</h2>
    <p style="margin:0 0 14px;color:#555"><b>{company}</b> completed billing setup and
    signed the charge authorization.</p>
    <table style="border-collapse:collapse;font-size:14px">{rows}</table>
    <p style="margin:14px 0 4px;font-size:13px;color:#555">Funding method: <b>{fund}</b></p>
    <p style="margin:0 0 4px;font-size:12px;color:#888">Authorization signed
    {bp.get('authorized_at')} · IP {bp.get('signer_ip') or '—'}</p>
    <p style="margin:0;font-size:11px;color:#aaa">SHA-256 {bp.get('authorization_sha')}</p>
    <p style="margin:14px 0 0;font-size:12px;color:#555">Generator profile written to:
    {json_path}</p>
    <p style="margin:6px 0 0;font-size:12px;color:#555">Authorization text:<br>
    <i>{bp.get('authorization_text') or ''}</i></p>
    </div>"""
    text = (f"New billing profile on file — {company}\n"
            f"Funding: {fund}\nAuthorized: {bp.get('authorized_at')} "
            f"IP {bp.get('signer_ip')}\nSHA {bp.get('authorization_sha')}\n"
            f"Profile JSON: {json_path}\n")
    return send_mail(to=OPERATOR_ADDR, subject=f"Billing on file — {company}",
                     html=html, text=text, reply_to=OPERATOR_ADDR)


def main() -> int:
    # Authorized profiles still needing a JSON drop or a notification.
    pending = _get(
        "billing_profiles?authorized=eq.true"
        "&or=(json_dropped_at.is.null,notified_at.is.null)"
        "&select=*")
    if not pending:
        print("billing-sync: nothing pending")
        return 0
    print(f"billing-sync: {len(pending)} profile(s) to process")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for bp in pending:
        client = _client(bp["client_id"])
        label = client.get("company") or bp.get("legal_name") or bp["client_id"]
        patch: dict = {}
        if not bp.get("json_dropped_at"):
            try:
                p = _drop_json(bp, client)
                patch["json_dropped_at"] = now
                print(f"  ✓ {label}: profile JSON -> {p}")
            except Exception as e:
                print(f"  ! {label}: JSON drop failed: {e}")
        if not bp.get("notified_at"):
            try:
                p = CLIENTS_DIR / f"{(bp.get('profile_slug') or client.get('profile_slug') or 'client')}.json"
                if _notify(bp, client, p):
                    patch["notified_at"] = now
                    print(f"  ✓ {label}: emailed {OPERATOR_ADDR}")
            except Exception as e:
                print(f"  ! {label}: notify failed: {e}")
        if patch:
            _patch(f"billing_profiles?id=eq.{bp['id']}", patch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
