# -*- coding: utf-8 -*-
"""Render the Atlas X-Ads brief (copy variants + targeting + budget + conversion
playbook) to a branded PDF for presenting.

    py scripts/_make-atlas-ads-brief-pdf.py
"""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "out" / "atlas-x-ads" / "Atlas-X-Ads-Brief.pdf"
OUT.parent.mkdir(parents=True, exist_ok=True)

YELLOW = "#E0BA00"; CRIMSON = "#c9165b"; INK = "#0a0a0a"; SLATE = "#33373f"; MUTED = "#7a828c"

HTML = f"""<!doctype html><html><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
@page {{ size:A4; margin:0; }}
*{{box-sizing:border-box;margin:0}} body{{font-family:'Inter',sans-serif;color:{SLATE};-webkit-print-color-adjust:exact;font-size:11.5px;line-height:1.55}}
.page{{padding:38px 46px;page-break-after:always;min-height:100vh}} .page:last-child{{page-break-after:auto}}
.hero{{background:{INK};color:#fff;margin:-38px -46px 26px;padding:34px 46px}}
.logo{{display:flex;align-items:center;gap:9px;font-weight:800;font-size:20px}}
.bolt{{width:24px;height:24px}}
h1{{font-size:27px;font-weight:900;letter-spacing:-0.6px;margin-top:18px}}
h1 .y{{color:{YELLOW}}}
.lede{{color:#b9c0c9;font-size:13px;margin-top:6px;max-width:640px}}
h2{{font-size:12.5px;font-weight:800;letter-spacing:1px;text-transform:uppercase;color:{INK};margin:22px 0 10px;border-bottom:2px solid {YELLOW};padding-bottom:5px}}
h3{{font-size:12px;font-weight:800;color:{CRIMSON};margin:14px 0 4px}}
table{{width:100%;border-collapse:collapse;margin:6px 0}}
th,td{{text-align:left;padding:7px 9px;border:1px solid #e5e7eb;vertical-align:top}}
th{{background:#faf7e8;font-size:10px;text-transform:uppercase;letter-spacing:.5px;color:{INK}}}
.var{{background:#f8f9fb;border:1px solid #e5e7eb;border-left:3px solid {YELLOW};border-radius:5px;padding:10px 13px;margin:8px 0}}
.var .h{{font-weight:800;color:{INK};font-size:12.5px}}
.var .b{{margin-top:3px}}
.var .m{{color:{MUTED};font-size:10.5px;margin-top:4px}}
ul{{margin:5px 0;padding-left:18px}} li{{margin:3px 0}}
.k{{color:{INK};font-weight:700}}
.tag{{display:inline-block;background:rgba(201,22,91,.1);color:{CRIMSON};border:1px solid {CRIMSON};font-size:9.5px;font-weight:700;padding:2px 8px;border-radius:999px;margin-left:6px}}
.note{{background:#fff7f9;border:1px solid #f3c9d8;border-radius:6px;padding:11px 14px;margin:10px 0;font-size:11px}}
.foot{{display:flex;justify-content:space-between;margin-top:24px;padding-top:12px;border-top:1px solid #e5e7eb;font-size:10px;color:{MUTED}}}
.grid2{{display:flex;gap:18px}} .grid2>div{{flex:1}}
</style></head><body>

<div class="page">
  <div class="hero">
    <div class="logo"><svg class="bolt" viewBox="0 0 22 22"><rect width="22" height="22" rx="6" fill="{YELLOW}"/><path d="M12 3 L6 12 H10 L9 19 L16 9 H11.5 Z" fill="{INK}"/></svg>AlgoAlpha</div>
    <h1>Atlas <span class="y">X Ads</span> — Creative, Copy &amp; Conversion Plan</h1>
    <div class="lede">New ad creatives and copy for Atlas, the AI backtester, plus targeting, budget, and a conversion-optimization playbook for X Ads Manager. Prepared 2026-06-07.</div>
  </div>

  <h2>The product (what we are selling)</h2>
  <p><span class="k">Atlas</span> is AlgoAlpha's AI-powered backtester and strategy-discovery tool. It scans the market with AI and surfaces strategies ranked by win rate, net profit, and risk ratio, with no coding and no manual chart grind. It is not sold standalone: it is bundled into the Indicators plan ($24.97/mo), Signals ($55.97/mo), and the VIP Bundle ($68.97/mo). Brand line: <span class="k">Signal first. Then trade.</span> 79,000+ traders.</p>

  <h2>The 4 creatives (attached as PNGs in this folder)</h2>
  <table>
    <tr><th>File</th><th>Size / placement</th><th>Angle</th></tr>
    <tr><td>atlas-landscape-A_1200x628.png</td><td>1.91:1 — website card / single image</td><td>"Stop hunting for strategies. Let the AI find them." (pain → relief)</td></tr>
    <tr><td>atlas-landscape-B_1200x628.png</td><td>1.91:1 — website card / single image</td><td>"Win rate, profit and risk" (proof / metrics-led)</td></tr>
    <tr><td>atlas-square-A_1080x1080.png</td><td>1:1 — feed</td><td>"What if your backtesting ran itself?" (curiosity hook)</td></tr>
    <tr><td>atlas-square-B_1080x1080.png</td><td>1:1 — feed</td><td>"Manual backtesting vs Atlas" (before/after contrast)</td></tr>
  </table>
  <p class="m" style="color:{MUTED};font-size:10.5px">Use landscape for the Website Traffic / Website Conversions objective (clickable card). Use square for in-feed awareness and retargeting. Pair each image with a copy variant below and A/B at least 2 creatives per ad group.</p>

  <div class="foot"><span><span class="k">AlgoAlpha</span> · Atlas X Ads brief · algoalpha.io</span><span>Signal first. Then trade.</span></div>
</div>

<div class="page">
  <h2>Ad copy — ready to paste <span class="tag">A/B THESE</span></h2>
  <p style="font-size:10.5px;color:{MUTED}">X single-image ad: headline shows under the image (~70 chars), the post/primary text sits above (first ~120 chars matter most). No exclamation marks per AlgoAlpha brand. Each block = primary text / headline / CTA button.</p>

  <h3>Variant 1 — Pain → relief</h3>
  <div class="var"><div class="b"><span class="k">Primary:</span> You do not need more screen time. You need strategies that actually have an edge. Atlas runs the backtesting with AI and hands you the ones worth trading.</div>
    <div class="b"><span class="k">Headline:</span> Stop hunting for strategies. Let the AI find them.</div>
    <div class="m">CTA button: <span class="k">Start free trial</span> · pair with landscape-A</div></div>

  <h3>Variant 2 — Proof / metrics</h3>
  <div class="var"><div class="b"><span class="k">Primary:</span> Atlas scores strategies on win rate, net profit, and risk ratio, then ranks them for you. No code. Backtested across real market history.</div>
    <div class="b"><span class="k">Headline:</span> Strategies optimized for win rate, profit and risk.</div>
    <div class="m">CTA button: <span class="k">Learn more</span> · pair with landscape-B</div></div>

  <h3>Variant 3 — Curiosity hook</h3>
  <div class="var"><div class="b"><span class="k">Primary:</span> What if your backtesting ran itself while you slept. Atlas does the heavy lifting with AI, you just trade the setups that pass.</div>
    <div class="b"><span class="k">Headline:</span> What if your backtesting ran itself?</div>
    <div class="m">CTA button: <span class="k">Sign up</span> · pair with square-A</div></div>

  <h3>Variant 4 — Before / after</h3>
  <div class="var"><div class="b"><span class="k">Primary:</span> Manual backtesting: hours per strategy and easy to fool yourself. With Atlas: seconds, ranked by real metrics, no code. Join 79,000+ traders.</div>
    <div class="b"><span class="k">Headline:</span> Manual backtesting vs Atlas. It is not close.</div>
    <div class="m">CTA button: <span class="k">Get started</span> · pair with square-B</div></div>

  <h3>Variant 5 — Social proof / FOMO</h3>
  <div class="var"><div class="b"><span class="k">Primary:</span> 79,000+ traders use AlgoAlpha to find signals before they trade. Atlas is the AI that finds the strategy first, so you are not guessing.</div>
    <div class="b"><span class="k">Headline:</span> Signal first. Then trade. Now with Atlas AI.</div>
    <div class="m">CTA button: <span class="k">Start free trial</span> · pair with landscape-A or square-A</div></div>

  <div class="foot"><span><span class="k">AlgoAlpha</span> · Atlas X Ads brief · algoalpha.io</span><span>page 2 / 3</span></div>
</div>

<div class="page">
  <h2>Targeting &amp; budget (X Ads Manager setup)</h2>
  <div class="grid2">
    <div>
      <h3>Objective</h3>
      <ul>
        <li><span class="k">Cold:</span> Website Conversions (optimize for the trial signup event), not "Traffic". Traffic buys clicks, conversions buy signups.</li>
        <li><span class="k">Warm:</span> a second Conversions campaign for retargeting.</li>
      </ul>
      <h3>Audiences</h3>
      <ul>
        <li>Keywords: backtesting, trading strategy, TradingView, crypto signals, algo trading, price action, scalping, swing trading.</li>
        <li>Follower look-alikes: @TradingView and large crypto-trading / fintwit accounts.</li>
        <li>Interests: Investing, Cryptocurrencies, Day trading.</li>
        <li>Retargeting: site visitors (last 30 days), video viewers (50%+), and anyone who engaged with the ads.</li>
      </ul>
    </div>
    <div>
      <h3>Budget &amp; bidding</h3>
      <ul>
        <li>Start lean: 3 ad groups x 1 angle each, ~$20–30/day per group for 5–7 days to gather data.</li>
        <li>Autobid first, then switch winners to target-cost once you know your cost-per-trial.</li>
        <li>Kill any ad group above ~2x your target cost-per-signup after 1,000+ impressions.</li>
      </ul>
      <h3>Structure</h3>
      <ul>
        <li>1 campaign (Conversions) → 3 ad groups (Pain, Proof, Curiosity) → 2 creatives each.</li>
        <li>Separate campaign for retargeting with the before/after + social-proof creatives.</li>
      </ul>
    </div>
  </div>

  <h2>Conversion playbook — getting the most signups</h2>
  <ul>
    <li><span class="k">Match the click to the page.</span> Send each ad to a landing page that repeats the ad's exact promise (e.g. the "AI finds strategies" headline). Mismatched landing pages are the #1 conversion killer.</li>
    <li><span class="k">Track the real event.</span> Install the X pixel and fire a conversion on trial-start, not on page-view. Optimize toward that event, not clicks.</li>
    <li><span class="k">Lead with the free trial.</span> "Start free trial" converts colder traffic than "Buy". Let the product sell the upgrade.</li>
    <li><span class="k">Show price honestly.</span> "From $24.97/mo, cancel anytime" filters tire-kickers and raises signup quality.</li>
    <li><span class="k">Retarget hard.</span> Most signups come on the 2nd–4th touch. Budget 25–35% to retargeting; that is usually the cheapest cost-per-signup.</li>
    <li><span class="k">Refresh creative every ~7–10 days.</span> X audiences fatigue fast; rotate the 4 creatives and pause the worst CTR weekly.</li>
    <li><span class="k">Add a video later.</span> A 10–15s screen-capture of Atlas ranking strategies will likely beat any static. Worth testing once statics have a baseline.</li>
  </ul>

  <div class="note"><span class="k">What I could not do from here:</span> I cannot log into your X Ads Manager, so I could not pull the <span class="k">current</span> Atlas campaign numbers (spend, CTR, CPC, cost-per-signup, which ad groups convert). To analyze and tune the live campaign, paste these creatives + copy in, run for ~5–7 days, then send me a screenshot or CSV export of the campaign breakdown and I will tell you exactly what to scale, cut, and re-bid.</div>

  <div class="foot"><span><span class="k">AlgoAlpha</span> · Atlas X Ads brief · algoalpha.io</span><span>page 3 / 3</span></div>
</div>
</body></html>"""

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
