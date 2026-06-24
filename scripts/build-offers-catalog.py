# -*- coding: utf-8 -*-
"""build-offers-catalog.py, compile ONE PDF cataloguing every client's give-first
offer: an overview table, then for each client an offer divider page followed by
the actual visual deliverable a prospect receives (the real PDF pages merged in,
vector, not rasterised). Distinguishes LIVE offers from the newly built ones.

    py scripts/build-offers-catalog.py   ->  out/Aureon-Client-Offers-Catalog-v3.pdf
"""
from __future__ import annotations
import glob
import html as H
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import fitz  # PyMuPDF

REPO = Path(__file__).resolve().parent.parent
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUT = REPO / "out" / "Aureon-Client-Offers-Catalog-v3.pdf"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

specs = {s["client_slug"]: s for s in
         json.loads((REPO / "lead-magnets" / "magnet-specs.json").read_text(encoding="utf-8"))}


def render_html(html: str) -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html); src = f.name
    out = Path(tempfile.mktemp(suffix=".pdf"))
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                    "--user-data-dir=" + str(REPO / "out" / "_chrome_tmp"),
                    "--no-pdf-header-footer", f"--print-to-pdf={out}",
                    "file:///" + src.replace("\\", "/")], capture_output=True, timeout=90)
    Path(src).unlink(missing_ok=True)
    return out


def deliver_pdf(slug: str) -> Path | None:
    hits = sorted(glob.glob(str(REPO / "lead-magnets" / f"{slug}--*.pdf")))
    return Path(hits[0]) if hits else None


# ── catalogue entries: (client, accent, status, offers[]) ──
referral_sample = (
    "<table style='width:100%;border-collapse:collapse;font-size:9pt;margin-top:6px'>"
    "<tr style='background:#f3f3f3'><th style='border:1px solid #ddd;padding:5px 7px;text-align:left'>Firm</th>"
    "<th style='border:1px solid #ddd;padding:5px 7px;text-align:left'>Lead attorney</th>"
    "<th style='border:1px solid #ddd;padding:5px 7px;text-align:left'>Phone</th></tr>"
    "<tr><td style='border:1px solid #ddd;padding:5px 7px'>H.G. Myers Law</td><td style='border:1px solid #ddd;padding:5px 7px'>Heather L. George Myers</td><td style='border:1px solid #ddd;padding:5px 7px'>317-643-5496</td></tr>"
    "<tr><td style='border:1px solid #ddd;padding:5px 7px'>Walterman Legal</td><td style='border:1px solid #ddd;padding:5px 7px'>Joseph B. Walterman</td><td style='border:1px solid #ddd;padding:5px 7px'>317-953-2281</td></tr>"
    "</table>")

# Each offer: (keyword, free_value, title, deliverable_slug_or_None, extra_html)
ENTRIES = [
    ("Diraya", "#6d28d9", "LIVE", [
        ("GHOSTS", "A list of 40 production-killer AI edge cases, each with the failure mode and the eval that catches it.",
         "The Agent Ghost-Cases List", "__diraya_ghosts", ""),
        ("REVIEW", "A written architecture review: reference build, the three killer risks, an 8-week timeline. Tailored version is the human follow-up.",
         "Your AI Feature: A Reference Architecture Review", "__diraya_review", ""),
    ]),
    ("Aureon (real-estate agents)", "#b8922c", "LIVE", [
        ("LIST / PROBATE", "A curated, hand-verified attorney referral list for the agent's metro (14 metros built). A real spreadsheet they can call down.",
         "Attorney Referral List (per metro)", None,
         "<p style='font-size:9.5pt;color:#444'>Each row: firm, lead attorney, practice focus, city, a direct phone for every firm, website and full address. Sample (Indianapolis, 30 firms):</p>" + referral_sample),
        ("(give-first cold)", "Free motivated-seller leads sourced in the agent's ZIP, before any ask. Delivered to 5 agents so far.",
         "Seller-Test motivated-seller list", None,
         "<p style='font-size:9.5pt;color:#444'>The cold email offers to source motivated sellers in the agent's farm area for free. On a yes, the leads are sourced and delivered and the booked listing appointment routes to the agent.</p>"),
        ("(home-value funnel)", "A free home-value report for a homeowner who opts in on the capture page.",
         "Home Value Report", None,
         "<p style='font-size:9.5pt;color:#444'>Property facts, recent comparable sales, your local market with evidence, and what you could walk away with (equity, net proceeds). Built from public county-assessor data with a disclaimer. Note: 0 opt-ins so far, no traffic yet.</p>"),
    ]),
    ("AlgoAlpha", "#caa200", "LIVE", [
        ("(reply to the cold email)", "The personalised offer itself: a flat fee per video computed live from the creator's last-10-video average views, plus 30% lifetime commission.",
         "Personalised retainer quote + creator-signup page", None,
         "<p style='font-size:9.5pt;color:#444'>The give is the number, not a PDF. The system reads the last-10-video average views and quotes a flat per-video fee (10 USD per 1,000 of that average) plus 30% lifetime commission. A free signup page captures interested creators. The rate stays internal.</p>"),
    ]),
]
# the new ones, from specs (each has a real visual deliverable PDF)
for slug in ["mark-eting", "lk-advertising", "atalsolidrocks", "dorian", "energ"]:
    sp = specs[slug]
    ENTRIES.append((slug, sp.get("accent_hex", "#222"), "NEW", [
        (", ".join(sp["magnet_keywords"]), sp["one_line_promise"], sp["deliverable_title"], slug, "")
    ]))


def overview_rows() -> str:
    rows = []
    for client, _acc, status, offers in ENTRIES:
        for kw, _fv, title, _slug, _x in offers:
            rows.append(f"<tr><td>{H.escape(client)}</td><td>{H.escape(kw)}</td>"
                        f"<td>{H.escape(title)}</td><td>{H.escape(status)}</td></tr>")
    return "".join(rows)


def divider_html(client, acc, status, kw, fv, title, extra) -> str:
    return f"""<!doctype html><meta charset=utf-8><body style="margin:0;font-family:-apple-system,'Segoe UI',Arial,sans-serif;color:#1b1b1b">
<div style="padding:22mm 18mm">
 <div style="border-bottom:3px solid {acc};padding-bottom:8px;display:flex;justify-content:space-between;align-items:center">
   <div style="font-size:21pt;font-weight:800;color:{acc}">{H.escape(client)}</div>
   <span style="font-size:9pt;background:{acc};color:#fff;padding:4px 11px;border-radius:12px">{H.escape(status)}</span>
 </div>
 <div style="font-size:11pt;font-weight:800;color:{acc};margin-top:16px">Reply: {H.escape(kw)}</div>
 <div style="margin:6px 0 14px"><b>Free value:</b> {H.escape(fv)}</div>
 <div style="background:#fafafa;border-left:3px solid {acc};padding:11px 14px;border-radius:8px">
   <div style="font-size:8pt;letter-spacing:.12em;text-transform:uppercase;color:#888;font-weight:700">What the prospect receives</div>
   <div style="font-size:13pt;font-weight:700;margin-top:3px">{H.escape(title)}</div>
   {extra}
   {'<div style="font-size:9pt;color:#888;margin-top:10px">The full deliverable follows on the next pages.</div>' if extra=='' else ''}
 </div>
</div></body>"""


def cover_overview_html() -> str:
    n_off = sum(len(o) for _, _, _, o in ENTRIES)
    return f"""<!doctype html><meta charset=utf-8><body style="margin:0;font-family:-apple-system,'Segoe UI',Arial,sans-serif;color:#1b1b1b">
<div style="padding:60mm 18mm 0;page-break-after:always">
 <div style="font-size:30pt;font-weight:800">Aureon Global</div>
 <div style="font-size:13pt;color:#555;margin-top:6px">Client Give-First Offers &amp; Deliverables, the full catalogue</div>
 <div style="font-size:10pt;color:#777;margin-top:14px">Every client's free-value offer, the reply keyword that triggers it, and the exact deliverable a prospect receives, with each visual deliverable shown in full. {len(ENTRIES)} clients, {n_off} offers.</div>
</div>
<div style="padding:16mm 18mm">
 <div style="font-size:16pt;font-weight:800;margin-bottom:8px">Overview</div>
 <table style="width:100%;border-collapse:collapse;font-size:9.5pt">
   <tr style="background:#f3f3f3"><th style="border:1px solid #ddd;padding:6px 8px;text-align:left">Client</th><th style="border:1px solid #ddd;padding:6px 8px;text-align:left">Reply keyword</th><th style="border:1px solid #ddd;padding:6px 8px;text-align:left">Deliverable</th><th style="border:1px solid #ddd;padding:6px 8px;text-align:left">Status</th></tr>
   {overview_rows()}
 </table>
</div></body>"""


def main() -> int:
    tmp = []
    final = fitz.open()
    # cover + overview
    p = render_html(cover_overview_html()); tmp.append(p); final.insert_pdf(fitz.open(p))
    diraya_pdf = {"__diraya_ghosts": REPO / "lead-magnets" / "Diraya-Agent-Ghost-Cases-List.pdf",
                  "__diraya_review": REPO / "lead-magnets" / "Diraya-Architecture-Review.pdf"}
    for client, acc, status, offers in ENTRIES:
        for kw, fv, title, slug, extra in offers:
            d = render_html(divider_html(client, acc, status, kw, fv, title, extra))
            tmp.append(d); final.insert_pdf(fitz.open(d))
            pdf = diraya_pdf.get(slug) if slug and slug.startswith("__") else (deliver_pdf(slug) if slug else None)
            if pdf and Path(pdf).exists():
                final.insert_pdf(fitz.open(pdf))
    final.save(OUT)
    final.close()
    for t in tmp:
        Path(t).unlink(missing_ok=True)
    d = fitz.open(OUT)
    print(f"-> {OUT}  ({OUT.stat().st_size//1024} KB, {len(d)} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
