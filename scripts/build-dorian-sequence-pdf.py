"""build-dorian-sequence-pdf.py — premium PDF of Mercury Scales' cold-email
sequence with each email rendered to its real inbox HTML (via email_render)
and embedded as a pixel-accurate screenshot, plus offer / cadence / targeting
/ optimization pages.

Reads a sequence-data JSON so the same builder works for the live copy or an
upgraded v2 sequence:

    py scripts/build-dorian-sequence-pdf.py --data out/dorian-sequence-data.json \
        --out out/Mercury-Scales-Sequence.pdf

DATA JSON shape:
{
  "positioning": "one-line positioning",
  "offer_block": "the sharpened offer + guarantee text",
  "emails": [{"n":1,"delay_days":0,"angle":"...","subject":"...","body":"...","rationale":"..."}],
  "actions": [{"area":"Lead quality","priority":"P0","title":"...","action":"...","impact":"..."}]
}
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

# Sample prospect for merge previews. {greeting} shows the personalized variant;
# the overview page notes that name-missing leads get a graceful fallback.
SAMPLE = {
    "greeting": "Marcus",
    "first_name": "Marcus",
    "company": "Apex Closers",
    "hook": "your post on firing your three worst-fit clients",
    "city": "Austin",
}

ACCENT = "#3730a3"   # Mercury Scales indigo
INK = "#0a0a0a"
SLATE = "#475569"
MUTED = "#94a3b8"
RULE = "#e5e7eb"


def merge(s: str) -> str:
    for k, v in SAMPLE.items():
        s = s.replace("{" + k + "}", v)
    return s


def esc(s: str) -> str:
    return _html.escape(s or "")


def load_brand_and_persona() -> tuple[dict, dict]:
    prof = json.loads((REPO / "profiles" / "dorian.json").read_text(encoding="utf-8"))
    brand = prof.get("brand")
    persona = next(p for p in prof["personas"] if p["slug"] == "dorian")
    return brand, persona


def screenshot_emails(emails: list[dict], brand: dict, persona: dict,
                      shot_dir: Path) -> list[Path]:
    """Render each email to its real HTML and screenshot it full-page."""
    shot_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 680, "height": 900},
                                device_scale_factor=2)
        for e in emails:
            body = merge(e["body"])
            html = render_html(body=body, persona=persona,
                               unsubscribe_token="preview-token-0000",
                               brand=brand, step_n=e["n"])
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(350)
            shot = shot_dir / f"email_{e['n']}.png"
            page.screenshot(path=str(shot), full_page=True)
            paths.append(shot)
        browser.close()
    return paths


def cadence_rows(emails: list[dict]) -> str:
    day = 0
    rows = []
    for e in emails:
        day += int(e.get("delay_days", 0))
        when = "sent immediately" if e["n"] == 1 else f"day {day}"
        rows.append(
            f"<tr><td class='c1'>E{e['n']}</td>"
            f"<td class='c2'>{when}</td>"
            f"<td class='c3'>{esc(e.get('angle',''))}</td>"
            f"<td class='c4'>{esc(merge(e['subject']))}</td></tr>"
        )
    return "".join(rows)


def email_cards(emails: list[dict], shots: list[Path]) -> str:
    day = 0
    cards = []
    for e, shot in zip(emails, shots):
        day += int(e.get("delay_days", 0))
        when = "Sent immediately (day 0)" if e["n"] == 1 else f"Day {day} · +{e['delay_days']} after E{e['n']-1}"
        rationale = e.get("rationale", "")
        rat_html = (f"<div class='rationale'><span class='rk'>Why this email</span>{esc(rationale)}</div>"
                    if rationale else "")
        cards.append(f"""
        <section class="card">
          <div class="card-head">
            <span class="step">EMAIL {e['n']}</span>
            <span class="when">{esc(when)}</span>
            <span class="angle">{esc(e.get('angle',''))}</span>
          </div>
          <div class="subjline"><span class="sk">Subject</span> {esc(merge(e['subject']))}</div>
          {rat_html}
          <div class="inbox"><img src="file:///{shot.as_posix()}" alt="Email {e['n']}"></div>
        </section>""")
    return "".join(cards)


def actions_table(actions: list[dict]) -> str:
    if not actions:
        return ""
    order = {"P0": 0, "P1": 1, "P2": 2}
    actions = sorted(actions, key=lambda a: order.get(a.get("priority", "P2"), 3))
    rows = []
    for a in actions:
        pr = a.get("priority", "P2")
        rows.append(
            f"<tr><td class='pr pr-{pr}'>{pr}</td>"
            f"<td class='area'>{esc(a.get('area',''))}</td>"
            f"<td class='act'><b>{esc(a.get('title',''))}</b><br>{esc(a.get('action',''))}</td>"
            f"<td class='imp'>{esc(a.get('impact',''))}</td></tr>"
        )
    return f"""
    <section class="page">
      <h2>Optimization plan</h2>
      <p class="lede">The highest-leverage changes, ordered by priority. P0 = do before sending another batch.</p>
      <table class="actions">
        <thead><tr><th>Pri</th><th>Area</th><th>Change</th><th>Expected impact</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </section>"""


def build_master_html(data: dict, shots: list[Path]) -> str:
    emails = data["emails"]
    positioning = data.get("positioning", "")
    offer = data.get("offer_block", "")
    offer_html = "".join(f"<p>{esc(par)}</p>" for par in offer.split("\n") if par.strip())
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&family=Fraunces:opsz,wght@9..144,500;9..144,600&display=swap" rel="stylesheet">
<style>
  @page {{ size: A4; margin: 12mm 12mm 13mm; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:'Inter',-apple-system,'Segoe UI',sans-serif; color:{INK}; font-size:13px; line-height:1.6; }}
  h1,h2,h3 {{ font-family:'Fraunces','Inter',serif; font-weight:600; letter-spacing:-.01em; }}
  .lede {{ color:{SLATE}; }}
  /* Cover */
  .cover {{ height: 263mm; display:flex; flex-direction:column; justify-content:center; page-break-after:always; }}
  .cover .mark {{ font-weight:800; font-size:15px; letter-spacing:.08em; text-transform:uppercase; color:{ACCENT}; font-family:'Inter',sans-serif; }}
  .cover .rule {{ height:3px; width:54px; background:{ACCENT}; margin:18px 0 30px; }}
  .cover h1 {{ font-size:42px; line-height:1.08; margin:0 0 18px; max-width:16em; }}
  .cover .sub {{ font-size:16px; color:{SLATE}; max-width:30em; }}
  .cover .meta {{ margin-top:46px; color:{MUTED}; font-size:12px; }}
  .cover .pos {{ margin-top:30px; padding:16px 18px; border-left:3px solid {ACCENT}; background:#f8f8fc; font-size:14px; color:{INK}; max-width:34em; }}
  /* Generic page */
  .page {{ page-break-before: always; }}
  h2 {{ font-size:24px; margin:0 0 6px; }}
  /* tables */
  table {{ width:100%; border-collapse:collapse; margin-top:14px; }}
  th {{ text-align:left; font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:{MUTED}; border-bottom:2px solid {RULE}; padding:0 10px 7px; }}
  td {{ padding:9px 10px; border-bottom:1px solid {RULE}; vertical-align:top; }}
  .cad .c1 {{ font-weight:700; color:{ACCENT}; width:8%; }}
  .cad .c2 {{ width:18%; color:{SLATE}; }}
  .cad .c3 {{ width:30%; color:{SLATE}; font-style:italic; }}
  .cad .c4 {{ width:44%; }}
  .grid2 {{ display:flex; gap:26px; margin-top:16px; }}
  .grid2 > div {{ flex:1; }}
  .box {{ border:1px solid {RULE}; border-radius:8px; padding:16px 18px; }}
  .box h3 {{ font-size:14px; margin:0 0 8px; }}
  .box ul {{ margin:0; padding-left:18px; color:{SLATE}; }}
  .box li {{ margin-bottom:5px; }}
  .offer p {{ margin:0 0 9px; max-width:42em; }}
  /* email cards */
  .card {{ page-break-before: always; }}
  .card-head {{ display:flex; align-items:center; gap:12px; margin-bottom:10px; }}
  .step {{ background:{ACCENT}; color:#fff; font-weight:700; font-size:11px; letter-spacing:.06em; padding:4px 11px; border-radius:5px; }}
  .when {{ font-size:12px; color:{SLATE}; font-weight:600; }}
  .angle {{ font-size:11px; color:{MUTED}; font-style:italic; margin-left:auto; }}
  .subjline {{ font-size:15px; font-weight:600; margin-bottom:8px; }}
  .sk, .rk, .pr {{ display:inline-block; }}
  .sk {{ font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:{MUTED}; font-weight:700; margin-right:6px; }}
  .rationale {{ font-size:12px; color:{SLATE}; background:#f8f8fc; border-radius:7px; padding:10px 13px; margin-bottom:14px; }}
  .rk {{ font-size:10px; text-transform:uppercase; letter-spacing:.06em; color:{ACCENT}; font-weight:700; margin-right:8px; }}
  .inbox {{ text-align:center; }}
  .inbox img {{ display:block; margin:0 auto; width:auto; height:auto; max-width:172mm; max-height:212mm;
               border:1px solid {RULE}; border-radius:10px; box-shadow:0 1px 4px rgba(0,0,0,.08); }}
  /* actions */
  .actions .pr {{ font-weight:700; font-size:11px; width:7%; }}
  .pr-P0 {{ color:#b91c1c; }} .pr-P1 {{ color:{ACCENT}; }} .pr-P2 {{ color:{MUTED}; }}
  .actions .area {{ width:18%; font-weight:600; }}
  .actions .act {{ width:50%; color:{SLATE}; }}
  .actions .imp {{ width:25%; color:{SLATE}; }}
</style></head><body>

  <div class="cover">
    <div class="mark">Mercury Scales</div>
    <div class="rule"></div>
    <h1>Cold Email Sequence &amp; Optimization Plan</h1>
    <div class="sub">The 7-touch founder-to-founder sequence, rendered exactly as it lands in the inbox, plus the changes that lift replies, deliverability and booked calls.</div>
    <div class="pos">{esc(positioning)}</div>
    <div class="meta">Prepared for Dorian Skiljo · mercuryscales.com · client acquisition for self-made B2B founders</div>
  </div>

  <section class="page">
    <h2>The offer</h2>
    <p class="lede">One spine runs through all seven emails. Every touch points back to this.</p>
    <div class="offer" style="margin-top:14px;">{offer_html}</div>
    <div class="grid2">
      <div class="box">
        <h3>Who it is for</h3>
        <ul>
          <li>Self-made B2B founders, lean teams of 1 to 10</li>
          <li>AI / automation agency owners</li>
          <li>High-ticket sales and closing coaches</li>
          <li>Business, sales and marketing coaches</li>
          <li>Money and mindset educators</li>
        </ul>
      </div>
      <div class="box">
        <h3>Buying signals we target</h3>
        <ul>
          <li>15k+ engaged followers, real testimonials</li>
          <li>Already running paid ads (proven they invest)</li>
          <li>Posting income or self-made milestones</li>
          <li>Recruiting closers or scaling a team</li>
          <li>English-speaking US/UK/CA/AU plus Germany</li>
        </ul>
      </div>
    </div>
  </section>

  <section class="page">
    <h2>Cadence</h2>
    <p class="lede">Seven touches over 28 days. One clear ask per email. The greeting is name-optional, so a lead with no parseable first name still gets a clean, non-generic open.</p>
    <table class="cad">
      <thead><tr><th>Step</th><th>Timing</th><th>Angle</th><th>Subject</th></tr></thead>
      <tbody>{cadence_rows(emails)}</tbody>
    </table>
    <div class="grid2">
      <div class="box"><h3>Sending setup</h3><ul>
        <li>12 verified sending subdomains, 12 rotating personas</li>
        <li>Recipient-local 08:00 to 17:00, weekdays only</li>
        <li>Warmup ramp 15 to 50 per domain per day</li>
        <li>One-click unsubscribe + legal footer on every send</li>
      </ul></div>
      <div class="box"><h3>Metrics to watch weekly</h3><ul>
        <li>Bounce rate (target under 2%)</li>
        <li>Open rate (target 50%+)</li>
        <li>Reply rate and positive-reply rate</li>
        <li>Calls booked and show rate</li>
      </ul></div>
    </div>
  </section>

  <section class="page">
    <h2>The sequence</h2>
    <p class="lede">Each email below is the real rendered HTML, captured exactly as the recipient sees it. Merge fields are filled with a sample prospect ({esc(SAMPLE['greeting'])} at {esc(SAMPLE['company'])}).</p>
  </section>
  {email_cards(emails, shots)}

  {actions_table(data.get('actions', []))}

</body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="path to sequence-data JSON")
    ap.add_argument("--out", default="out/Mercury-Scales-Sequence.pdf")
    args = ap.parse_args()

    data = json.loads(Path(args.data).read_text(encoding="utf-8"))
    emails = sorted(data["emails"], key=lambda e: e["n"])
    data["emails"] = emails
    brand, persona = load_brand_and_persona()

    shot_dir = Path(tempfile.mkdtemp(prefix="mercury_shots_"))
    print(f"rendering {len(emails)} emails -> screenshots in {shot_dir} ...")
    shots = screenshot_emails(emails, brand, persona, shot_dir)

    master = build_master_html(data, shots)
    master_path = shot_dir / "master.html"
    master_path.write_text(master, encoding="utf-8")

    out = REPO / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    print(f"composing PDF -> {out} ...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(master_path.as_uri(), wait_until="networkidle")
        page.wait_for_timeout(500)
        page.pdf(path=str(out), format="A4", print_background=True,
                 margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        browser.close()
    print(f"DONE: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
