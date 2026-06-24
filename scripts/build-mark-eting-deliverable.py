"""build-mark-eting-deliverable.py — ONE branded PDF: campaign setup + the full
7-email sequence, matched 1:1 to mark-eting.co (orange #f07307 + navy hero
gradient + the real logo). Replaces the two separate PDFs with a single document.

    py scripts/build-mark-eting-deliverable.py

Output: out/Mark-eting-Campaign.pdf  (+ .html)
"""
from __future__ import annotations
import base64
import html as _html
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from email_render import render_html  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

# Logo as a base64 data URI so it renders in EVERY Playwright context
# (set_content email screenshots AND the goto() master page) without depending
# on network or file:// access, which Playwright's set_content blocks.
_logo_bytes = (REPO / "out" / "assets" / "mark-eting-logo.jpg").read_bytes()
LOGO_LOCAL = "data:image/jpeg;base64," + base64.b64encode(_logo_bytes).decode("ascii")

# Brand tokens — verified 1:1 from the live site + logo.
ORANGE = "#f07307"
ORANGE_D = "#c25608"
NAVY = "#1a1a2e"
INK = "#0b0b0b"
SLATE = "#475569"
MUTED = "#8f8f8f"
RULE = "#ececec"
NAVY_GRADIENT = ("linear-gradient(135deg, #1a1a2e 0%, #16213e 25%, "
                 "#1a1a2e 50%, #2d1810 75%, #1a1a2e 100%)")

SAMPLE = {"greeting": "Sarah", "first_name": "Sarah", "company": "Apex Plumbing",
          "city": "Austin"}


def merge(s: str) -> str:
    for k, v in SAMPLE.items():
        s = s.replace("{" + k + "}", v)
    return s


def esc(s: str) -> str:
    return _html.escape(s or "")


def screenshot_emails(emails, brand, persona, shot_dir):
    shot_dir.mkdir(parents=True, exist_ok=True)
    # Render the emails with a LOCAL logo so the screenshot never depends on network.
    brand_local = json.loads(json.dumps(brand))
    brand_local.setdefault("legal", {})["logo_url"] = LOGO_LOCAL
    paths = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 700, "height": 900}, device_scale_factor=2)
        for e in emails:
            html = render_html(body=merge(e["body"]), persona=persona,
                               unsubscribe_token="preview-token-0000",
                               brand=brand_local, step_n=e["n"])
            page.set_content(html, wait_until="load")
            page.wait_for_timeout(400)
            shot = shot_dir / f"email_{e['n']}.png"
            page.screenshot(path=str(shot), full_page=True)
            paths.append(shot)
        browser.close()
    return paths


SETUP_SECTIONS = [
    ("The offer",
     "SEO and online visibility, managed end to end, so US service businesses get "
     "found on Google by the buyers already searching for them. Every sequence opens "
     "with a free written visibility teardown as the primary ask. The booking call is "
     "always the secondary option, never the cold pitch. The give carries the proof, "
     "so there is no need for fabricated case studies."),
    ("Who we target",
     "Established US service businesses, roughly 2M USD or more in revenue, all states. "
     "Two segments: trades and specialized services (plumbing, HVAC, roofing, electrical, "
     "general contractors, restoration, pest control), and professional services (law, "
     "accounting and CPA, dental, medspas, chiropractic and physical therapy, insurance, "
     "financial advisors, landscaping). Best-converting titles: Owner, Founder, CEO, "
     "General Manager, Managing Partner, VP or Director of Marketing, CMO."),
    ("Sending setup",
     "12 sending subdomains on getmark-eting.com with 12 rotating personas. Recipient-local "
     "08:00 to 17:00, weekdays only. Warmup ramp of 15 to 50 emails per domain per day so "
     "the new domain warms safely before full volume. One-click unsubscribe and a full legal "
     "footer on every email."),
    ("Lead sourcing and compliance",
     "US service-business websites (team and contact pages), every address verified before it "
     "can be sent to. A compliance gate automatically skips any site that states it does not "
     "accept marketing or unsolicited email. The lead pool refills on its own every day, kept "
     "above a 2x buffer of daily sending volume."),
    ("Replies, booking and reporting",
     "Positive replies route to your Google Calendar booking link and to mark@mark-eting.co. "
     "Warm replies that ask to talk can be answered automatically with the booking link. A "
     "daily campaign report goes to mark@mark-eting.co and info@aureonglobal.de: emails sent, "
     "delivered, open rate, reply rate, positive replies, and calls booked."),
]


# Expected performance — steady state after the 4-week warmup, ~150 sends/day
# across 12 subdomains x ~22 weekdays = ~3,300 emails/month. Ranges are grounded
# in published B2B cold-email benchmarks (Belkins 2025: 5.8% avg reply across
# 16.5M emails; Apollo/Instantly ~3.4%; booked-call rate 0.1-0.8%/send, "good"
# >0.4%) and the give-first design, which lifted our own controlled A/B from
# 0.3% to 5.4% reply. They are projections, not guarantees.
PERF_FUNNEL = [
    # label, conservative, target, pct_of_sent_for_bar
    ("Emails sent / month",   "3,300", "3,300", 100.0),
    ("Delivered (97%)",       "3,200", "3,200", 97.0),
    ("Opened (52-58%)",       "1,650", "1,860", 56.0),
    ("Replied (3-6%)",        "95",    "190",   5.8),
    ("Positive replies",      "30",    "75",    2.3),
    ("Calls booked",          "12",    "25",    0.8),
]
PERF_NOTES = [
    ("Ramp, not day one",
     "Month 1 lands at roughly 50 to 60 percent of these numbers while the 12 "
     "subdomains warm from 15 to 50 emails per day. Steady state is reached in "
     "about four weeks, and the figures above describe that steady state."),
    ("Why these ranges are realistic",
     "Typical B2B cold email replies at 3 to 6 percent (Belkins 2025: 5.8 percent "
     "average across 16.5M emails). The give-first opener used here lifted our own "
     "controlled A/B on another brand from 0.3 to 5.4 percent reply, so the target "
     "column sits at the top of the benchmark band, not above it."),
    ("The honest caveat",
     "There is no US track record for this brand yet, so the free written teardown "
     "has to carry the proof in the early weeks. A booked-call rate of 0.4 to 0.7 "
     "percent per email is the established good-operator band; reaching it depends "
     "on reply speed and a clean warmup. Treat month 1 as calibration."),
]


def perf_html() -> str:
    bars = []
    for label, cons, tgt, pct in PERF_FUNNEL:
        w = max(pct, 3.0)  # keep tiny bars visible
        rng = tgt if cons == tgt else f"{cons} &ndash; {tgt}"
        bars.append(f"""<div class='fbar'>
          <div class='flabel'>{esc(label)}</div>
          <div class='ftrack'><div class='ffill' style='width:{w:.1f}%'></div></div>
          <div class='fval'>{rng}</div>
        </div>""")
    rows = "".join(
        f"<tr><td class='p1'>{esc(l)}</td><td class='p2'>{esc(c)}</td>"
        f"<td class='p3'>{esc(t)}</td></tr>"
        for l, c, t, _ in PERF_FUNNEL)
    notes = "".join(
        f"<section class='setup'><h3>{esc(h)}</h3><p>{esc(b)}</p></section>"
        for h, b in PERF_NOTES)
    return f"""<section class="page">
    <div class="kick">Expected performance</div>
    <div class="h2wrap"><img src="{LOGO_LOCAL}"><h2>What to expect</h2></div>
    <p class="lede">A monthly projection at steady state (about 150 emails a day across 12 subdomains). Figures are grounded in published B2B cold-email benchmarks and the give-first design, shown as a conservative-to-target range. They are projections, not guarantees.</p>
    <div class="funnel">{''.join(bars)}</div>
    <table class="ptable"><thead><tr><th>Metric (per month)</th><th>Conservative</th><th>Target</th></tr></thead>
      <tbody>{rows}</tbody></table>
    {notes}
  </section>"""


def build_html(profile, emails, shots) -> str:
    brand = profile.get("brand") or {}
    wordmark = brand.get("wordmark") or "Mark-eting"
    tagline = brand.get("tagline") or ""
    site = brand.get("site") or "mark-eting.co"

    # Cadence table + email cards
    day = 0
    cad_rows, cards = [], []
    for e, shot in zip(emails, shots):
        day += int(e.get("delay_days", 0))
        when = "day 0 (immediately)" if e["n"] == 1 else f"day {day}"
        cad_rows.append(
            f"<tr><td class='c1'>E{e['n']}</td><td class='c2'>{when}</td>"
            f"<td class='c3'>{esc(e.get('angle',''))}</td>"
            f"<td class='c4'>{esc(merge(e['subject']))}</td></tr>")
        cards.append(f"""<section class="card">
          <div class="card-head">
            <span class="step">EMAIL {e['n']}</span>
            <span class="when">{esc(when)}</span>
            <span class="angle">{esc(e.get('angle',''))}</span>
          </div>
          <div class="subjline"><span class="sk">Subject</span> {esc(merge(e['subject']))}</div>
          <div class="inbox"><img src="file:///{shot.as_posix()}" alt="Email {e['n']}"></div>
        </section>""")

    setup_html = "".join(
        f"<section class='setup'><h3>{esc(title)}</h3><p>{esc(body)}</p></section>"
        for title, body in SETUP_SECTIONS)

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
  @page {{ size: A4; margin: 14mm 14mm 15mm; }}
  @page :first {{ margin: 0; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:'Inter',-apple-system,'Segoe UI',sans-serif; color:{INK}; font-size:13px; line-height:1.65; }}
  h1,h2,h3 {{ font-weight:800; letter-spacing:-.02em; margin:0; }}

  /* COVER — site hero gradient, 1:1 */
  .cover {{ height:297mm; width:210mm; background:{NAVY}; background:{NAVY_GRADIENT};
            color:#fff; padding:34mm 22mm; page-break-after:always; position:relative; }}
  .cover .logo {{ width:74px; height:74px; border-radius:16px; display:block; }}
  .cover h1 {{ font-size:46px; line-height:1.05; margin:30px 0 14px; max-width:14em; }}
  .cover h1 .amp {{ color:{ORANGE}; }}
  .cover .sub {{ font-size:17px; color:rgba(255,255,255,.72); max-width:30em; font-weight:500; }}
  .cover .rule {{ height:4px; width:64px; background:{ORANGE}; margin:26px 0; border-radius:2px; }}
  .cover .meta {{ position:absolute; bottom:30mm; left:22mm; right:22mm; color:rgba(255,255,255,.55); font-size:12px; }}
  .cover .meta b {{ color:#fff; font-weight:700; }}

  /* SECTION HEADERS */
  .page {{ page-break-before: always; }}
  .h2wrap {{ display:flex; align-items:center; gap:12px; margin:0 0 8px; }}
  .h2wrap img {{ width:30px; height:30px; border-radius:7px; }}
  h2 {{ font-size:26px; color:{INK}; }}
  .kick {{ font-size:11px; text-transform:uppercase; letter-spacing:.14em; color:{ORANGE}; font-weight:700; margin-bottom:4px; }}
  .lede {{ color:{SLATE}; max-width:42em; margin:4px 0 18px; }}

  /* SETUP cards */
  .setup {{ border-left:3px solid {ORANGE}; padding:2px 0 2px 16px; margin:0 0 16px; break-inside:avoid; }}
  .setup h3 {{ font-size:15px; color:{INK}; margin-bottom:4px; }}
  .setup p {{ margin:0; color:{SLATE}; }}

  /* Performance funnel */
  .funnel {{ margin:18px 0 22px; }}
  .fbar {{ display:flex; align-items:center; gap:12px; margin-bottom:9px; }}
  .flabel {{ width:170px; font-size:12px; font-weight:600; color:{INK}; flex:0 0 170px; }}
  .ftrack {{ flex:1; background:#f1f1f1; border-radius:5px; height:22px; overflow:hidden; }}
  .ffill {{ height:100%; background:{ORANGE}; background:linear-gradient(90deg,{ORANGE},{ORANGE_D}); border-radius:5px; }}
  .fval {{ width:96px; flex:0 0 96px; text-align:right; font-size:12px; font-weight:700; color:{ORANGE_D}; }}
  .ptable {{ width:100%; border-collapse:collapse; margin:2px 0 8px; }}
  .ptable .p1 {{ width:46%; font-weight:600; }} .ptable .p2 {{ width:27%; color:{SLATE}; }} .ptable .p3 {{ width:27%; font-weight:700; color:{ORANGE_D}; }}

  /* Cadence table */
  table {{ width:100%; border-collapse:collapse; margin-top:8px; }}
  th {{ text-align:left; font-size:10px; text-transform:uppercase; letter-spacing:.07em; color:{MUTED}; border-bottom:2px solid {RULE}; padding:0 10px 7px; }}
  td {{ padding:9px 10px; border-bottom:1px solid {RULE}; vertical-align:top; }}
  .c1 {{ font-weight:800; color:{ORANGE}; width:8%; }} .c2 {{ width:22%; color:{SLATE}; }}
  .c3 {{ width:28%; color:{SLATE}; font-style:italic; }} .c4 {{ width:42%; font-weight:600; }}

  /* Email cards */
  .card {{ page-break-before: always; }}
  .card-head {{ display:flex; align-items:center; gap:12px; margin-bottom:10px; }}
  .step {{ background:{ORANGE}; color:#fff; font-weight:800; font-size:11px; letter-spacing:.06em; padding:4px 11px; border-radius:6px; }}
  .when {{ font-size:12px; color:{SLATE}; font-weight:600; }}
  .angle {{ font-size:11px; color:{MUTED}; font-style:italic; margin-left:auto; }}
  .subjline {{ font-size:15px; font-weight:700; margin-bottom:10px; color:{INK}; }}
  .sk {{ font-size:10px; text-transform:uppercase; letter-spacing:.06em; font-weight:800; color:{MUTED}; margin-right:6px; }}
  .inbox {{ text-align:center; }}
  .inbox img {{ display:block; margin:0 auto; width:auto; height:auto; max-width:174mm; max-height:215mm; border:1px solid {RULE}; border-radius:12px; box-shadow:0 2px 8px rgba(0,0,0,.10); }}
</style></head><body>

  <div class="cover">
    <img class="logo" src="{LOGO_LOCAL}" alt="Mark-eting">
    <h1>Cold Email Campaign <span class="amp">.</span></h1>
    <div class="rule"></div>
    <div class="sub">{esc(tagline)}</div>
    <div class="meta"><b>{esc(wordmark)}</b> &nbsp;·&nbsp; {esc(site)} &nbsp;·&nbsp; Campaign setup and the full 7-email sequence, rendered exactly as it lands in the inbox.</div>
  </div>

  <section class="page">
    <div class="kick">Campaign setup</div>
    <div class="h2wrap"><img src="{LOGO_LOCAL}"><h2>How the campaign runs</h2></div>
    <p class="lede">Everything that powers the outreach, end to end. The give-first teardown leads every conversation; the booking call is always the optional second step.</p>
    {setup_html}
  </section>

  {perf_html()}

  <section class="page">
    <div class="kick">The sequence</div>
    <div class="h2wrap"><img src="{LOGO_LOCAL}"><h2>Seven touches over 28 days</h2></div>
    <p class="lede">One clear ask per email. Founder-to-owner voice, no hype. Merge fields shown filled for a sample prospect ({esc(SAMPLE['greeting'])} at {esc(SAMPLE['company'])}).</p>
    <table><thead><tr><th>Step</th><th>Timing</th><th>Angle</th><th>Subject</th></tr></thead>
      <tbody>{''.join(cad_rows)}</tbody></table>
  </section>

  {''.join(cards)}
</body></html>"""


def main() -> int:
    profile = json.loads((REPO / "profiles" / "mark-eting.json").read_text(encoding="utf-8"))
    brand = profile.get("brand")
    personas = profile.get("personas") or []
    persona = personas[0] if personas else {}
    variants = json.loads((REPO / "sequences" / "mark-eting-default" / "variants.json").read_text(encoding="utf-8"))
    emails = sorted(variants["variants"], key=lambda e: e["n"])

    shot_dir = Path(tempfile.mkdtemp(prefix="mark_eting_deliv_"))
    print(f"rendering {len(emails)} emails ...")
    shots = screenshot_emails(emails, brand, persona, shot_dir)
    master = build_html(profile, emails, shots)
    (shot_dir / "master.html").write_text(master, encoding="utf-8")

    out = REPO / "out" / "Mark-eting-Campaign.pdf"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.with_suffix(".html").write_text(master, encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto((shot_dir / "master.html").as_uri(), wait_until="networkidle")
        page.wait_for_timeout(500)
        page.pdf(path=str(out), format="A4", print_background=True,
                 margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        browser.close()
    print(f"DONE: {out}")
    print(f"      {out.with_suffix('.html')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
