# -*- coding: utf-8 -*-
"""credentials-sync.py — land a client's sending-infra access locally and notify info@.

After a client signs their pilot agreement they complete the access step in the
portal (/access/:id): they hand over a SCOPED API token for their DNS / domain
host plus a signed authorization to use it. That writes a `client_credentials`
row in Supabase. The Edge runtime can't touch the local secrets file, so this
local task does two things for every newly-authorized handover:

  1. Write the token into sequences/hostinger.env under the right key so the
     provisioning pipeline can auto-publish DNS:
        hostinger  -> HOSTINGER_API_TOKEN_<SLUG>
        cloudflare -> CF_API_TOKEN_<SLUG>
        other      -> CLIENT_API_TOKEN_<SLUG>
  2. Email info@ ALL the details combined (the onboarding answers + the access
     token) so the operator can start working immediately.

Idempotent: a row is processed once for the env write (written_to_env_at) and
once for the email (notified_at). Re-submitting access resets both flags (the
Edge Function nulls them on upsert) so updates re-sync.

    py scripts/credentials-sync.py
"""
from __future__ import annotations
import json, sys, ssl, smtplib, re, datetime as dt, urllib.request
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
HOSTINGER_ENV = REPO / "sequences" / "hostinger.env"
OPERATOR_ADDR = "info@aureonglobal.de"


def _load_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); out[k.strip()] = v.strip()
    return out


SENV = _load_env(REPO / "sequences" / "supabase.env")
HENV = _load_env(HOSTINGER_ENV)
URL = SENV["SUPABASE_URL"].rstrip("/")
KEY = SENV["SUPABASE_SERVICE_KEY"]          # service role — bypasses RLS
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
     "User-Agent": "les-credentials-sync/1.0"}


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


def _latest_answers(client_id: str) -> dict:
    rows = _get(f"onboarding_submissions?client_id=eq.{client_id}"
                "&select=raw_answers,created_at&order=created_at.desc&limit=1")
    return (rows[0].get("raw_answers") or {}) if rows else {}


def _slugify(s: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")
    return s or "client"


def _env_key(cr: dict, slug: str) -> str:
    host = (cr.get("dns_host") or "").lower()
    reg = (cr.get("registrar") or "").lower()
    token = slug.upper().replace("-", "_")
    if "hostinger" in host or "hostinger" in reg:
        return f"HOSTINGER_API_TOKEN_{token}"
    if "cloudflare" in host or "cloudflare" in reg or host == "cf":
        return f"CF_API_TOKEN_{token}"
    return f"CLIENT_API_TOKEN_{token}"


def _write_env(key: str, value: str) -> None:
    """Set or replace KEY=value in hostinger.env, preserving everything else."""
    lines = HOSTINGER_ENV.read_text(encoding="utf-8").splitlines() if HOSTINGER_ENV.exists() else []
    out, found = [], False
    for ln in lines:
        if re.match(rf"^\s*{re.escape(key)}\s*=", ln):
            out.append(f"{key}={value}"); found = True
        else:
            out.append(ln)
    if not found:
        out.append(f"{key}={value}")
    HOSTINGER_ENV.write_text("\n".join(out) + "\n", encoding="utf-8")


def _notify(cr: dict, client: dict, answers: dict, env_key: str) -> bool:
    user = HENV.get("SMTP_USER") or OPERATOR_ADDR
    pw = HENV.get("SMTP_PASS")
    if not pw:
        print("    (no SMTP_PASS — combined email not sent)")
        return False
    company = client.get("company") or answers.get("company") or "A client"

    def block(title, pairs):
        rows = "".join(
            f"<tr><td style='padding:4px 12px 4px 0;color:#888;white-space:nowrap;vertical-align:top'>{k}</td>"
            f"<td style='padding:4px 0'>{(v or '—')}</td></tr>" for k, v in pairs)
        return (f"<h3 style='margin:18px 0 6px'>{title}</h3>"
                f"<table style='border-collapse:collapse;font-size:14px'>{rows}</table>")

    onboarding = block("Onboarding details", [
        ("Company", answers.get("company")), ("Website", answers.get("website")),
        ("Contact email", answers.get("contact_email")), ("Offer", answers.get("offer")),
        ("ICP", answers.get("icp")), ("Proof", answers.get("proof")),
        ("CTA", answers.get("cta")), ("Sending domain", answers.get("sending_root")),
        ("DNS host", answers.get("dns_host")), ("Reply-to", answers.get("reply_to")),
        ("Signer", answers.get("rep")), ("Position / title", answers.get("rep_title")),
        ("Jurisdiction", answers.get("jurisdiction")), ("Registered office", answers.get("office")),
        ("Lead source", answers.get("lead_source")), ("Notes", answers.get("notes")),
    ])
    has_email = bool((cr.get("api_token") or "").strip() or (cr.get("registrar") or "").strip())
    has_social = bool((cr.get("social_handles") or "").strip() or (cr.get("asset_link") or "").strip())
    access = block("Sending-infrastructure access", [
        ("Provider", cr.get("registrar")), ("DNS host", cr.get("dns_host")),
        ("API token", cr.get("api_token")), ("Other access", cr.get("other_access")),
        ("Written to hostinger.env as", env_key),
    ]) if has_email else ""
    social = block("Social-media account access", [
        ("Accounts", cr.get("social_handles")),
        ("Access granted via business tools", "yes" if cr.get("social_access_confirmed") else "NOT confirmed"),
        ("Business account ID / invited email", cr.get("social_business_id")),
        ("Brand assets", cr.get("asset_link")),
        ("Content approver", cr.get("content_approver")),
    ]) if has_social else ""
    record = block("Access record", [
        ("Access notes", cr.get("notes")),
        ("Authorized at", cr.get("authorized_at")), ("Signer IP", cr.get("signer_ip")),
    ])
    token_note = (f" The API token is sensitive, it has also been written into "
                  f"hostinger.env as <b>{env_key}</b>.") if (has_email and env_key) else ""
    html = (f"<div style='font-family:Inter,Arial,sans-serif;color:#111'>"
            f"<h2 style='margin:0 0 6px'>New client ready to provision — {company}</h2>"
            f"<p style='margin:0 0 8px;color:#555'>The agreement is signed and access has been "
            f"handed over. Everything you need to start is below.{token_note}</p>"
            f"{onboarding}{access}{social}{record}"
            f"<p style='margin:14px 0 0;font-size:11px;color:#aaa'>Authorization SHA-256 "
            f"{cr.get('authorization_sha')}</p>"
            f"<p style='margin:6px 0 0;font-size:12px;color:#555'>Authorization text:<br>"
            f"<i>{cr.get('authorization_text') or ''}</i></p></div>")
    text = (f"New client ready to provision — {company}\n\n"
            f"ONBOARDING\n"
            + "".join(f"  {k}: {answers.get(v) or '-'}\n" for k, v in [
                ("Company", "company"), ("Contact email", "contact_email"),
                ("Offer", "offer"), ("ICP", "icp"), ("Sending domain", "sending_root"),
                ("DNS host", "dns_host"), ("Reply-to", "reply_to"),
                ("Signer", "rep"), ("Position", "rep_title")])
            + (f"\nEMAIL ACCESS\n"
               f"  Provider: {cr.get('registrar')}\n  DNS host: {cr.get('dns_host')}\n"
               f"  API token: {cr.get('api_token')}\n  Other access: {cr.get('other_access')}\n"
               f"  Written to hostinger.env as: {env_key}\n" if has_email else "")
            + (f"\nSOCIAL ACCESS\n"
               f"  Accounts: {cr.get('social_handles')}\n"
               f"  Access granted: {'yes' if cr.get('social_access_confirmed') else 'NOT confirmed'}\n"
               f"  Business ID / invited email: {cr.get('social_business_id')}\n"
               f"  Brand assets: {cr.get('asset_link')}\n"
               f"  Content approver: {cr.get('content_approver')}\n" if has_social else "")
            + f"\n  Authorized: {cr.get('authorized_at')} IP {cr.get('signer_ip')}\n")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Client ready to provision — {company}"
    msg["From"] = user
    msg["To"] = OPERATOR_ADDR
    msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    with smtplib.SMTP_SSL("smtp.hostinger.com", 465, context=ssl.create_default_context()) as s:
        s.login(user, pw)
        s.sendmail(user, [OPERATOR_ADDR], msg.as_string())
    return True


def main() -> int:
    pending = _get(
        "client_credentials?authorized=eq.true"
        "&or=(written_to_env_at.is.null,notified_at.is.null)"
        "&select=*")
    if not pending:
        print("credentials-sync: nothing pending")
        return 0
    print(f"credentials-sync: {len(pending)} handover(s) to process")
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    for cr in pending:
        client = _client(cr["client_id"])
        answers = _latest_answers(cr["client_id"])
        slug = cr.get("profile_slug") or client.get("profile_slug") \
            or _slugify(client.get("company") or answers.get("company") or "")
        env_key = _env_key(cr, slug)
        label = client.get("company") or answers.get("company") or cr["client_id"]
        patch: dict = {}

        if not cr.get("written_to_env_at"):
            try:
                if (cr.get("api_token") or "").strip():
                    _write_env(env_key, cr["api_token"].strip())
                    print(f"  ✓ {label}: token -> hostinger.env [{env_key}]")
                patch["written_to_env_at"] = now
            except Exception as e:
                print(f"  ! {label}: env write failed: {e}")

        if not cr.get("notified_at"):
            try:
                if _notify(cr, client, answers, env_key):
                    patch["notified_at"] = now
                    print(f"  ✓ {label}: emailed {OPERATOR_ADDR} (combined details)")
            except Exception as e:
                print(f"  ! {label}: notify failed: {e}")

        if patch:
            _patch(f"client_credentials?id=eq.{cr['id']}", patch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
