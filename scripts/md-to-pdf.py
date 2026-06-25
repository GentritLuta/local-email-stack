# -*- coding: utf-8 -*-
"""md-to-pdf.py — render a Markdown document to a clean, print-ready PDF.

Markdown -> styled HTML -> PDF via headless Chrome (same engine as render-magnet.py).
General-purpose: contracts, briefs, any document kept in Markdown.

Usage:
    py scripts/md-to-pdf.py contracts/algoalpha-creator-agreement.md
    py scripts/md-to-pdf.py <input.md> <output.pdf>
"""
from __future__ import annotations
import shutil, subprocess, sys, tempfile
from pathlib import Path
import markdown

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

CSS = """
@page { size: A4; margin: 18mm 16mm 20mm 16mm; }
* { box-sizing: border-box; }
body { font: 10.5pt/1.55 Georgia, 'Times New Roman', serif; color: #1a1a1a; margin: 0; }
h1 { font-family: 'Segoe UI', Arial, sans-serif; font-size: 20pt; font-weight: 700;
     margin: 0 0 4pt 0; color: #0f172a; }
h2 { font-family: 'Segoe UI', Arial, sans-serif; font-size: 12.5pt; font-weight: 700;
     color: #0f172a; margin: 18pt 0 6pt 0; padding-bottom: 3pt; border-bottom: 1px solid #e2e8f0;
     page-break-after: avoid; }
h3 { font-family: 'Segoe UI', Arial, sans-serif; font-size: 11pt; font-weight: 700; margin: 12pt 0 4pt; }
p { margin: 0 0 7pt 0; }
strong { color: #0f172a; }
hr { border: none; border-top: 1px solid #cbd5e1; margin: 16pt 0; }
blockquote { background: #f8fafc; border-left: 3px solid #94a3b8; margin: 10pt 0;
             padding: 8pt 12pt; font-size: 9.5pt; color: #334155; page-break-inside: avoid; }
blockquote p { margin: 0 0 4pt 0; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0; font-size: 9.5pt; page-break-inside: avoid; }
th, td { border: 1px solid #cbd5e1; padding: 5pt 8pt; text-align: left; vertical-align: top; }
th { background: #f1f5f9; font-family: 'Segoe UI', Arial, sans-serif; font-weight: 700; }
a { color: #1d4ed8; text-decoration: none; }
.fill { display: inline-block; min-width: 140px; border-bottom: 1px solid #334155; }
.fill::after { content: "\\00a0"; }
.fill-lg { min-width: 290px; }
"""


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: py scripts/md-to-pdf.py <input.md> [output.pdf]"); return 1
    src_md = Path(sys.argv[1])
    if not src_md.exists():
        print(f"not found: {src_md}"); return 1
    out_pdf = (Path(sys.argv[2]) if len(sys.argv) > 2 else src_md.with_suffix(".pdf")).resolve()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    body = markdown.markdown(src_md.read_text(encoding="utf-8"),
                             extensions=["tables", "sane_lists", "attr_list"])
    html = (f"<!doctype html><html><head><meta charset='utf-8'><style>{CSS}</style></head>"
            f"<body>{body}</body></html>")
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html); tmp = f.name
    udir = tempfile.mkdtemp(prefix="md2pdf_chrome_")
    try:
        r = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                            f"--user-data-dir={udir}", f"--print-to-pdf={out_pdf}",
                            "file:///" + tmp.replace("\\", "/")],
                           capture_output=True, timeout=120)
    finally:
        Path(tmp).unlink(missing_ok=True)
        shutil.rmtree(udir, ignore_errors=True)
    if out_pdf.exists() and out_pdf.stat().st_size > 0:
        print(f"PDF: {out_pdf}  ({out_pdf.stat().st_size} bytes)")
        return 0
    print("render failed:", (r.stderr or b"").decode(errors="replace")[-300:])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
