# -*- coding: utf-8 -*-
"""Render a branded Team Minik company one-pager PDF (navy + gold), built from
public info on teamminik.com. For presenting the brand + offer alongside the
email campaign PDFs.

    py scripts/_make-teamminik-brand-pdf.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "out" / "teamminik-brand" / "Team-Minik-Overview.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

NAVY = "#10295A"
GOLD = "#DB1263"   # real brand accent is crimson/magenta, not gold
SLATE = "#333333"
MUTED = "#9E9E9E"

HTML = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
@page {{ size: A4; margin: 0; }}
* {{ box-sizing: border-box; }}
body {{ font-family:'Figtree',sans-serif; color:{SLATE}; margin:0; -webkit-print-color-adjust:exact; }}
.wrap {{ padding: 0 0 40px 0; }}
.hero {{ background:{NAVY}; color:#fff; padding:44px 54px 36px 54px; }}
.brand {{ display:flex; align-items:center; gap:12px; }}
.mark {{ width:34px; height:34px; }}
.name {{ font-size:26px; font-weight:800; letter-spacing:-0.4px; }}
.dot {{ color:{GOLD}; }}
.roa {{ font-size:11px; letter-spacing:1.5px; text-transform:uppercase; color:#9FB0C8; margin-left:auto; }}
.tag {{ font-size:30px; font-weight:800; letter-spacing:-0.6px; margin:26px 0 6px 0; line-height:1.15; }}
.tag .g {{ color:{GOLD}; }}
.lede {{ font-size:14px; color:#C7D2E0; max-width:620px; line-height:1.6; }}
.body {{ padding: 30px 54px 0 54px; }}
h2 {{ font-size:12px; font-weight:700; letter-spacing:1.2px; text-transform:uppercase; color:{NAVY}; margin:26px 0 10px; }}
.stats {{ display:flex; gap:0; margin:24px 0 8px; border:1px solid #E4E8EF; border-radius:8px; overflow:hidden; }}
.stat {{ flex:1; padding:16px 18px; border-right:1px solid #E4E8EF; }}
.stat:last-child {{ border-right:none; }}
.stat .num {{ font-size:22px; font-weight:800; color:{NAVY}; }}
.stat .lbl {{ font-size:10.5px; color:{MUTED}; margin-top:2px; }}
ul {{ margin:6px 0; padding-left:18px; }}
li {{ margin:5px 0; font-size:13px; line-height:1.5; }}
.two {{ display:flex; gap:36px; }}
.two > div {{ flex:1; }}
.box {{ background:#F7F9FC; border-left:3px solid {GOLD}; padding:14px 18px; margin:10px 0; border-radius:4px; font-size:13px; line-height:1.6; }}
.k {{ color:{NAVY}; font-weight:700; }}
.foot {{ display:flex; justify-content:space-between; margin-top:30px; padding-top:14px; border-top:1px solid #E4E8EF; font-size:11px; color:{MUTED}; }}
</style></head>
<body><div class="wrap">
  <div class="hero">
    <div class="brand">
      <svg class="mark" viewBox="0 0 22 22"><rect width="22" height="22" fill="#fff"/><path d="M4 16 V9 L11 4 L18 9 V16" fill="none" stroke="{GOLD}" stroke-width="1.9" stroke-linejoin="round"/></svg>
      <span class="name">Team Minik<span class="dot">.</span></span>
      <span class="roa">Powered by Realty of America</span>
    </div>
    <div class="tag">Unlock your Real Estate<br>Potential<span class="g">.</span></div>
    <div class="lede">A top-1-percent real estate team that hands agents real leads, coaching, and ownership, and gives sellers and buyers a proven team that handles the entire process.</div>
  </div>

  <div class="body">
    <div class="stats">
      <div class="stat"><div class="num">$354.4M+</div><div class="lbl">Career sales volume</div></div>
      <div class="stat"><div class="num">1,534+</div><div class="lbl">Clients served</div></div>
      <div class="stat"><div class="num">Top 1%</div><div class="lbl">Nationally ranked</div></div>
      <div class="stat"><div class="num">25 yrs</div><div class="lbl">Experience</div></div>
    </div>

    <h2>Who we are</h2>
    <p style="font-size:13px;line-height:1.6;margin:4px 0;">Led by <span class="k">Michelle Minik</span>, Team Minik operates under Realty of America with 16 licensed agents and $49.2M in 2025 team volume across 1,636 total closed units. Featured on the Today Show with Barbara Corcoran and on Fox 10 News. FastExpert Top 25 Agent in Arizona.</p>

    <div class="two">
      <div>
        <h2>For agents</h2>
        <ul>
          <li>Real leads handed to you, not bought by you</li>
          <li>85/15 split, $14,000 annual cap, then 100% retention</li>
          <li>No monthly fees, no desk fees, no hidden costs</li>
          <li>Coaching, marketing, and CRM included</li>
          <li>Equity and revenue share, build ownership not just commissions</li>
        </ul>
      </div>
      <div>
        <h2>For sellers &amp; buyers</h2>
        <ul>
          <li>A full team, not one solo agent juggling everyone</li>
          <li>Pricing backed by 1,600+ real closings</li>
          <li>Trusted partners for mortgage, title, and home warranty</li>
          <li>We handle the work, you make the decisions</li>
          <li>Free, no-obligation home valuation on request</li>
        </ul>
      </div>
    </div>

    <h2>Partners</h2>
    <div class="box">Fairway Home Mortgage <span style="color:{MUTED}">&middot;</span> Fidelity National Title <span style="color:{MUTED}">&middot;</span> Old Republic Home Protection</div>

    <div class="foot">
      <span><span class="k">Team Minik</span> &middot; Arizona, USA &middot; teamminik.com</span>
      <span>michelle@teamminik.com &middot; 602.488.5432</span>
    </div>
  </div>
</div></body></html>"""

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.set_content(HTML, wait_until="networkidle")
    page.wait_for_timeout(900)
    page.pdf(path=str(OUT), format="A4", print_background=True,
             margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
    b.close()
print("wrote", OUT, f"({OUT.stat().st_size} bytes)")
