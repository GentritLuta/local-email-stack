# -*- coding: utf-8 -*-
"""build-seller-mailers.py — print-ready direct mail to motivated sellers.

The free, legal, no-skip-trace channel (see docs/SELLER_ENGINE_BLUEPRINT.md). The
county assessor gives every owner's MAILING ADDRESS for free, so we mail the owner a
personal letter that drives them to the agent's home-value page (the funnel), where
they get their value and opt in / book — routed straight to the agent. No phone/email
append, no skip-trace, no TCPA: direct mail is unregulated and the funnel opt-in is
consented.

Leads come from scripts/source-seller-leads.py (absentee owners carry owner name +
mailing address; FSBO carries the property + listing). Output: a print-ready PDF (one
mailer per page) + a CSV manifest. Print and mail, or hand the PDF to a mail house.

  py scripts/build-seller-mailers.py --zip 47383 --agent-slug austin-elite \\
     --agent-name Austin --agent-company "My Next Home Elite" --limit 25
"""
from __future__ import annotations
import argparse
import csv
import html as _html
import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

REPO = Path(__file__).resolve().parent.parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PAGES_BASE = "https://gentritluta.github.io/local-email-stack/home-value"
OUT_DIR = REPO / "out" / "seller-mailers"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_spec = importlib.util.spec_from_file_location("ssl_src", REPO / "scripts" / "source-seller-leads.py")
_ssl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ssl)


def title_name(n: str) -> str:
    n = re.sub(r"\s+", " ", (n or "").strip())
    return " ".join(w.capitalize() for w in n.split()) if n else ""


def mailing_address(lead: dict) -> str:
    """Absentee leads encode the owner's mailing address in `source` as
    'Owner mailing: <ADDR> | phone: <url>'. Pull just the address."""
    src = lead.get("source") or ""
    m = re.search(r"owner mailing:\s*(.+?)(?:\s*\|\s*phone:|$)", src, re.I)
    return m.group(1).strip() if m else ""


def qr_img(url: str) -> str:
    """Inline fixed-size QR (PNG data-uri) so the homeowner can scan straight to
    their value page. Uses segno if installed; any failure -> '' (letter shows the URL).
    PNG sized to the 104px box so it can never overflow regardless of URL length."""
    try:
        import base64
        import io
        import segno  # pure-python, no Pillow needed for PNG
        qr = segno.make(url, error="m")
        cols = qr.symbol_size(scale=1, border=0)[0]          # module count
        scale = max(2, round(108 / cols))                    # ~box-sized
        buf = io.BytesIO()
        qr.save(buf, kind="png", scale=scale, border=0, dark="#1e293b")
        b64 = base64.b64encode(buf.getvalue()).decode()
        return f'<img src="data:image/png;base64,{b64}" style="width:104px;height:104px;display:block">'
    except Exception:
        return ""


def mailer_html(*, owner: str, mail_addr: str, prop_addr: str, signal: str,
                agent_name: str, agent_company: str, url: str) -> str:
    esc = _html.escape
    qr = qr_img(url)
    prop_city = (prop_addr.split(",")[1].strip() if prop_addr.count(",") >= 1 else "your area")
    mail_city = (mail_addr.split(",")[1].strip() if mail_addr.count(",") >= 1 else "")
    # proper mailing block: street on line 1, "city, state zip" on line 2
    _ap = mail_addr.split(", ", 1)
    addr_html = (esc(_ap[0]) + "<br>" + esc(_ap[1])) if len(_ap) == 2 else (esc(mail_addr) or "(mailing address)")
    if signal == "absentee owner" and mail_city:
        hook = (f"I work with homeowners around {esc(prop_city)}, and I noticed you own the property "
                f"at {esc(prop_addr)} but receive your mail in {esc(mail_city)}.")
    elif signal == "fsbo":
        hook = (f"I saw your property at {esc(prop_addr)} is for sale by owner.")
    else:
        hook = f"I work with homeowners around {esc(prop_city)} and came across your property at {esc(prop_addr)}."
    return f"""<!doctype html><meta charset=utf-8><body style="margin:0;font-family:Georgia,'Times New Roman',serif;color:#1e293b">
<div style="width:8.5in;height:11in;padding:1in 1.1in;box-sizing:border-box">
  <div style="font-size:15pt;font-weight:bold;color:#0f172a">{esc(agent_company)}</div>
  <div style="font-size:10pt;color:#64748b;margin-bottom:38px">{esc(agent_name)}</div>

  <div style="font-size:11pt;line-height:1.4;margin-bottom:34px">
    {esc(owner) or "Current Owner"}<br>{addr_html}
  </div>

  <p style="font-size:12pt;line-height:1.65">Hello,</p>
  <p style="font-size:12pt;line-height:1.65">{hook}</p>
  <p style="font-size:12pt;line-height:1.65">If you have ever wondered what it is worth in today's
    market, I put together a free, no-obligation home value report you can see in about a minute.
    No phone call, no pressure, no salesperson. Just your number.</p>
  <div style="display:flex;align-items:center;gap:26px;margin:30px 0;padding:18px 22px;border:1px solid #e2e8f0;border-radius:10px">
    <div style="width:104px;height:104px;flex:none">{qr or ''}</div>
    <div>
      <div style="font-size:12pt;font-weight:bold">See your home's value</div>
      <div style="font-size:11pt;color:#334155;margin-top:4px">{'Scan the code, or visit:' if qr else 'Visit:'}</div>
      <div style="font-size:11.5pt;color:#1d4ed8;margin-top:3px">{esc(url)}</div>
    </div>
  </div>
  <p style="font-size:12pt;line-height:1.65">If selling is not on your mind right now, no problem at
    all, keep the number for whenever it is.</p>
  <p style="font-size:12pt;line-height:1.65;margin-top:30px">Warm regards,<br><br>
    {esc(agent_name)}<br>{esc(agent_company)}</p>
</div></body>"""


def render_pdf(html: str) -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html); src = f.name
    out = Path(tempfile.mktemp(suffix=".pdf"))
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={out}", "file:///" + src.replace("\\", "/")],
                   capture_output=True, timeout=90)
    Path(src).unlink(missing_ok=True)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--agent-slug", required=True, help="the agent's home-value page slug")
    ap.add_argument("--agent-name", required=True)
    ap.add_argument("--agent-company", required=True)
    ap.add_argument("--limit", type=int, default=25)
    a = ap.parse_args()

    url = f"{PAGES_BASE}/{_html.escape(a.agent_slug, quote=False)}.html"
    print(f"sourcing motivated sellers in {a.zip} ...")
    res = _ssl.source_seller_leads(a.zip, limit=max(a.limit * 2, 10))
    leads = res.get("leads", [])
    # mailable = we have an owner name OR a mailing address (absentee), or a FSBO property
    mailers, manifest = [], []
    for l in leads:
        owner = title_name(l.get("owner_name"))
        mail = mailing_address(l)
        prop = l.get("address") or ""
        sig = l.get("signal") or ""
        # need somewhere to mail: absentee -> owner's mailing address; FSBO -> the property itself
        mailto = mail or prop
        if not mailto:
            continue
        mailers.append(mailer_html(owner=owner, mail_addr=mailto, prop_addr=prop, signal=sig,
                                   agent_name=a.agent_name, agent_company=a.agent_company, url=url))
        manifest.append({"owner": owner, "mailing_address": mailto, "property": prop,
                         "signal": sig, "url": url})
        if len(mailers) >= a.limit:
            break

    if not mailers:
        print(f"  no mailable leads for {a.zip} (coverage {res.get('coverage')}).")
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    final, tmp = fitz.open(), []
    for h in mailers:
        p = render_pdf(h); tmp.append(p); final.insert_pdf(fitz.open(p))
    pdf_out = OUT_DIR / f"mailers-{a.agent_slug}-{a.zip}.pdf"
    final.save(pdf_out); final.close()
    for p in tmp:
        Path(p).unlink(missing_ok=True)
    csv_out = OUT_DIR / f"mailers-{a.agent_slug}-{a.zip}.csv"
    with open(csv_out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["owner", "mailing_address", "property", "signal", "url"])
        w.writeheader(); w.writerows(manifest)
    print(f"-> {pdf_out}  ({len(mailers)} print-ready mailers)")
    print(f"-> {csv_out}  (manifest)")
    print(f"   drives owners to {url}. Print + mail, or hand the PDF to a mail house.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
