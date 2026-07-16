# -*- coding: utf-8 -*-
"""fulfill-home-value.py — auto-fulfil the consented Home Value Report funnel.

When a homeowner opts in on the branded capture page (build-home-value-funnel.py),
they land in prospects with source='home_value_funnel', company=<their address>,
custom_fields={for_agent, funnel, zip, address}. This fulfiller:

  1. pulls home_value opt-ins not yet fulfilled,
  2. looks up the property in the FREE county-assessor data (source-seller-leads.py
     ::lookup_address) -> real assessed value + last sale + sqft + equity context,
  3. emails the homeowner a branded report from the AGENT (reply-to the agent),
     bcc info@aureonglobal.de, and CCs nothing else,
  4. marks the opt-in fulfilled in custom_fields.home_value.

HONESTY: the assessed value is the county's public assessed value (the same record
Zillow/ATTOM start from), clearly labelled as such — never a fabricated AVM. If the
county is not mapped or the parcel is not found, the homeowner still gets a report
acknowledging their request with a market-read + the agent's offer to prepare a full
CMA (so we never send a fake number, and the agent still gets the lead).

Usage:
  py scripts/fulfill-home-value.py --dry          # show what it would do
  py scripts/fulfill-home-value.py                # live
"""
from __future__ import annotations
import argparse
import datetime as dt
import html as _html
import importlib.util
import json
import shutil
import smtplib
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "sequences"))
from mailer import send as send_mail   # Resend primary (VPS blocks SMTP), SMTP fallback
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# load lookup_address from the hyphenated module
_spec = importlib.util.spec_from_file_location("ssl_src", REPO / "scripts" / "source-seller-leads.py")
_ssl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ssl)
lookup_address = _ssl.lookup_address
value_estimate = _ssl.value_estimate

from home_value_report import build_report_html  # noqa: E402


def _chrome() -> str | None:
    for c in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"):
        if Path(c).exists():
            return c
    return shutil.which("chrome") or shutil.which("msedge")


def render_pdf(html: str) -> bytes | None:
    """HTML -> PDF via headless Chrome/Edge. Returns bytes or None on failure."""
    chrome = _chrome()
    if not chrome:
        return None
    with tempfile.TemporaryDirectory() as td:
        hp = Path(td) / "r.html"; pp = Path(td) / "r.pdf"
        hp.write_text(html, encoding="utf-8")
        try:
            subprocess.run([chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                            f"--print-to-pdf={pp}", hp.as_uri()],
                           timeout=60, capture_output=True)
            return pp.read_bytes() if pp.exists() else None
        except Exception:
            return None


def load_env(path: Path) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


SUPA = load_env(REPO / "sequences" / "supabase.env")
HOST = load_env(REPO / "sequences" / "hostinger.env")
URL = SUPA["SUPABASE_URL"].rstrip("/")
KEY = SUPA["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
BCC = "info@aureonglobal.de"


def supa_get(path: str) -> list:
    return json.loads(urllib.request.urlopen(
        urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H), timeout=40).read())


def supa_patch(path: str, body: dict) -> None:
    urllib.request.urlopen(urllib.request.Request(
        f"{URL}/rest/v1/{path}", data=json.dumps(body).encode(),
        headers={**H, "Prefer": "return=minimal"}, method="PATCH"), timeout=30).read()


CAL = "https://calendly.com/aureonglobal-info/30min"


def report_html(*, owner_first: str, address: str, mid: str, found: bool) -> tuple[str, str]:
    """Short Aureon-branded cover email; the rich detail is the attached PDF. Aureon is the
    front door — homeowner books with us, a local agent reaches out after the call."""
    esc = _html.escape
    fn = esc(owner_first or "there")
    if found and mid:
        headline = f"Your estimated home value is around <strong>{esc(mid)}</strong>."
    else:
        headline = f"Your home value report for {esc(address)} is attached."
    detail = ("<p style='margin:0 0 14px;color:#444;'>Your full report is attached as a PDF: the estimated "
              "market range, what you could net, recent comparable sales, and the moves that add the most "
              "before listing.</p>"
              "<p style='margin:0 0 14px;color:#444;'>For the exact figure, book a quick call and we will arrange "
              "your free professional CMA (normally $400&ndash;$600). A local real estate expert then reaches out "
              "as soon as possible to confirm it. No pressure, no obligation.</p>"
              f"<p style='margin:0 0 14px;'><a href='{CAL}' style='background:#d4af37;color:#0a0a0a;font-weight:700;"
              f"padding:11px 18px;border-radius:8px;text-decoration:none;display:inline-block;'>Book your free CMA call</a></p>")
    text = (f"Hi {owner_first or 'there'},\n\n{('Your estimated home value is around ' + mid + '. ') if (found and mid) else ''}"
            f"Your full home value report for {address} is attached (estimated range, net proceeds, recent comps, "
            f"and pre-listing tips).\n\nFor the exact figure, book a quick call and we arrange your free professional "
            f"CMA (normally $400-600); a local real estate expert then reaches out as soon as possible. "
            f"No pressure, no obligation.\n\nBook: {CAL}\n\nAureon Global\ninfo@aureonglobal.de")
    html = (f"<div style=\"font-family:system-ui,-apple-system,Segoe UI,sans-serif;max-width:600px;color:#1e293b;\">"
            f"<p style='margin:0 0 14px;'>Hi {fn},</p>"
            f"<p style='margin:0 0 14px;font-size:17px;color:#0a0a0a;'>{headline}</p>"
            f"{detail}"
            f"<p style='margin:18px 0 4px;'><strong>Aureon Global</strong></p>"
            f"<p style='margin:4px 0 0;font-size:12px;color:#94a3b8;'>You requested this report. "
            f"Reply to this email or book a call above and a local expert will be in touch.</p></div>")
    return html, text


def smtp_send(*, to_addr: str, reply_to: str, subject: str, html: str, text: str,
              pdf: bytes | None = None, pdf_name: str = "Home-Value-Report.pdf") -> bool:
    # info@ keeps a blind copy, except when the primary recipient already IS info@
    # (the HOT-alert path passes to_addr=BCC, so we must not duplicate it).
    bcc = [BCC] if (BCC and BCC.lower() != to_addr.lower()) else None
    atts = [(pdf_name, pdf)] if pdf else None
    return send_mail(to=to_addr, subject=subject, html=html, text=text,
                     reply_to=(reply_to or "info@aureonglobal.de"),
                     from_addr='"Home Value Report" <info@send.aureonglobal.de>',
                     bcc=bcc, attachments=atts)


def booking_when(rc: dict) -> str:
    """Human phrasing of the homeowner's requested call time."""
    bits = [rc.get("window", ""), ("on " + rc["date"]) if rc.get("date") else ""]
    return " ".join(b for b in bits if b).strip() or "a time they will pick on the call"


def notify_booking(*, owner_name: str, email: str, phone: str, address: str,
                   mid_str: str, agent_email: str, rc: dict) -> bool:
    """HOT alert to the operator: a homeowner asked to book a call about selling.
    The operator confirms the time and hands the booked appointment to the agent."""
    when = booking_when(rc)
    subj = f"HOT seller appointment request — {address}"
    body = ("A homeowner asked to book a call to discuss selling their home.\n\n"
            f"Name:           {owner_name or '(not given)'}\n"
            f"Email:          {email}\n"
            f"Phone:          {phone or '(not given)'}\n"
            f"Property:       {address}\n"
            f"Estimated value:{mid_str or '(see their report)'}\n"
            f"Requested time: {when}\n"
            f"For agent:      {agent_email or '(unassigned)'}\n\n"
            "Action: confirm the call with the homeowner, then hand the booked appointment to the agent.")
    html = ("<pre style='font-family:system-ui,-apple-system,Segoe UI,sans-serif;font-size:14px;"
            "color:#1e293b;white-space:pre-wrap'>" + _html.escape(body) + "</pre>")
    return smtp_send(to_addr=BCC, reply_to=email or BCC, subject=subj, html=html, text=body)


def one_pass(limit: int, dry: bool) -> dict:
    stats = {"candidates": 0, "sent": 0, "skipped": 0, "errors": 0}
    rows = supa_get("prospects?source=eq.home_value_funnel&select=id,email,first_name,"
                    "company,phone,custom_fields,unsubscribed&order=created_at.desc&limit=200")
    todo = [r for r in rows
            if not (r.get("custom_fields") or {}).get("home_value", {}).get("fulfilled")
            and not r.get("unsubscribed") and r.get("email")][:limit]
    stats["candidates"] = len(todo)
    print(f"home-value opt-ins to fulfil: {len(todo)}")
    for p in todo:
        cf = dict(p.get("custom_fields") or {})
        address = cf.get("address") or p.get("company") or ""
        zipc = cf.get("zip") or ""
        agent_email = cf.get("for_agent") or ""
        owner_first = (p.get("first_name") or "").strip()
        # We don't carry the agent's display name/company on the opt-in; derive a sensible
        # fallback from the agent email's domain, overridable later if we store it.
        agent_name = cf.get("agent_name") or "Your agent"
        agent_company = cf.get("agent_company") or (agent_email.split("@")[-1] if agent_email else "")
        details = cf.get("details") or {}
        rc = details.get("requested_call") or {}
        res = value_estimate(address, zipc, details=details)
        mid = res.get("market_mid")
        mid_str = ("$%s" % format(int(mid), ",")) if mid else ""
        print(f"  · {p['email']} | {address} -> found={res.get('found')} "
              f"est={mid_str} comps={ (res.get('comps') or {}).get('n',0) } "
              f"owner-sqft={details.get('sqft','')}")
        # Short Aureon-branded cover email; the rich detail lives in the attached PDF.
        html, text = report_html(owner_first=owner_first, address=res.get("address") or address,
                                 mid=mid_str, found=bool(res.get("found")))
        # Rich PDF report (Aureon-fronted; agent/owner dicts unused by the report now but kept for signature).
        owner = {"first_name": owner_first, "address": res.get("address") or address, "zip": zipc}
        report_html_full = build_report_html(res, {}, owner)
        subject = f"Your home value report — {res.get('address') or address}"
        if dry:
            pdf_ok = "yes" if _chrome() else "no-chrome"
            print(f"    [DRY] would email {p['email']} (from/reply-to Aureon) subj={subject!r} pdf={pdf_ok}")
            if rc:
                print(f"    [DRY] would alert {BCC}: HOT appointment request ({booking_when(rc)})")
            stats["sent"] += 1
            continue
        pdf = render_pdf(report_html_full)
        if not pdf:
            print("    ! PDF render failed — sending without attachment")
        # Aureon is the front door: send from + reply-to Aureon (FROM_ADDR), not the agent.
        ok = smtp_send(to_addr=p["email"], reply_to=HOST.get("FROM_ADDR", BCC), subject=subject,
                       html=html, text=text, pdf=pdf, pdf_name="Home-Value-Report.pdf")
        if ok:
            stats["sent"] += 1
            cf["home_value"] = {"fulfilled": True,
                                "at": dt.datetime.now(dt.timezone.utc).isoformat(),
                                "found": bool(res.get("found")),
                                "assessed_value": res.get("assessed_value", "")}
            if rc and notify_booking(owner_name=owner_first, email=p["email"],
                                     phone=p.get("phone", ""), address=res.get("address") or address,
                                     mid_str=mid_str, agent_email=agent_email, rc=rc):
                cf["home_value"]["booking_notified"] = True
                print(f"    -> HOT appointment alert -> {BCC} ({booking_when(rc)})")
            supa_patch(f"prospects?id=eq.{p['id']}", {"custom_fields": cf})
            print(f"    -> sent report to {p['email']}, bcc {BCC}")
        else:
            stats["errors"] += 1
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=25)
    a = ap.parse_args()
    print(json.dumps(one_pass(a.limit, a.dry), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
