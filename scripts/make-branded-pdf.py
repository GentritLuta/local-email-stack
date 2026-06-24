"""make-branded-pdf.py — MODULAR building block: turn a markdown doc into a clean
branded PDF (Playwright-rendered, no external daemon). Used for client onboarding
summaries, proposals, and any operator doc.

    py scripts/make-branded-pdf.py docs/mark-eting-onboarding-summary.md \
        --out out/Mark-eting-Campaign-Setup.pdf --accent "#E8740C" --title "Mark-eting Campaign Setup"
"""
from __future__ import annotations
import argparse
import sys
import tempfile
from pathlib import Path

import markdown as _md
from playwright.sync_api import sync_playwright


def build_html(md_text: str, title: str, accent: str) -> str:
    body = _md.markdown(md_text, extensions=["tables", "fenced_code", "sane_lists"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap" rel="stylesheet">
<style>
  @page {{ size: A4; margin: 16mm 16mm 18mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family:'Inter',-apple-system,'Segoe UI',sans-serif; color:#1a1a1a; font-size:12.5px; line-height:1.62; margin:0; }}
  h1 {{ font-family:'Fraunces','Inter',serif; font-size:30px; font-weight:600; letter-spacing:-.01em; margin:0 0 4px; color:#0f0f0f; }}
  h1 + p {{ color:#64748b; margin-top:0; }}
  h2 {{ font-family:'Fraunces','Inter',serif; font-size:18px; font-weight:600; margin:24px 0 6px; color:{accent}; border-bottom:2px solid #f0e3d6; padding-bottom:4px; }}
  p {{ margin:0 0 9px; }}
  ul, ol {{ margin:0 0 10px; padding-left:20px; }}
  li {{ margin-bottom:4px; }}
  table {{ width:100%; border-collapse:collapse; margin:10px 0 16px; font-size:12px; }}
  th {{ text-align:left; background:{accent}; color:#fff; padding:7px 10px; font-weight:600; }}
  td {{ padding:7px 10px; border-bottom:1px solid #ececec; vertical-align:top; }}
  tr:nth-child(even) td {{ background:#faf7f3; }}
  code {{ background:#f5f5f5; padding:1px 5px; border-radius:4px; font-size:11.5px; }}
  strong {{ color:#0f0f0f; }}
  .topbar {{ height:5px; background:{accent}; margin:-16mm -16mm 14mm; }}
</style></head><body><div class="topbar"></div>
{body}
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("md")
    ap.add_argument("--out", required=True)
    ap.add_argument("--title", default="Document")
    ap.add_argument("--accent", default="#3730a3")
    a = ap.parse_args()
    html = build_html(Path(a.md).read_text(encoding="utf-8"), a.title, a.accent)
    tmp = Path(tempfile.mkdtemp(prefix="branded_pdf_")) / "doc.html"
    tmp.write_text(html, encoding="utf-8")
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(); pg = b.new_page()
        pg.goto(tmp.as_uri(), wait_until="networkidle"); pg.wait_for_timeout(400)
        pg.pdf(path=str(out), format="A4", print_background=True,
               margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        b.close()
    print(f"DONE: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
