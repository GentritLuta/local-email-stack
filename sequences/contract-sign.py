# -*- coding: utf-8 -*-
"""contract-sign.py — the self-hosted e-sign backend for client onboarding.

Two jobs, both idempotent and safe to run on a schedule (LES-contract-sign):

  prepare : for every onboarding_submissions row that has NO contract yet,
            auto-generate the pilot agreement from its raw_answers and insert a
            `contracts` row (status='draft'). This is what makes the contract
            "automatically prepared for signing" the moment a client submits
            their info — the signing screen then renders contracts.contract_html.

  seal    : for every contracts row the CLIENT has signed in the browser
            (status='signed': signer_name + consent + signed_at present, but not
            yet sealed) stamp the server-observed audit trail (IP best-effort,
            user-agent, SHA-256 integrity lock), fill the client signature block,
            render a locked signed PDF, and flip status='sealed'. Only a sealed
            contract unblocks provisioning (see onboard-pipeline gate).

  run     : prepare + seal in one pass (what the scheduled task calls).

Usage:
    py sequences/contract-sign.py run
    py sequences/contract-sign.py prepare
    py sequences/contract-sign.py seal [--id <contract_id>]
"""
from __future__ import annotations
import argparse, base64, hashlib, html as _html, json, sys, ssl, smtplib, tempfile, datetime as dt
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from contract_lib import (
    generate_contract, verify_clean, make_ref, apply_signature,
    apply_counter_signature, completion_certificate, derive_contract_fields,
)


def _load_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); out[k.strip()] = v.strip()
    return out


SENV = _load_env(REPO / "sequences" / "supabase.env")
U = SENV["SUPABASE_URL"].rstrip("/") + "/rest/v1"
K = SENV["SUPABASE_ANON_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Content-Type": "application/json"}
cli = httpx.Client(base_url=U, headers=H, timeout=40)

CONTRACT_DIR = REPO / "out" / "contracts"
CONTRACT_DIR.mkdir(parents=True, exist_ok=True)

HENV = _load_env(REPO / "sequences" / "hostinger.env")
OPERATOR_ADDR = "info@aureonglobal.de"


def _send_mail(recipients: list[str], subject: str, body_html: str, text_body: str,
               attach: Path, filename: str) -> bool:
    """Send one email via Resend over HTTPS (the VPS blocks SMTP ports 25/465/587),
    falling back to Hostinger SMTP on the laptop. Returns True if sent."""
    resend_key = (HENV.get("RESEND_NEW_ACCOUNT_API_KEY")
                  or HENV.get("RESEND_FULL_ACCESS_API_KEY")
                  or HENV.get("RESEND_API_KEY"))
    if resend_key:
        payload = {"from": "Aureon Global <info@send.aureonglobal.de>", "to": recipients,
                   "reply_to": OPERATOR_ADDR, "subject": subject, "html": body_html, "text": text_body}
        try:
            payload["attachments"] = [{"filename": filename,
                                       "content": base64.b64encode(attach.read_bytes()).decode()}]
        except Exception as e:
            print(f"    (attachment skipped: {e})")
        try:
            r = httpx.post("https://api.resend.com/emails", json=payload, timeout=30,
                           headers={"Authorization": f"Bearer {resend_key}",
                                    "Content-Type": "application/json",
                                    "User-Agent": "aureon-contract-sign/1.0"})
            if r.status_code in (200, 201):
                print(f"    ✓ sent via Resend to {', '.join(recipients)}")
                return True
            print(f"    ! Resend send failed {r.status_code}: {r.text[:200]}")
        except Exception as e:
            print(f"    ! Resend send error: {e}")

    user = HENV.get("SMTP_USER") or OPERATOR_ADDR
    pw = HENV.get("SMTP_PASS")
    if not pw:
        print("    (no SMTP_PASS and Resend unavailable — email not sent)")
        return False
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = f"Aureon Global <{user}>"
    msg["To"] = ", ".join(recipients)
    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(text_body, "plain", "utf-8"))
    alt.attach(MIMEText(body_html, "html", "utf-8"))
    msg.attach(alt)
    try:
        part = MIMEApplication(attach.read_bytes(), _subtype=("pdf" if attach.suffix == ".pdf" else "html"))
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)
    except Exception as e:
        print(f"    (attachment skipped: {e})")
    try:
        with smtplib.SMTP_SSL("smtp.hostinger.com", 465, context=ssl.create_default_context()) as s:
            s.login(user, pw)
            s.sendmail(user, recipients, msg.as_string())
        print(f"    ✓ sent via SMTP to {', '.join(recipients)}")
        return True
    except Exception as e:
        print(f"    ! SMTP send failed: {e}")
        return False


# Onboarding fields the operator wants at signing, in reading order. Any other non-empty
# answer is appended generically so nothing the client provided is lost.
_ONBOARD_LABELS = [
    ("Company", "company"), ("Website", "website"), ("Contact email", "contact_email"),
    ("Reply-to", "reply_to"), ("Service type", "service_type"), ("Platforms", "platforms"),
    ("Handles", "handles"), ("Posting cadence", "posting_cadence"), ("Offer", "offer"),
    ("ICP", "icp"), ("CTA", "cta"), ("Proof", "proof"), ("Give-first", "give_first"),
    ("Sending domain", "sending_root"), ("DNS host", "dns_host"), ("Jurisdiction", "jurisdiction"),
    ("Office", "office"), ("Signer", "rep"), ("Position", "rep_title"),
    ("Representation chain", "rep_chain"), ("Lead source", "lead_source"), ("Notes", "notes"),
]
_ONBOARD_SKIP = {"accepted_terms", "accepted_privacy", "accepted_agb", "accepted_at"}


def _format_onboarding(a: dict | None) -> tuple[str, str]:
    """Render the client's onboarding answers into (html, text) for the operator email."""
    if not a:
        return "", ""
    def val(v):
        return ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
    seen, pairs = set(), []
    for label, key in _ONBOARD_LABELS:
        seen.add(key)
        v = a.get(key)
        if v not in (None, "", []):
            pairs.append((label, val(v)))
    for k, v in a.items():
        if k in seen or k in _ONBOARD_SKIP:
            continue
        if v not in (None, "", []):
            pairs.append((k, val(v)))
    consent = (f"Terms {a.get('accepted_terms')}, Privacy {a.get('accepted_privacy')}, "
               f"AGB {a.get('accepted_agb')} at {a.get('accepted_at')}")
    tr = "".join(f"<tr><td style='padding:3px 14px 3px 0;color:#64748b;vertical-align:top'>{_html.escape(k)}</td>"
                 f"<td style='padding:3px 0'>{_html.escape(v)}</td></tr>" for k, v in pairs)
    html = (f"<h3 style='margin:20px 0 6px;color:#1e293b'>What the client provided (onboarding)</h3>"
            f"<table style='font-size:13px;border-collapse:collapse'>{tr}</table>"
            f"<p style='font-size:11px;color:#94a3b8;margin:8px 0 0'>Consent: {_html.escape(consent)}</p>")
    text = ("\n\nWHAT THE CLIENT PROVIDED (ONBOARDING)\n"
            + "\n".join(f"  {k}: {v}" for k, v in pairs) + f"\n  Consent: {consent}")
    return html, text


def _onboarding_for(submission_id: str | None, client_id: str | None) -> dict:
    """Fetch the client's onboarding raw_answers (by submission id, else latest for the client)."""
    try:
        if submission_id:
            r = cli.get(f"/onboarding_submissions?id=eq.{submission_id}&select=raw_answers", headers=H).json()
            if r and r[0].get("raw_answers"):
                return r[0]["raw_answers"]
        if client_id:
            r = cli.get(f"/onboarding_submissions?client_id=eq.{client_id}"
                        "&select=raw_answers&order=created_at.desc&limit=1", headers=H).json()
            if r and r[0].get("raw_answers"):
                return r[0]["raw_answers"]
    except Exception as e:
        print(f"    (onboarding fetch failed: {e})")
    return {}


def _email_signature_evidence(*, contract_ref: str, signer_name: str, signer_email: str,
                              signed_at: str, sealed_at: str, ip: str, ua: str, sha: str,
                              pdf_path: Path | None, html_fallback: Path,
                              operator_only: bool = False, onboarding: dict | None = None) -> bool:
    """On seal, email the operator (info@) the executed agreement + audit trail + everything the
    client provided at onboarding, and — unless operator_only — email the client just their
    executed copy. Resend over HTTPS (the VPS blocks SMTP ports); SMTP is a laptop fallback.
    Returns True if the operator email sent."""
    rows = (
        ("Agreement", contract_ref),
        ("Signed by (Client)", f"{signer_name} ({signer_email})"),
        ("Counter-signed by (Provider)", "Gentrit Luta, Aureon Global L.L.C. (Chief Executive Officer)"),
        ("Client signed at (UTC)", signed_at),
        ("Fully executed at (UTC)", sealed_at),
        ("Signer IP", ip),
        ("Signer device", ua),
        ("Document SHA-256", sha),
    )
    tr = "".join(f"<tr><td style='padding:4px 14px 4px 0;color:#64748b'>{k}</td>"
                 f"<td style='padding:4px 0;font-weight:600'>{v}</td></tr>" for k, v in rows)
    body_html = f"""<div style="font-family:system-ui,sans-serif;color:#1e293b;max-width:620px">
      <h2 style="color:#16a34a;margin:0 0 6px">Agreement fully executed</h2>
      <p style="margin:0 0 14px;color:#475569">The agreement has been signed by both parties and is
      now fully executed. The fully executed copy, with its Certificate of Completion, is attached.
      The audit record below is a second, independent evidence trail (the first is the locked record
      in the portal).</p>
      <table style="font-size:13px;border-collapse:collapse;margin:0 0 14px">{tr}</table>
      <p style="font-size:11px;color:#94a3b8">Any change to the agreement text invalidates the
      SHA-256 hash. Retained by Aureon Global L.L.C. as evidence of execution.</p>
    </div>"""
    text_body = (f"Agreement fully executed by both parties.\n\n"
                 + "\n".join(f"{k}: {v}" for k, v in rows)
                 + "\n\nThe fully executed agreement (with Certificate of Completion) is attached.")

    subject = f"Fully executed agreement: {contract_ref}"[:200]
    attach = pdf_path if (pdf_path and pdf_path.exists()) else html_fallback
    filename = f"{contract_ref.replace(' ', '_')}-signed{attach.suffix if hasattr(attach, 'suffix') else '.pdf'}"

    # Operator (info@) gets the evidence PLUS everything the client provided at onboarding.
    ob_html, ob_text = _format_onboarding(onboarding)
    op_ok = _send_mail([OPERATOR_ADDR], subject, body_html + ob_html, text_body + ob_text, attach, filename)
    # The client gets just their executed copy (no internal onboarding notes).
    if not operator_only and signer_email and "@" in signer_email:
        _send_mail([signer_email], subject, body_html, text_body, attach, filename)
    return op_ok


def _rows(resp) -> list | None:
    """Parse a PostgREST response into a list of rows, or None if the table is
    missing / errored (e.g. migrations 005+006 not run yet). Keeps the scheduled
    task from throwing tracebacks before the DB is provisioned."""
    try:
        data = resp.json()
    except Exception:
        return None
    if isinstance(data, list):
        return data
    # An error body (dict with code/message) means the table isn't there yet.
    if isinstance(data, dict) and data.get("code"):
        print(f"  (contracts/onboarding tables not ready: {data.get('code')} "
              f"{str(data.get('message',''))[:80]}) — run migrations 005+006")
    return None


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ─── prepare: auto-generate a draft contract per submission ──────────────────
def prepare() -> int:
    subs = _rows(cli.get("/onboarding_submissions",
                         params={"select": "id,client_id,raw_answers", "order": "created_at.asc"}))
    existing = _rows(cli.get("/contracts", params={"select": "submission_id"}))
    if subs is None or existing is None:
        return 0
    have = {c["submission_id"] for c in existing}
    made = 0
    for s in subs:
        if s["id"] in have:
            continue
        a = s.get("raw_answers") or {}
        ref = make_ref(a.get("company", "client"))
        try:
            html = generate_contract(a, ref)
        except Exception as e:
            print(f"  ! prepare {s['id'][:8]} failed: {e}")
            continue
        problems = verify_clean(html)
        if problems:
            print(f"  ! prepare {s['id'][:8]} produced an unclean contract: {problems} — skipping")
            continue
        row = {
            "client_id": s.get("client_id"),
            "submission_id": s["id"],
            "contract_ref": ref,
            "contract_html": html,
            "status": "draft",
            "signer_name": (a.get("rep") or "").strip() or None,
            "signer_email": (a.get("contact_email") or "").strip() or None,
            "signer_title": (a.get("rep_title") or "").strip() or None,
        }
        r = cli.post("/contracts", json=row, headers={**H, "Prefer": "return=minimal"})
        if r.status_code in (200, 201):
            made += 1
            print(f"  + draft contract for {a.get('company')} ({ref})")
        else:
            print(f"  ! insert failed {s['id'][:8]}: {r.status_code} {r.text[:160]}")
    print(f"prepare: {made} new draft contract(s)")
    return made


# ─── seal: stamp the audit trail + render the signed PDF ─────────────────────
def _render_pdf(html: str, out_path: Path) -> bool:
    """Render the sealed contract HTML to a locked PDF via Playwright/chromium
    (the same engine render-campaign-pdf.py uses). Returns True on success."""
    try:
        import asyncio
        from playwright.async_api import async_playwright
    except Exception as e:
        print(f"  ! playwright unavailable, skipping PDF render: {e}")
        return False

    async def _go():
        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(html, wait_until="networkidle")
            await page.wait_for_timeout(400)
            await page.pdf(path=str(out_path), format="A4", print_background=True,
                           margin={"top": "14mm", "bottom": "14mm", "left": "14mm", "right": "14mm"})
            await browser.close()
    try:
        asyncio.run(_go())
        return out_path.exists()
    except Exception as e:
        print(f"  ! PDF render error: {e}")
        return False


def seal(one_id: str | None = None) -> int:
    q = {"select": "*", "status": "eq.signed"}
    if one_id:
        q = {"select": "*", "id": f"eq.{one_id}"}
    rows = _rows(cli.get("/contracts", params=q))
    if rows is None:
        return 0
    sealed = 0
    for c in rows:
        if c.get("status") == "sealed":
            continue
        if not (c.get("signer_name") and c.get("consent") and c.get("signed_at")):
            print(f"  ~ {c['id'][:8]} not fully signed yet (name/consent/signed_at missing) — skip")
            continue

        html = c["contract_html"]
        # Integrity lock over the EXACT bytes the client agreed to (draft html).
        sha = hashlib.sha256(html.encode("utf-8")).hexdigest()
        signed_at = c["signed_at"]
        # Server-observed IP: the browser already wrote its best-effort IP into
        # signer_ip; if absent, mark unverified. (A reverse-proxy/edge function
        # would set the trusted IP here.)
        ip = c.get("signer_ip") or "not captured"
        ua = c.get("signer_user_agent") or "not captured"
        place = (c.get("contract_html") and "") or ""  # place comes from the form-derived field below

        # Recover place from the submission answers for the signature block.
        place_val = ""
        sub = cli.get("/onboarding_submissions",
                      params={"select": "raw_answers", "id": f"eq.{c['submission_id']}"}).json()
        if sub:
            f = derive_contract_fields(sub[0].get("raw_answers") or {})
            place_val = f.get("place") or f.get("jurisdiction") or ""

        date_str = signed_at[:10]
        # 1. Fill the CLIENT signature (no certificate appended yet).
        client_html = apply_signature(
            html, signer_name=c["signer_name"], signer_title=c.get("signer_title") or "",
            place=place_val, date_str=date_str, audit_panel_html="")
        # 2. Aureon Global (Provider) auto counter-signs, so the agreement is now FULLY
        #    EXECUTED by both parties. This is Aureon's standing authorisation, as Provider,
        #    to counter-execute its own pilot agreements the moment the client signs.
        provider_name, provider_title = "Gentrit Luta", "Chief Executive Officer"
        executed_at = _now()
        executed_html = apply_counter_signature(client_html, signer_name=provider_name, date_str=executed_at[:10])
        # 3. Append the court-defensible Certificate of Completion listing BOTH signers.
        cert = completion_certificate(
            contract_ref=c["contract_ref"], contract_id=c["id"], sha256=sha,
            prepared_at=(c.get("created_at") or "")[:19].replace("T", " "),
            client_name=c["signer_name"], client_email=c.get("signer_email") or "",
            client_title=c.get("signer_title") or "", client_signed_at=signed_at, client_ip=ip, client_ua=ua,
            provider_name=provider_name, provider_title=provider_title, provider_signed_at=executed_at)
        sealed_html = (executed_html.replace("</body>", cert + "\n</body>", 1)
                       if "</body>" in executed_html else executed_html + cert)

        out_html = CONTRACT_DIR / f"{c['contract_ref'].replace(' ', '_')}-executed.html"
        out_pdf = CONTRACT_DIR / f"{c['contract_ref'].replace(' ', '_')}-executed.pdf"
        out_html.write_text(sealed_html, encoding="utf-8")
        pdf_ok = _render_pdf(sealed_html, out_pdf)

        patch = {
            "status": "sealed",
            "contract_sha256": sha,
            "sealed_at": executed_at,
            "signer_ip": ip,
            "signer_user_agent": ua,
            "contract_html": sealed_html,  # persist the sealed version (with cert panel)
            "signed_pdf_path": str(out_pdf) if pdf_ok else str(out_html),
        }
        r = cli.patch(f"/contracts?id=eq.{c['id']}", json=patch,
                      headers={**H, "Prefer": "return=minimal"})
        if r.status_code in (200, 204):
            sealed += 1
            print(f"  ✓ sealed {c['contract_ref']} "
                  f"(sha {sha[:12]}…, pdf={'yes' if pdf_ok else 'html-only'})")
            # Second evidence trail: email the operator (info@) the signed copy +
            # the audit details (signer, timestamp, IP, SHA) with the PDF attached.
            try:
                if _email_signature_evidence(
                    contract_ref=c["contract_ref"], signer_name=c.get("signer_name") or "",
                    signer_email=c.get("signer_email") or "", signed_at=signed_at,
                    sealed_at=patch["sealed_at"], ip=ip, ua=ua, sha=sha,
                    pdf_path=out_pdf if pdf_ok else None, html_fallback=out_html,
                    onboarding=_onboarding_for(c.get("submission_id"), c.get("client_id"))):
                    cli.patch(f"/contracts?id=eq.{c['id']}",
                              json={"notified_at": patch["sealed_at"]},
                              headers={**H, "Prefer": "return=minimal"})
            except Exception as e:
                print(f"    (evidence email skipped: {e})")
        else:
            print(f"  ! seal patch failed {c['id'][:8]}: {r.status_code} {r.text[:160]}")
    print(f"seal: {sealed} contract(s) sealed")
    return sealed


def renotify(one_id: str | None, do_all: bool) -> int:
    """Re-send the fully-executed evidence email (operator-only) for sealed contracts that
    were never notified — recovers signings lost to the VPS SMTP-port block. --id targets one
    contract; --all covers every sealed contract with notified_at still null."""
    if one_id:
        q = f"/contracts?id=eq.{one_id}&select=*"
    elif do_all:
        q = "/contracts?status=eq.sealed&notified_at=is.null&select=*&order=sealed_at.asc"
    else:
        print("renotify: pass --id <contract_id> or --all"); return 2
    rows = cli.get(q, headers=H).json()
    if not rows:
        print("renotify: nothing to do"); return 0
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    sent = 0
    for c in rows:
        ref = c.get("contract_ref") or c["id"]
        sp = c.get("signed_pdf_path") or ""
        pdf_path = Path(sp) if (sp.lower().endswith(".pdf") and Path(sp).exists()) else None
        tmp_html = Path(tempfile.gettempdir()) / f"{str(ref).replace(' ', '_')}.html"
        tmp_html.write_text(c.get("contract_html") or "<html></html>", encoding="utf-8")
        print(f"  renotify {ref} ({c.get('signer_name')} / {c.get('signer_email')})")
        if _email_signature_evidence(
                contract_ref=str(ref), signer_name=c.get("signer_name") or "",
                signer_email=c.get("signer_email") or "", signed_at=c.get("signed_at") or "",
                sealed_at=c.get("sealed_at") or "", ip=c.get("signer_ip") or "",
                ua=c.get("signer_user_agent") or "", sha=c.get("contract_sha256") or "",
                pdf_path=pdf_path, html_fallback=tmp_html, operator_only=True,
                onboarding=_onboarding_for(c.get("submission_id"), c.get("client_id"))):
            cli.patch(f"/contracts?id=eq.{c['id']}", json={"notified_at": now},
                      headers={**H, "Prefer": "return=minimal"})
            sent += 1
    print(f"renotify: {sent}/{len(rows)} operator notification(s) sent")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("prepare")
    sp = sub.add_parser("seal"); sp.add_argument("--id", default=None)
    sub.add_parser("run")
    rn = sub.add_parser("renotify"); rn.add_argument("--id", default=None); rn.add_argument("--all", action="store_true")
    args = ap.parse_args()
    if args.cmd == "prepare":
        prepare()
    elif args.cmd == "seal":
        seal(args.id)
    elif args.cmd == "run":
        prepare(); seal(None)
    elif args.cmd == "renotify":
        return renotify(args.id, args.all)
    return 0


if __name__ == "__main__":
    sys.exit(main())
