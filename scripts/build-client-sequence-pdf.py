"""build-client-sequence-pdf.py — MODULAR client deliverable block.

Given ANY profile slug, render its live 7-email sequence to a premium branded PDF
(+ a standalone HTML) with each email shown exactly as it lands in the inbox. This
is the reusable "PDF and HTML creation" building block for client onboarding: no
per-client code, it reads the brand + sequence the rest of the stack already owns.

    py scripts/build-client-sequence-pdf.py --profile dorian
    py scripts/build-client-sequence-pdf.py --profile energ --out out/ENER-G-Sequence.pdf

Inputs it composes (all existing building blocks):
  - profiles/<slug>.json        -> brand (colors, wordmark, legal) + personas
  - sequences/<slug>-default/variants.json (or --variants) -> the 7 emails
  - sequences/email_render.py   -> the real wire-format HTML per email

Outputs:
  - out/<Slug>-Sequence.pdf  (premium document)
  - out/<Slug>-Sequence.html (the same, viewable in a browser)
"""
from __future__ import annotations
import argparse
import html as _html
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from email_render import render_html  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

SAMPLE = {"greeting": "Marcus", "first_name": "Marcus", "company": "Apex Co",
          "hook": "your recent post on firing your three worst-fit clients",
          "personal_hook": "your recent post on firing your three worst-fit clients",
          "city": "Austin", "retainer_quote": "a flat 1,600 USD per video",
          "retainer_math": "At your audience size that is about 1,600 USD per video, paid win or lose."}


def merge(s: str) -> str:
    for k, v in SAMPLE.items():
        s = s.replace("{" + k + "}", v)
    return s


def esc(s: str) -> str:
    return _html.escape(s or "")


def load_profile(slug: str) -> dict:
    return json.loads((REPO / "profiles" / f"{slug}.json").read_text(encoding="utf-8"))


def load_variants(slug: str, override: str | None) -> list[dict]:
    path = Path(override) if override else (REPO / "sequences" / f"{slug}-default" / "variants.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    return sorted(data["variants"], key=lambda e: e["n"])


def screenshot_emails(emails, brand, persona, shot_dir):
    shot_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 680, "height": 900}, device_scale_factor=2)
        for e in emails:
            html = render_html(body=merge(e["body"]), persona=persona,
                               unsubscribe_token="preview-token-0000", brand=brand, step_n=e["n"])
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(350)
            shot = shot_dir / f"email_{e['n']}.png"
            page.screenshot(path=str(shot), full_page=True)
            paths.append(shot)
        browser.close()
    return paths


def build_html(profile, emails, shots) -> str:
    brand = profile.get("brand") or {}
    colors = brand.get("colors") or {}
    accent = colors.get("accent_2") or colors.get("accent") or "#3730a3"
    ink = colors.get("text") or "#0a0a0a"
    slate = colors.get("text_2") or "#475569"
    muted = colors.get("muted") or "#94a3b8"
    rule = colors.get("rule") or "#e5e7eb"
    wordmark = brand.get("wordmark") or profile.get("name", "")
    tagline = brand.get("tagline") or (profile.get("company") or {}).get("tagline", "")
    site = brand.get("site") or (profile.get("company") or {}).get("site", "")

    day = 0
    cad_rows, cards = [], []
    for e, shot in zip(emails, shots):
        day += int(e.get("delay_days", 0))
        when = "day 0 (immediately)" if e["n"] == 1 else f"day {day}"
        cad_rows.append(f"<tr><td class='c1'>E{e['n']}</td><td class='c2'>{when}</td>"
                        f"<td class='c3'>{esc(e.get('angle',''))}</td><td class='c4'>{esc(merge(e['subject']))}</td></tr>")
        rat = e.get("rationale", "")
        rat_html = f"<div class='rationale'><span class='rk'>Why this email</span>{esc(rat)}</div>" if rat else ""
        cards.append(f"""<section class="card"><div class="card-head">
          <span class="step">EMAIL {e['n']}</span><span class="when">{esc(when)}</span>
          <span class="angle">{esc(e.get('angle',''))}</span></div>
          <div class="subjline"><span class="sk">Subject</span> {esc(merge(e['subject']))}</div>
          {rat_html}<div class="inbox"><img src="file:///{shot.as_posix()}" alt="Email {e['n']}"></div></section>""")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap" rel="stylesheet">
<style>
  @page {{ size: A4; margin: 12mm 12mm 13mm; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:'Inter',-apple-system,'Segoe UI',sans-serif; color:{ink}; font-size:13px; line-height:1.6; }}
  h1,h2 {{ font-family:'Fraunces','Inter',serif; font-weight:600; letter-spacing:-.01em; }}
  .lede {{ color:{slate}; }}
  .cover {{ height: 263mm; display:flex; flex-direction:column; justify-content:center; page-break-after:always; }}
  .cover .mark {{ font-weight:800; font-size:15px; letter-spacing:.08em; text-transform:uppercase; color:{accent}; }}
  .cover .rule {{ height:3px; width:54px; background:{accent}; margin:18px 0 30px; }}
  .cover h1 {{ font-size:40px; line-height:1.1; margin:0 0 16px; max-width:16em; }}
  .cover .sub {{ font-size:16px; color:{slate}; max-width:32em; }}
  .cover .meta {{ margin-top:42px; color:{muted}; font-size:12px; }}
  .page {{ page-break-before: always; }}
  h2 {{ font-size:24px; margin:0 0 6px; }}
  table {{ width:100%; border-collapse:collapse; margin-top:14px; }}
  th {{ text-align:left; font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:{muted}; border-bottom:2px solid {rule}; padding:0 10px 7px; }}
  td {{ padding:9px 10px; border-bottom:1px solid {rule}; vertical-align:top; }}
  .c1 {{ font-weight:700; color:{accent}; width:8%; }} .c2 {{ width:20%; color:{slate}; }}
  .c3 {{ width:30%; color:{slate}; font-style:italic; }} .c4 {{ width:42%; }}
  .card {{ page-break-before: always; }}
  .card-head {{ display:flex; align-items:center; gap:12px; margin-bottom:10px; }}
  .step {{ background:{accent}; color:#fff; font-weight:700; font-size:11px; letter-spacing:.06em; padding:4px 11px; border-radius:5px; }}
  .when {{ font-size:12px; color:{slate}; font-weight:600; }}
  .angle {{ font-size:11px; color:{muted}; font-style:italic; margin-left:auto; }}
  .subjline {{ font-size:15px; font-weight:600; margin-bottom:8px; }}
  .sk,.rk {{ font-size:10px; text-transform:uppercase; letter-spacing:.06em; font-weight:700; margin-right:6px; }}
  .sk {{ color:{muted}; }} .rk {{ color:{accent}; margin-right:8px; }}
  .rationale {{ font-size:12px; color:{slate}; background:#f7f7fb; border-radius:7px; padding:10px 13px; margin-bottom:14px; }}
  .inbox {{ text-align:center; }}
  .inbox img {{ display:block; margin:0 auto; width:auto; height:auto; max-width:172mm; max-height:212mm; border:1px solid {rule}; border-radius:10px; box-shadow:0 1px 4px rgba(0,0,0,.08); }}
</style></head><body>
  <div class="cover">
    <div class="mark">{esc(wordmark)}</div><div class="rule"></div>
    <h1>Cold Email Sequence</h1>
    <div class="sub">{esc(tagline)}</div>
    <div class="meta">{esc(wordmark)} · {esc(site)} · 7-touch founder-to-founder sequence, rendered exactly as it lands in the inbox.</div>
  </div>
  <section class="page"><h2>Cadence</h2>
    <p class="lede">Seven touches. One clear ask per email. Merge fields filled with a sample prospect ({esc(SAMPLE['greeting'])} at {esc(SAMPLE['company'])}).</p>
    <table><thead><tr><th>Step</th><th>Timing</th><th>Angle</th><th>Subject</th></tr></thead><tbody>{''.join(cad_rows)}</tbody></table>
  </section>
  {''.join(cards)}
</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True, help="profile slug (e.g. dorian, energ, diraya)")
    ap.add_argument("--variants", default=None, help="override path to variants.json")
    ap.add_argument("--persona", default=None, help="persona slug to render as (default: first persona)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    profile = load_profile(args.profile)
    brand = profile.get("brand")
    personas = profile.get("personas") or []
    persona = next((p for p in personas if p["slug"] == args.persona), None) or (personas[0] if personas else {})
    emails = load_variants(args.profile, args.variants)

    shot_dir = Path(tempfile.mkdtemp(prefix=f"{args.profile}_seq_"))
    print(f"rendering {len(emails)} emails for '{args.profile}' ...")
    shots = screenshot_emails(emails, brand, persona, shot_dir)
    master = build_html(profile, emails, shots)
    (shot_dir / "master.html").write_text(master, encoding="utf-8")

    slug_title = args.profile.replace("-", " ").title().replace(" ", "-")
    out = Path(args.out) if args.out else (REPO / "out" / f"{slug_title}-Sequence.pdf")
    out.parent.mkdir(parents=True, exist_ok=True)
    html_out = out.with_suffix(".html")
    html_out.write_text(master.replace('src="file:///', 'src="file:///'), encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto((shot_dir / "master.html").as_uri(), wait_until="networkidle")
        page.wait_for_timeout(500)
        page.pdf(path=str(out), format="A4", print_background=True,
                 margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        browser.close()
    print(f"DONE: {out}\n      {html_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
