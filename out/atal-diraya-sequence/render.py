# -*- coding: utf-8 -*-
"""Render the 7-email Atal Solidrocks sequence to HTML + a preview PNG.

Standalone: imports the local template + sequence, merges demo prospect data,
writes each email's HTML, and screenshots all 7 at email width into one tall
preview image (preview-all.png) plus single-email shots.

    py render.py
"""
import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from template import render as render_email  # noqa: E402
from sequence import SEQUENCE, BRAND  # noqa: E402
from playwright.async_api import async_playwright  # noqa: E402

DEMO = {
    "first_name": "Frau Bergmann",
    "company": "Hartmann Logistik GmbH",
    "city": "Düsseldorf",
}


def merge(s: str) -> str:
    for k, v in DEMO.items():
        s = s.replace("{" + k + "}", v)
    return s


def build_all() -> list[tuple[int, str, str]]:
    """Return list of (n, subject, html)."""
    out = []
    for step in SEQUENCE:
        html = render_email(
            headline=merge(step["headline"]),
            kicker=step["kicker"],
            body=merge(step["body"]),
            cta_label=step.get("cta_label", "Vorgespräch buchen"),
            cta_url=BRAND["calendly_url"],
            signature=BRAND["signature"],
            brand=BRAND,
            show_cta=step.get("show_cta", True),
            step_n=step["n"],
        )
        out.append((step["n"], merge(step["subject"]), html))
    return out


async def main():
    emails = build_all()
    html_dir = HERE / "html"
    html_dir.mkdir(exist_ok=True)
    for n, subj, html in emails:
        (html_dir / f"email-{n}.html").write_text(html, encoding="utf-8")

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        # Single-email screenshots
        page = await browser.new_page(viewport={"width": 660, "height": 1000},
                                      device_scale_factor=2)
        for n, subj, html in emails:
            await page.set_content(html, wait_until="networkidle")
            await page.wait_for_timeout(700)  # let webfonts paint
            await page.screenshot(path=str(HERE / f"email-{n}.png"), full_page=True)

        # Combined contact-sheet: all 7 emails side by side in a grid
        cards = "".join(
            f'<div style="display:inline-block;vertical-align:top;margin:0 14px 28px 0;">'
            f'<div style="font-family:Kanit,sans-serif;font-size:13px;font-weight:600;'
            f'letter-spacing:1px;text-transform:uppercase;color:#101010;margin:0 0 8px 4px;">'
            f'E-Mail {n} &nbsp;·&nbsp; Betreff: {subj}</div>'
            f'<div style="width:620px;">{html.split("<body", 1)[1].split(">", 1)[1].rsplit("</body>", 1)[0]}</div>'
            f'</div>'
            for n, subj, html in emails
        )
        sheet = (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700;900&family=Kanit:wght@400;500;600;700&display=swap" rel="stylesheet">'
            '</head><body style="margin:0;padding:36px;background:#cfcfcf;white-space:nowrap;font-size:0;">'
            + cards + "</body></html>"
        )
        sheet_page = await browser.new_page(device_scale_factor=2)
        await sheet_page.set_content(sheet, wait_until="networkidle")
        await sheet_page.wait_for_timeout(1200)
        await sheet_page.screenshot(path=str(HERE / "preview-all.png"), full_page=True)
        await browser.close()

    print("OK: wrote html/email-1..7.html, email-1..7.png, preview-all.png")
    print(f"dir: {HERE}")


if __name__ == "__main__":
    asyncio.run(main())
