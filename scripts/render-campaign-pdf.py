# -*- coding: utf-8 -*-
"""render-campaign-pdf.py — render any profile's 7-email sequence into a
branded presentation PDF (cover + ICP summary + all 7 emails as pages),
plus per-email PNG previews and a contact-sheet.

Reuses the live render pipeline (sequences/email_render.py + the profile's
custom template), so the PDF shows EXACTLY what prospects receive.

    py scripts/render-campaign-pdf.py <profile_slug> [variants_dir]

Example:
    py scripts/render-campaign-pdf.py energ energ-default

Output: out/<slug>-sequence/
  - email-1..7.html / email-1..7.png  (single emails)
  - preview-all.png                   (contact sheet)
  - <Brand>-Email-Campaign.pdf        (the deliverable to present)

One combined HTML doc -> one page.pdf() call (CSS page-breaks), so no extra
PDF-merge dependency is needed.
"""
from __future__ import annotations
import asyncio
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from email_render import render_html  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

# Locale-appropriate demo prospect so the preview reads naturally per market.
DEMO_DE = {"first_name": "Herr Bergmann", "company": "Hartmann Logistik GmbH",
           "brokerage": "", "city": "Düsseldorf", "state": ""}
DEMO_US = {"first_name": "Jordan", "company": "Summit Realty Group",
           "brokerage": "your current brokerage", "city": "Phoenix", "state": "AZ"}
ART = re.compile(r"\{[a-z_]+\}")


def pick_demo(prof: dict) -> dict:
    tz = (prof.get("send_window", {}) or {}).get("default_timezone", "")
    return DEMO_DE if tz.startswith("Europe") else DEMO_US


def merge(s: str, demo: dict) -> str:
    out = s
    for k, v in demo.items():
        out = out.replace("{" + k + "}", v)
    return out


def load(slug: str, variants_dir: str):
    prof = json.loads((REPO / "profiles" / f"{slug}.json").read_text(encoding="utf-8"))
    variants = json.loads((REPO / "sequences" / variants_dir / "variants.json").read_text(encoding="utf-8"))
    return prof, variants


def build_emails(prof: dict, variants: dict):
    brand = prof["brand"]
    persona = prof["personas"][0]
    demo = pick_demo(prof)
    out = []
    for v in variants["variants"]:
        subj = merge(v["subject"], demo)
        body = merge(v["body"], demo)
        html = render_html(body=body, persona=persona, unsubscribe_token="preview",
                           brand=brand, step_n=v["n"])
        leftover = ART.findall(subj) + ART.findall(body)
        if leftover:
            print(f"  WARN step{v['n']}: unrendered {leftover}")
        out.append((v["n"], subj, v.get("delay_days", 0), html))
    return out


def _inner_body(html: str) -> str:
    return html.split("<body", 1)[1].split(">", 1)[1].rsplit("</body>", 1)[0]


def cover_section(prof: dict, variants: dict) -> str:
    b = prof["brand"]
    c = b["colors"]
    wordmark = b.get("wordmark", prof.get("slug", "").upper())
    tagline = b.get("tagline", "")
    site = b.get("site", "")
    name = prof.get("name", "")
    target = variants.get("target", "")
    of = variants.get("offer_facts", {})
    proofs = of.get("proof_points", [])
    diffs = of.get("differentiators", [])
    lm1 = of.get("lead_magnet_primary", "")
    lm2 = of.get("lead_magnet_secondary", "")
    n_emails = len(variants.get("variants", []))
    accent = c.get("accent", "#16A34A")
    # Cover + estimate pages always render on WHITE, so use solid dark text
    # regardless of the brand's own (possibly light, for dark-themed emails)
    # text colors. This keeps the prose crisp black instead of faint/transparent.
    ink = "#111111"
    body_c = "#2A2A2A"
    muted = "#6B7280"

    def li(items):
        return "".join(
            f'<li style="margin:0 0 7px 0;font-size:12.5px;line-height:1.5;color:{body_c};">{x}</li>'
            for x in items)

    return f"""
<section class="page">
  <div style="font-size:12px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:{accent};">E-Mail-Kampagne</div>
  <div style="font-size:44px;font-weight:800;letter-spacing:-1px;margin:8px 0 4px 0;color:{ink};">{wordmark}<span style="color:{accent};">.</span></div>
  <div style="font-size:16px;color:{muted};font-weight:500;">{tagline}</div>
  <div style="height:3px;width:80px;background:{accent};margin:20px 0;"></div>
  <div style="font-size:13px;color:{body_c};line-height:1.6;">{name}</div>

  <div style="margin-top:26px;">
    <div style="font-size:11.5px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{ink};margin-bottom:7px;">Zielgruppe (ICP)</div>
    <div style="font-size:12.5px;color:{body_c};line-height:1.55;">{target}</div>
  </div>

  <table style="width:100%;margin-top:24px;border-collapse:collapse;"><tr>
    <td style="vertical-align:top;width:50%;padding-right:18px;">
      <div style="font-size:11.5px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{ink};margin-bottom:7px;">Beweise</div>
      <ul style="margin:0;padding-left:18px;">{li(proofs)}</ul>
    </td>
    <td style="vertical-align:top;width:50%;padding-left:18px;">
      <div style="font-size:11.5px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{ink};margin-bottom:7px;">Differenzierung</div>
      <ul style="margin:0;padding-left:18px;">{li(diffs)}</ul>
    </td>
  </tr></table>

  <div style="margin-top:24px;padding:16px 18px;background:#F4F5F4;border-left:3px solid {accent};">
    <div style="font-size:11.5px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{ink};margin-bottom:7px;">Lead-Magnete</div>
    <div style="font-size:12.5px;color:{body_c};line-height:1.6;">{lm1}<br>{lm2}</div>
  </div>

  <div style="margin-top:26px;font-size:12.5px;color:{muted};">
    {n_emails}-email sequence &middot; {site}
  </div>
</section>"""


def _is_dark(hex_color: str) -> bool:
    """True if the color is dark (so the PDF page should match it)."""
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) != 6:
        return False
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    # relative luminance
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) < 110


def email_section(n: int, subj: str, delay: int, html: str, accent: str,
                  page_bg: str, label_color: str, subj_color: str, rule: str) -> str:
    inner = _inner_body(html)
    label = "Start (Tag 0)" if n == 1 else f"+{delay} Tage"
    return f"""
<section class="page email-page" style="background:{page_bg};">
  <div style="border-bottom:1px solid {rule};padding-bottom:10px;margin-bottom:14px;">
    <div style="font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:{accent};">E-Mail {n} &nbsp;·&nbsp; {label}</div>
    <div style="font-size:17px;font-weight:700;color:{subj_color};margin-top:4px;">Betreff: {subj}</div>
  </div>
  <div class="email-wrap">{inner}</div>
</section>"""


def performance_section(prof: dict, variants: dict) -> str:
    """Optional projected-performance page. Renders only when the variants file
    defines a `performance` block. Numbers come straight from that block so the
    deliverable stays honest and editable per campaign."""
    perf = variants.get("performance")
    if not perf:
        return ""
    b = prof["brand"]
    c = b["colors"]
    accent = c.get("accent", "#16A34A")
    # Estimate page is on WHITE: solid dark text, not the brand's light colors.
    ink = "#111111"
    body_c = "#2A2A2A"
    muted = "#6B7280"

    rows = ""
    for r in perf.get("rows", []):
        rows += f"""<tr>
          <td style="padding:8px 10px;border-bottom:1px solid #E6EAE7;font-size:12px;color:{ink};font-weight:600;">{r.get('stage','')}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #E6EAE7;font-size:11px;color:{muted};">{r.get('cons_rate','')}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #E6EAE7;font-size:13px;color:{ink};font-weight:700;text-align:right;">{r.get('cons','')}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #E6EAE7;font-size:11px;color:{muted};">{r.get('opt_rate','')}</td>
          <td style="padding:8px 10px;border-bottom:1px solid #E6EAE7;font-size:13px;color:{accent};font-weight:700;text-align:right;">{r.get('opt','')}</td>
        </tr>"""

    rev = ""
    for rr in perf.get("revenue_rows", []):
        rev += f"""<div style="display:flex;justify-content:space-between;gap:16px;padding:9px 0;border-bottom:1px solid #E6EAE7;">
          <span style="font-size:12px;color:{body_c};">{rr.get('label','')}</span>
          <span style="font-size:12.5px;color:{ink};font-weight:700;white-space:nowrap;">{rr.get('value','')}</span></div>"""

    return f"""
<section class="page">
  <div style="font-size:12px;font-weight:600;letter-spacing:2px;text-transform:uppercase;color:{accent};">Performance estimate</div>
  <div style="font-size:30px;font-weight:800;letter-spacing:-0.6px;margin:8px 0 4px 0;color:{ink};">{perf.get('title','')}</div>
  <div style="height:3px;width:80px;background:{accent};margin:16px 0;"></div>

  <div style="padding:13px 16px;background:#FBEEF2;border:1px solid #F3C9D8;border-radius:6px;font-size:11px;line-height:1.6;color:{body_c};margin-bottom:20px;">
    <strong style="color:{ink};">Important:</strong> {perf.get('disclaimer','')}
  </div>

  <div style="font-size:11.5px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{ink};margin-bottom:8px;">{perf.get('funnel_label','Funnel')}</div>
  <table style="width:100%;border-collapse:collapse;border:1px solid #E6EAE7;">
    <tr style="background:#F4F5F4;">
      <th style="text-align:left;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:{ink};">Stage</th>
      <th style="text-align:left;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:{muted};">Conservative rate</th>
      <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:{ink};">Cons. / mo</th>
      <th style="text-align:left;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:{muted};">Optimistic rate</th>
      <th style="text-align:right;padding:8px 10px;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:{accent};">Opt. / mo</th>
    </tr>
    {rows}
  </table>

  <div style="margin-top:18px;padding:13px 16px;background:#F4F5F4;border-left:3px solid {accent};font-size:11.5px;line-height:1.6;color:{body_c};">
    {perf.get('value_note','')}
  </div>

  <div style="margin-top:18px;font-size:11.5px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{ink};margin-bottom:4px;">Projected annual value</div>
  {rev}

  <div style="margin-top:18px;padding:14px 18px;background:{ink};color:#fff;border-radius:8px;font-size:12.5px;line-height:1.6;">
    <strong style="color:{accent};">Bottom line:</strong> {perf.get('bottom_line','')}
  </div>
</section>"""


def combined_html(prof: dict, variants: dict, emails) -> str:
    b = prof["brand"]
    c = b["colors"]
    accent = c.get("accent", "#16A34A")
    font_url = b.get("font_url", "")
    # Theme the email pages to match the email itself. A dark-themed email
    # (dark bg_page) gets a dark PDF page so the card is not a small island on
    # white, with light label text; a light email keeps the white page.
    email_bg = c.get("bg_page", "#FFFFFF")
    dark = _is_dark(email_bg)
    if dark:
        page_bg = email_bg
        label_color = accent
        subj_color = "#FFFFFF"
        rule = "rgba(255,255,255,0.15)"
    else:
        page_bg = "#FFFFFF"
        label_color = accent
        subj_color = c.get("text", "#0E1A14")
        rule = "#E6EAE7"

    sections = [cover_section(prof, variants)]
    perf = performance_section(prof, variants)
    if perf:
        sections.append(perf)
    for n, subj, delay, html in emails:
        sections.append(email_section(n, subj, delay, html, accent,
                                      page_bg, label_color, subj_color, rule))
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8">
<link href="{font_url}" rel="stylesheet">
<style>
  @page {{ size: A4; margin: 0; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:{b.get('font_stack', "'Inter',sans-serif")}; -webkit-print-color-adjust: exact; }}
  .page {{ padding: 40px 46px; page-break-after: always; min-height: 100vh; }}
  .page:last-child {{ page-break-after: auto; }}
  .email-page {{ padding: 34px 30px; }}
  /* The email card is 620px wide. Scale to ~0.95 and center so text is large
     and readable on the A4 page instead of a shrunken island. */
  .email-wrap {{ width: 620px; transform: scale(0.95); transform-origin: top center; margin: 0 auto; }}
  .email-wrap table {{ margin: 0 auto !important; }}
</style></head>
<body>{''.join(sections)}</body></html>"""


async def main():
    slug = sys.argv[1] if len(sys.argv) > 1 else "energ"
    variants_dir = sys.argv[2] if len(sys.argv) > 2 else f"{slug}-default"
    prof, variants = load(slug, variants_dir)
    brand = prof["brand"]
    company = brand.get("legal", {}).get("company_name", brand.get("wordmark", slug.upper()))
    # Suffix the deliverable + out-dir when this is not the profile's default
    # sequence, so multiple sequences for one profile do not overwrite each other.
    suffix = ""
    if variants_dir not in (f"{slug}-default", f"{slug}"):
        tail = variants_dir.split("-", 1)[1] if "-" in variants_dir else variants_dir
        suffix = "-" + tail.capitalize()
    pdf_name = f"{company.replace(' ', '-')}-Email-Campaign{suffix}.pdf"

    out_dir = REPO / "out" / f"{variants_dir}-render"
    out_dir.mkdir(parents=True, exist_ok=True)
    html_dir = out_dir / "html"
    html_dir.mkdir(exist_ok=True)

    emails = build_emails(prof, variants)
    for n, subj, delay, html in emails:
        (html_dir / f"email-{n}.html").write_text(html, encoding="utf-8")

    async with async_playwright() as p:
        browser = await p.chromium.launch()

        # 1) Single-email PNG previews
        page = await browser.new_page(viewport={"width": 660, "height": 1000}, device_scale_factor=2)
        for n, subj, delay, html in emails:
            await page.set_content(html, wait_until="networkidle")
            await page.wait_for_timeout(700)
            await page.screenshot(path=str(out_dir / f"email-{n}.png"), full_page=True)

        # 2) Contact sheet
        cards = "".join(
            f'<div style="display:inline-block;vertical-align:top;margin:0 14px 28px 0;">'
            f'<div style="font-family:{brand.get("font_stack","Inter")};font-size:13px;font-weight:600;'
            f'letter-spacing:1px;text-transform:uppercase;color:#101010;margin:0 0 8px 4px;">'
            f'E-Mail {n} &nbsp;·&nbsp; {subj}</div>'
            f'<div style="width:620px;">{_inner_body(html)}</div></div>'
            for n, subj, delay, html in emails
        )
        sheet = ('<!doctype html><html><head><meta charset="utf-8">'
                 f'<link href="{brand.get("font_url","")}" rel="stylesheet"></head>'
                 '<body style="margin:0;padding:36px;background:#cfcfcf;white-space:nowrap;font-size:0;">'
                 + cards + "</body></html>")
        sp = await browser.new_page(device_scale_factor=2)
        await sp.set_content(sheet, wait_until="networkidle")
        await sp.wait_for_timeout(1200)
        await sp.screenshot(path=str(out_dir / "preview-all.png"), full_page=True)

        # 3) Combined presentation PDF (cover + 7 emails), single page.pdf() call
        pdf_page = await browser.new_page()
        await pdf_page.set_content(combined_html(prof, variants, emails), wait_until="networkidle")
        await pdf_page.wait_for_timeout(1000)
        await pdf_page.pdf(path=str(out_dir / pdf_name), format="A4", print_background=True,
                           margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        await browser.close()

    merged = out_dir / pdf_name
    print(f"OK: wrote {pdf_name} ({len(emails)} emails + cover), {merged.stat().st_size} bytes")
    print(f"dir: {out_dir}")
    print(f"pdf: {merged}")


if __name__ == "__main__":
    asyncio.run(main())
