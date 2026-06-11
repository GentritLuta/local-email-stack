"""restore-missing-slides.py — re-inject the two slides accidentally
deleted by the trim-decks.py bug: PERSONALIZATION (between Example
Sequence and Deliverability) and FUNCTIONAL COMPARISON (between Scale
Plan and Scenario Math). Then renumber every slide-num 01..NN.

Operates on the 3 source decks in docs/ and the 3 mirrors in
~/Aureon-Presentations/. Idempotent: skips files that already contain
the personalization anchor text.

Run:
    py scripts/restore-missing-slides.py
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRES_DIR = Path.home() / "Aureon-Presentations"

DECKS = [
    {
        "path": REPO / "docs" / "aureon-architecture-client.html",
        "client": "smh",
    },
    {
        "path": REPO / "docs" / "aureon-architecture-atal.html",
        "client": "atal",
    },
    {
        "path": REPO / "docs" / "aureon-architecture-otai.html",
        "client": "otai",
    },
    {
        "path": PRES_DIR / "Aureon-Listing-Engine-Client-Architecture.html",
        "client": "smh",
    },
    {
        "path": PRES_DIR / "Aureon-Listing-Engine-Atal.html",
        "client": "atal",
    },
    {
        "path": PRES_DIR / "Aureon-Listing-Engine-OTAI-Automates.html",
        "client": "otai",
    },
]

PERSONALIZATION = {
    "smh": {
        "client_name": "Sales Methodology Hub",
        "examples": [
            (
                "Jess Park, VP Sales, Acme Ltd (UK SaaS, just hired 5 AEs in 60 days)",
                "\"Saw Acme hired 5 AEs in 60 days. Most fresh AE classes hit quota at month 9 if onboarding is ad hoc. Our 6 week sales methodology gets them productive in 90 days. Worth a 15 minute look?\"",
            ),
            (
                "Daniel Owens, CRO, Northfield Software (Series B UK SaaS, sales team of 18)",
                "\"Saw Northfield closed Series B last quarter. The next 18 months kill teams that try to scale the playbook by memory. We codify it. UK based, 6 week programme, money back guarantee...\"",
            ),
            (
                "Helena Marsh, Sales Enablement Lead, Crayon Industries (no obvious signal)",
                "\"Saw your post about win rate plateauing at 22 percent. We work with UK enablement leads to lift that to 30 plus in one quarter via methodology, not more tooling. Two minute video shows how...\"",
            ),
        ],
        "variables": [
            "First name, role, tenure in role (LinkedIn)",
            "Company name, funding stage, last round date",
            "Sales team size and 90 day hiring delta",
            "Recent CRO or VP Sales hire",
            "Public ramp time complaints or churn signals",
            "Methodology stack currently in use (MEDDIC, BANT, Force, etc.)",
            "One specific public post or quote we can mirror",
        ],
    },
    "atal": {
        "client_name": "Atal Solid Rocks",
        "examples": [
            (
                "Maria Schmidt, Head of People, Lumen GmbH (DACH SaaS, 220 staff, post reorg)",
                "\"Saw the reorg announcement at Lumen last week. Tough call. We help DACH SMBs rebuild leadership confidence in the team that stays. Twelve week structured programme, money back guarantee. Worth a 15 minute look?\"",
            ),
            (
                "Thomas Becker, Geschaeftsfuehrer, Beta GmbH (Series B, 120 staff)",
                "\"Saw Beta closed your Series B last week. The 12 month playbook from here is usually hire 30 people and pray your team leads can absorb it. Most cannot. We coach them through it. Local in DACH, results guaranteed...\"",
            ),
            (
                "Sarah Mueller, Head of L and D, Gamma AG (no obvious signal)",
                "\"Saw your post about burnout in mid level managers last quarter. We run a structured twelve week leadership coaching programme that addresses exactly that pattern. Weniger Blabla, mehr Ergebnisse...\"",
            ),
        ],
        "variables": [
            "First name, role, tenure in role (LinkedIn)",
            "Company name, funding stage, last round date",
            "Employee count and 90 day hiring delta",
            "Recent layoffs or reorg signals",
            "Public Kununu or Glassdoor rating trajectory",
            "Recent People or L and D leadership hire",
            "One specific public post or quote we can mirror",
        ],
    },
    "otai": {
        "client_name": "OTAI Automates",
        "examples": [
            (
                "Mike Patterson, Owner, Patterson Construction Group (TX GC, 38 staff, $14M, just won Hays CISD bid)",
                "\"Saw Patterson won the Hays CISD bid last week. Congrats. We help GCs your size automate vendor COIs, lien waivers and QuickBooks before the paperwork wave hits. 14 to 20 day install, paid back in five months. Worth a 15 minute look?\"",
            ),
            (
                "David Chen, CEO, Chen Builders Inc. (CA design-build, $22M, hiring controller plus AP clerk)",
                "\"Saw the two back-office postings on Chen Builders this month. The honest math: an office manager plus an AP clerk runs you $130K to $160K a year. Our platform replaces about 70 percent of that workload for a fraction of one salary...\"",
            ),
            (
                "Jenna Walsh, President, Walsh Concrete LLC ($6M specialty trade, no obvious signal)",
                "\"Saw your Reddit post about chasing lien waivers from subs. It is not a discipline problem. It is a systems problem. Two minute video shows exactly how we fix that for GCs your size. Built for contractors who are done managing paper...\"",
            ),
        ],
        "variables": [
            "First name, role, tenure as owner / CEO (LinkedIn)",
            "Company name, revenue band, state, license number",
            "Staff count and 90 day back-office hiring delta",
            "Recent public RFP wins or project announcements",
            "Current PM and accounting stack (Procore, QBO, etc.)",
            "OSHA citation history and license renewal window",
            "One specific public post, podcast, or quote we can mirror",
        ],
    },
}

COMPARISON_ROWS = [
    ("ICP source", "Apollo and Sales Navigator scrape", "Five live signal streams refreshed daily"),
    ("Personalization", "First name and company variable", "Per account research, named trigger event"),
    ("Cadence", "12 to 50 touches over months", "7 touches over 28 days, then stop"),
    ("Sender pool", "1 mailbox, occasionally 2", "10 subdomains, snowball warmup curve"),
    ("Deliverability", "set and pray, no monitoring", "Bounce kill switch, per recipient timezone"),
    ("Reply handling", "Manual triage in shared inbox", "60 second routing plus intent classifier"),
    ("Compliance", "CAN SPAM lip service", "RFC 8058, one click unsubscribe baked in"),
    ("Copy quality", "Templated, signal blind", "Hormozi grade copy, signal aware, vertical aware"),
]

SLIDE_NUM_RX = re.compile(r'<div class="slide-num">(\d{2})</div>')


def build_personalization(client: str) -> str:
    p = PERSONALIZATION[client]
    parts = []
    for i, (persona, quote) in enumerate(p["examples"]):
        margin = "margin-top:10px;" if i > 0 else ""
        parts.append(
            f'      <div class="card" style="padding:16px;font-family:monospace;font-size:12px;color:var(--text-2);line-height:1.55;{margin}">\n'
            f'        <div style="color:var(--gold);margin-bottom:6px;">&gt; {persona}</div>\n'
            f'        <div>{quote}</div>\n'
            f'      </div>'
        )
    examples_html = "\n".join(parts)
    vars_html = "\n".join(f'        <li>{v}</li>' for v in p["variables"])
    return (
        '<!-- SLIDE: PERSONALIZATION (restored) -->\n'
        '<section class="slide">\n'
        '  <div class="tagline-bar">\n'
        '    <div><svg class="logo-mini"><use href="#aureonGlobe"/></svg><span class="logo-text">Aureon Global</span></div>\n'
        '    <div class="right">Quality Converts</div>\n'
        '  </div>\n'
        '\n'
        '  <div class="eyebrow">How each email is personalized</div>\n'
        '  <h1 class="title">Every email knows who it is going to.</h1>\n'
        f'  <p class="kicker">One template per cadence step. The variables get filled per account at send time, from the research record. Three real examples below, all pitching {p["client_name"]}.</p>\n'
        '\n'
        '  <div class="grid grid-2" style="margin-top:24px;gap:32px;">\n'
        '    <div>\n'
        '      <h3 style="color:var(--gold);font-size:15px;letter-spacing:1.2px;text-transform:uppercase;margin-bottom:14px;">Same step 1 template, three accounts</h3>\n'
        f'{examples_html}\n'
        '    </div>\n'
        '    <div>\n'
        '      <h3 style="color:var(--gold);font-size:15px;letter-spacing:1.2px;text-transform:uppercase;margin-bottom:14px;">Variables pulled per account</h3>\n'
        '      <ul class="cleanlist" style="font-size:13.5px;">\n'
        f'{vars_html}\n'
        '      </ul>\n'
        '      <div style="margin-top:18px;padding:14px 16px;border-left:2px solid var(--gold);font-size:12.5px;color:var(--text-2);line-height:1.55;">\n'
        '        <span style="color:var(--gold);font-weight:600;">Honesty rule.</span> If a variable is missing or unverified, the line is dropped, not faked. The buyer never reads a sentence that does not pass smell test.\n'
        '      </div>\n'
        '    </div>\n'
        '  </div>\n'
        '\n'
        '  <div class="slide-num">00</div>\n'
        '</section>\n'
        '\n'
    )


def build_comparison() -> str:
    row_parts = []
    for dim, typical, us in COMPARISON_ROWS:
        row_parts.append(
            f'      <div style="padding:14px 18px;border-bottom:1px solid var(--rule);font-size:13px;color:var(--text-2);">{dim}</div>\n'
            f'      <div style="padding:14px 18px;border-bottom:1px solid var(--rule);font-size:13px;color:var(--text-2);">{typical}</div>\n'
            f'      <div style="padding:14px 18px;border-bottom:1px solid var(--rule);font-size:13px;color:var(--text);background:rgba(212,175,55,0.06);font-weight:500;">{us}</div>'
        )
    rows_html = "\n".join(row_parts)
    return (
        '<!-- SLIDE: FUNCTIONAL COMPARISON (restored) -->\n'
        '<section class="slide">\n'
        '  <div class="tagline-bar">\n'
        '    <div><svg class="logo-mini"><use href="#aureonGlobe"/></svg><span class="logo-text">Aureon Global</span></div>\n'
        '    <div class="right">Quality Converts</div>\n'
        '  </div>\n'
        '\n'
        '  <div class="eyebrow">Functional comparison</div>\n'
        '  <h1 class="title">What a typical outbound stack does vs what we do.</h1>\n'
        '  <p class="kicker">Most outbound tooling stacks at SMBs are a list vendor plus a generic sequencer plus a tired sender. The engine below replaces every layer with a tighter, more honest version.</p>\n'
        '\n'
        '  <div style="margin-top:32px;border:1px solid var(--rule);border-radius:6px;overflow:hidden;display:grid;grid-template-columns:0.9fr 1.3fr 1.3fr;">\n'
        '    <div style="padding:14px 18px;background:rgba(212,175,55,0.08);font-size:11px;letter-spacing:1.6px;text-transform:uppercase;color:var(--muted);font-weight:700;">Dimension</div>\n'
        '    <div style="padding:14px 18px;background:rgba(212,175,55,0.08);font-size:11px;letter-spacing:1.6px;text-transform:uppercase;color:var(--muted);font-weight:700;">Typical outbound stack</div>\n'
        '    <div style="padding:14px 18px;background:rgba(212,175,55,0.12);font-size:11px;letter-spacing:1.6px;text-transform:uppercase;color:var(--gold);font-weight:700;">Aureon engine</div>\n'
        f'{rows_html}\n'
        '  </div>\n'
        '\n'
        '  <div class="slide-num">00</div>\n'
        '</section>\n'
        '\n'
    )


# Anchors: the bytes that mark the END of the section after which we insert.
EXAMPLE_END_RX = re.compile(
    r"<!--\s*SLIDE\s*7:\s*EXAMPLE SEQUENCE.*?</section>\s*\n",
    re.DOTALL,
)
SCALE_END_RX = re.compile(
    r"<!--\s*SLIDE\s*11:\s*SCALE PLAN.*?</section>\s*\n",
    re.DOTALL,
)


def restore(path: Path, client: str) -> tuple[bool, str]:
    if not path.exists():
        return False, f"SKIP (missing): {path}"
    html = path.read_text(encoding="utf-8")

    # Idempotency: if already restored, skip
    if "<!-- SLIDE: PERSONALIZATION (restored) -->" in html:
        return False, f"SKIP (already restored): {path}"

    p_html = build_personalization(client)
    c_html = build_comparison()

    m = EXAMPLE_END_RX.search(html)
    if not m:
        return False, f"FAIL (EXAMPLE SEQUENCE anchor not found): {path}"
    html = html[:m.end()] + "\n" + p_html + html[m.end():]

    m = SCALE_END_RX.search(html)
    if not m:
        return False, f"FAIL (SCALE PLAN anchor not found): {path}"
    html = html[:m.end()] + "\n" + c_html + html[m.end():]

    # Renumber all slide-num divs 01..NN in document order
    matches = list(SLIDE_NUM_RX.finditer(html))
    # Process in reverse to keep positions valid
    for i in range(len(matches) - 1, -1, -1):
        m = matches[i]
        new_num = f"{i + 1:02d}"
        html = (
            html[:m.start()]
            + f'<div class="slide-num">{new_num}</div>'
            + html[m.end():]
        )

    path.write_text(html, encoding="utf-8")
    return True, f"OK: {path} -- restored 2 slides, renumbered {len(matches)} slides"


def main() -> int:
    for deck in DECKS:
        _, msg = restore(deck["path"], deck["client"])
        print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
