# -*- coding: utf-8 -*-
"""render-magnet.py, render each give-first lead-magnet spec into a branded,
print-ready PDF (lead-magnets/<Title>.pdf) via headless Chrome.

Reads lead-magnets/magnet-specs.json (the designed deliverables, one per client),
applies the client's brand name + accent, and lays it out as a clean professional
document matching the Diraya magnet quality. The fulfiller (fulfill-magnets.py)
attaches the resulting PDF when a prospect replies the magnet keyword.

    py scripts/render-magnet.py            # render all
    py scripts/render-magnet.py mark-eting # render one
"""
from __future__ import annotations
import html as _html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SPECS = REPO / "lead-magnets" / "magnet-specs.json"
OUT_DIR = REPO / "lead-magnets"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def brand_for(slug: str) -> tuple[str, str]:
    """(wordmark, site) from the client profile; sensible fallback."""
    for fn in (f"{slug}.json", f"{slug}.private.json"):
        p = REPO / "profiles" / fn
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                b = d.get("brand") or {}
                name = b.get("name") or b.get("wordmark") or slug
                site = (b.get("site") or b.get("website")
                        or ((b.get("legal") or {}).get("website")) or "")
                site = re.sub(r"^https?://", "", site or "").rstrip("/")
                return str(name), str(site)
            except Exception:
                pass
    return slug.replace("-", " ").title(), ""


def _paras(body: str) -> str:
    """Body text -> HTML paragraphs. Blank lines split paragraphs; a numbered or
    lettered list marker mid-paragraph starts a new line for readability."""
    body = (body or "").strip()
    chunks = re.split(r"\n\s*\n", body) if "\n" in body else [body]
    out = []
    for ch in chunks:
        ch = " ".join(ch.split())
        # break before " 1. " / " 2. " style list items and before A/B/C section letters
        ch = re.sub(r"(?<=[.:])\s+(\d{1,2}\.\s)", r"<br>\1", ch)
        out.append(f"<p>{_html.escape(ch).replace('&lt;br&gt;', '<br>')}</p>")
    return "".join(out)


def build_html(spec: dict) -> str:
    slug = spec["client_slug"]
    accent = spec.get("accent_hex") or "#1a1a1a"
    wordmark, site = brand_for(slug)
    lang = spec.get("language", "en")
    title = _html.escape(spec["deliverable_title"])
    promise = _html.escape(spec.get("one_line_promise", ""))
    disclaimer = ("Allgemeine Information, keine Rechts- oder Steuerberatung im Einzelfall."
                  if lang == "de" else
                  "General guidance, not advice for your specific situation.")
    secs = "".join(
        f'<h2>{_html.escape(s["heading"])}</h2>{_paras(s["body"])}'
        for s in spec.get("sections", []))
    foot = " &nbsp;&middot;&nbsp; ".join(x for x in (_html.escape(wordmark), _html.escape(site)) if x)
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<style>
 @page {{ size: A4; margin: 20mm 17mm; }}
 :root {{ --accent: {accent}; }}
 * {{ box-sizing: border-box; }}
 body {{ font-family: Georgia, 'Times New Roman', serif; color:#1b1b1b; line-height:1.5; font-size:11pt; margin:0; }}
 .wm {{ font-family:-apple-system,'Segoe UI',Arial,sans-serif; font-weight:800; font-size:12.5pt; color:var(--accent); letter-spacing:.4px; text-transform:uppercase; }}
 .rule {{ height:3px; background:var(--accent); margin:7px 0 0; border-radius:2px; }}
 h1 {{ font-family:-apple-system,'Segoe UI',Arial,sans-serif; font-size:20pt; line-height:1.18; margin:20px 0 6px; color:#111; }}
 .sub {{ color:#555; font-size:11.5pt; margin:0 0 20px; font-style:italic; }}
 h2 {{ font-family:-apple-system,'Segoe UI',Arial,sans-serif; font-size:13.5pt; color:var(--accent); margin:22px 0 7px; page-break-after:avoid; }}
 p {{ margin:0 0 9px; }}
 .foot {{ margin-top:30px; padding-top:9px; border-top:1px solid #ddd; color:#777; font-size:8.5pt; font-family:-apple-system,'Segoe UI',Arial,sans-serif; }}
</style></head><body>
 <div class="wm">{_html.escape(wordmark)}</div><div class="rule"></div>
 <h1>{title}</h1>
 <div class="sub">{promise}</div>
 {secs}
 <div class="foot">{foot} &nbsp;&middot;&nbsp; {disclaimer}</div>
</body></html>"""


def render(spec: dict) -> Path:
    slug = spec["client_slug"]
    safe = re.sub(r"[^A-Za-z0-9]+", "-", spec["deliverable_title"].split(":")[0]).strip("-")[:60]
    pdf = OUT_DIR / f"{slug}--{safe}.pdf"
    html = build_html(spec)
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html); src = f.name
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={pdf}", "file:///" + src.replace("\\", "/")],
                   capture_output=True, timeout=90)
    Path(src).unlink(missing_ok=True)
    return pdf


def main() -> int:
    specs = json.loads(SPECS.read_text(encoding="utf-8"))
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for spec in specs:
        if only and spec["client_slug"] != only:
            continue
        pdf = render(spec)
        kb = pdf.stat().st_size // 1024 if pdf.exists() else 0
        print(f"  {spec['client_slug']:16} -> {pdf.name}  ({kb} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
