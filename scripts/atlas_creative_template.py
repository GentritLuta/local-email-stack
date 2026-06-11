# -*- coding: utf-8 -*-
"""atlas_creative_template.py — reusable AlgoAlpha "Atlas" ad-creative template.

Config-driven generator for X (Twitter) image ads for AlgoAlpha's Atlas AI
backtester. Each creative is a single entry in CREATIVES; the shared render()
applies the brand (yellow #ffd400 + magenta #c9165b, dark UI, Inter) AND a real
product visual that matches the claim: a mocked Atlas results panel (ranked
strategies with win-rate / net-profit / risk), an equity curve, or a
before/after split. So the ad SHOWS the product, not just text on a gradient.

Copy uses high-conversion persuasion structure (clear dream outcome, proof,
low effort/risk, one bold claim + one CTA). "Hormozi" never appears in output.

Sizes: 1.91:1 (1200x628) website card + 1:1 (1080x1080) square feed.

    py scripts/atlas_creative_template.py                 # all angles, both sizes
    py scripts/atlas_creative_template.py pain proof      # only these angle keys

Add an angle: append a dict to CREATIVES. Output: out/atlas-x-ads/<key>_<W>x<H>.png
"""
from __future__ import annotations
import asyncio
import sys
from pathlib import Path
from playwright.async_api import async_playwright

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "out" / "atlas-x-ads"
OUT.mkdir(parents=True, exist_ok=True)

B = {
    "name": "AlgoAlpha", "tag": "Signal first. Then trade.",
    "yellow": "#ffd400", "magenta": "#c9165b", "green": "#16c784", "red": "#ff4d6d",
    "ink": "#0a0a0a", "bg": "#0a0d13", "card": "#10151f", "card2": "#0d121b",
    "border": "#1c2532", "grey": "#8b97a7", "grey2": "#5b6675",
    "proof": "79,000+ traders", "price": "From $24.97/mo",
}
FONT = ('<link href="https://fonts.googleapis.com/css2?'
        'family=Inter:wght@400;500;600;700;800;900&family=JetBrains+Mono:wght@500;700&display=swap" rel="stylesheet">')
MONO = "'JetBrains Mono',ui-monospace,monospace"
SIZES = [(1200, 628), (1080, 1080)]


# ---------------------------------------------------------------- visuals -----
def equity_curve(w, h, up=True, accent=None):
    """SVG equity / pnl curve that trends up (the dream outcome)."""
    accent = accent or B["green"]
    import math
    pts = []
    n = 26
    for i in range(n):
        x = i / (n - 1)
        # rising curve with a little noise baked in deterministically
        base = x ** 0.7 if up else (1 - x) ** 0.7
        wobble = 0.05 * math.sin(i * 1.7) + 0.03 * math.sin(i * 0.6)
        y = base + wobble
        pts.append((x * w, h - (0.12 + 0.76 * max(0, min(1, y))) * h))
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    area = f"0,{h} " + line + f" {w},{h}"
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="display:block;">'
            f'<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{accent}" stop-opacity="0.35"/>'
            f'<stop offset="1" stop-color="{accent}" stop-opacity="0"/></linearGradient></defs>'
            f'<polygon points="{area}" fill="url(#g)"/>'
            f'<polyline points="{line}" fill="none" stroke="{accent}" stroke-width="3" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" r="5" fill="{accent}"/></svg>')


def candles(w, h):
    """A compact candlestick strip for chart-flavored visuals."""
    import math
    n = 18
    cw = w / n
    out = []
    for i in range(n):
        cx = i * cw + cw / 2
        mid = h * (0.5 + 0.18 * math.sin(i * 0.8))
        body = 14 + 10 * abs(math.sin(i * 1.3))
        wick = body + 12
        up = math.sin(i * 0.8 + 0.5) > 0
        col = B["green"] if up else B["red"]
        out.append(f'<line x1="{cx:.1f}" y1="{mid-wick/2:.1f}" x2="{cx:.1f}" y2="{mid+wick/2:.1f}" stroke="{col}" stroke-width="2"/>')
        out.append(f'<rect x="{cx-cw*0.28:.1f}" y="{mid-body/2:.1f}" width="{cw*0.56:.1f}" height="{body:.1f}" rx="1.5" fill="{col}"/>')
    return f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}" style="display:block;">{"".join(out)}</svg>'


def strategy_panel(big=False, highlight_top=True):
    """Mocked Atlas results panel: ranked strategies with metrics. The core
    'this is what the product gives you' visual."""
    rows = [
        ("RSI Divergence + Trend", "68.4%", "+214%", "2.9", True),
        ("Liquidity Sweep Reversal", "63.1%", "+186%", "2.4", False),
        ("Momentum Breakout v3", "61.7%", "+158%", "2.1", False),
        ("VWAP Mean Reversion", "59.2%", "+131%", "1.8", False),
    ]
    fs = 17 if big else 14
    hfs = 12 if big else 10
    pad = "20px 22px" if big else "16px 18px"
    head = (f'<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">'
            f'<div style="display:flex;align-items:center;gap:8px;">'
            f'<span style="width:8px;height:8px;border-radius:50%;background:{B["green"]};box-shadow:0 0 8px {B["green"]};"></span>'
            f'<span style="font-size:{hfs+1}px;font-weight:700;color:#fff;letter-spacing:.3px;">ATLAS · STRATEGIES FOUND</span></div>'
            f'<span style="font-size:{hfs}px;color:{B["grey"]};font-family:{MONO};">scanned 8,412 setups</span></div>')
    colhead = (f'<div style="display:grid;grid-template-columns:1fr 70px 84px 56px;gap:10px;'
               f'font-size:{hfs}px;color:{B["grey2"]};letter-spacing:.5px;text-transform:uppercase;padding:0 4px 8px;">'
               f'<span>Strategy</span><span style="text-align:right;">Win</span>'
               f'<span style="text-align:right;">Net P/L</span><span style="text-align:right;">Risk</span></div>')
    body = ""
    for name, win, pnl, risk, top in rows:
        bg = f'background:rgba(255,212,0,0.10);border:1px solid rgba(255,212,0,0.45);' if (top and highlight_top) else f'background:{B["card2"]};border:1px solid {B["border"]};'
        star = f'<span style="color:{B["yellow"]};">★ </span>' if (top and highlight_top) else ''
        body += (f'<div style="display:grid;grid-template-columns:1fr 70px 84px 56px;gap:10px;align-items:center;'
                 f'{bg}border-radius:10px;padding:{"13px 14px" if big else "11px 12px"};margin-bottom:8px;">'
                 f'<span style="font-size:{fs}px;font-weight:600;color:#fff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{star}{name}</span>'
                 f'<span style="font-size:{fs}px;font-weight:700;color:{B["green"]};text-align:right;font-family:{MONO};">{win}</span>'
                 f'<span style="font-size:{fs}px;font-weight:700;color:{B["yellow"]};text-align:right;font-family:{MONO};">{pnl}</span>'
                 f'<span style="font-size:{fs}px;font-weight:600;color:#fff;text-align:right;font-family:{MONO};">{risk}</span></div>')
    return (f'<div style="background:{B["card"]};border:1px solid {B["border"]};border-radius:16px;padding:{pad};'
            f'box-shadow:0 20px 60px rgba(0,0,0,0.5);">{head}{colhead}{body}</div>')


def vs_panel(big=False):
    fs = 18 if big else 15
    def col(title, color, items, border, icon):
        lis = "".join(
            f'<div style="display:flex;align-items:center;gap:9px;margin:0 0 12px;font-size:{fs}px;color:#cfd6df;">'
            f'<span style="color:{color};font-weight:800;">{icon}</span>{x}</div>' for x in items)
        return (f'<div style="flex:1;background:{B["card"]};border:1px solid {border};border-radius:14px;padding:{"24px" if big else "20px"};">'
                f'<div style="color:{color};font-weight:800;font-size:{fs+2}px;margin-bottom:16px;">{title}</div>{lis}</div>')
    left = col("By hand", B["red"], ["Hours per strategy", "Easy to fool yourself", "Slow, manual charting"], B["border"], "✕")
    right = col("With Atlas", B["green"], ["Seconds, not hours", "Ranked by real metrics", "AI scans for you"], B["yellow"], "✓")
    return f'<div style="display:flex;gap:16px;">{left}{right}</div>'


# ---------------------------------------------------------------- angles -------
# visual: 'panel' (strategy results) | 'curve' (equity) | 'candles' | 'vs'
CREATIVES = [
    {"key": "pain", "pill": "NEW · ATLAS AI", "headline": "Stop hunting for strategies.",
     "highlight": "Let the AI find them.",
     "sub": "Atlas scans thousands of setups and surfaces the ones with real edge.",
     "cta": "Try Atlas free", "foot": f"Join {B['proof']}", "visual": "panel"},

    {"key": "proof", "pill": "ATLAS AI BACKTESTER", "headline": "Ranked by win rate,",
     "highlight": "profit and risk.",
     "sub": "Every setup scored on the metrics that matter, backtested on real history.",
     "cta": "Start free trial", "foot": f"{B['price']} · cancel anytime", "visual": "panel"},

    {"key": "curiosity", "pill": "BACKTESTING ON AUTOPILOT", "headline": "What if your backtesting",
     "highlight": "ran itself?",
     "sub": "Atlas does the heavy lifting with AI. You just trade the setups that pass.",
     "cta": "Try Atlas free", "foot": f"{B['tag']}", "visual": "curve"},

    {"key": "vs", "pill": "MANUAL vs ATLAS", "headline": "Manual backtesting",
     "highlight": "vs Atlas.", "sub": "",
     "cta": "Get Atlas", "foot": f"Bundled {B['price'].lower()}", "visual": "vs"},

    {"key": "time", "pill": "HOURS → SECONDS", "headline": "Find an edge in seconds,",
     "highlight": "not weekends.",
     "sub": "What took a weekend of charting, Atlas does while you sleep.",
     "cta": "Try Atlas free", "foot": f"Join {B['proof']}", "visual": "curve"},

    {"key": "social", "pill": "WHY 79,000+ TRADERS", "headline": "Signal first.",
     "highlight": "Then trade.",
     "sub": "79,000+ traders find the move before they make it. Atlas finds the strategy first.",
     "cta": "Start free trial", "foot": f"{B['price']} · cancel anytime", "visual": "candles"},

    {"key": "risk", "pill": "ZERO-RISK TRIAL", "headline": "Test the AI that finds",
     "highlight": "your next setup, free.",
     "sub": "No code, no commitment. See the strategies Atlas surfaces before you pay.",
     "cta": "Start free trial", "foot": f"{B['price']} after trial", "visual": "panel"},
]


def _logo():
    return (f'<div style="display:flex;align-items:center;gap:9px;font-weight:800;font-size:22px;'
            f'letter-spacing:-0.3px;color:#fff;">'
            f'<svg width="26" height="26" viewBox="0 0 22 22"><rect width="22" height="22" rx="6" fill="{B["yellow"]}"/>'
            f'<path d="M12 3 L6 12 H10 L9 19 L16 9 H11.5 Z" fill="{B["ink"]}"/></svg>{B["name"]}</div>')


def visual_block(kind, big, side_w):
    """Render the right-side product visual for the given kind."""
    if kind == "panel":
        return strategy_panel(big=big)
    if kind == "vs":
        return vs_panel(big=big)
    if kind == "curve":
        cw = side_w
        ch = int(cw * 0.62)
        stat = (f'<div style="display:flex;justify-content:space-between;align-items:flex-end;margin-bottom:10px;">'
                f'<div><div style="font-size:12px;color:{B["grey"]};letter-spacing:.5px;">BACKTESTED EQUITY</div>'
                f'<div style="font-size:{30 if big else 26}px;font-weight:900;color:{B["green"]};font-family:{MONO};">+214%</div></div>'
                f'<div style="text-align:right;"><div style="font-size:12px;color:{B["grey"]};">WIN RATE</div>'
                f'<div style="font-size:{20 if big else 18}px;font-weight:800;color:#fff;font-family:{MONO};">68.4%</div></div></div>')
        return (f'<div style="background:{B["card"]};border:1px solid {B["border"]};border-radius:16px;padding:{"22px" if big else "18px"};'
                f'box-shadow:0 20px 60px rgba(0,0,0,0.5);">{stat}{equity_curve(cw-44, ch)}</div>')
    if kind == "candles":
        cw = side_w
        return (f'<div style="background:{B["card"]};border:1px solid {B["border"]};border-radius:16px;padding:{"22px" if big else "18px"};'
                f'box-shadow:0 20px 60px rgba(0,0,0,0.5);">'
                f'<div style="font-size:12px;color:{B["grey"]};letter-spacing:.5px;margin-bottom:12px;">LIVE SIGNAL · BTC/USDT</div>'
                f'{candles(cw-44, int(cw*0.5))}</div>')
    return ""


def render(cr, w, h):
    big = h >= 1000
    hsize = 56 if big else 40
    subsize = 20 if big else 17
    pad = "56px 60px" if big else "44px 50px"

    # square = stacked (text top, visual below); landscape = side-by-side
    if big:
        side_w = w - 120
        visual = visual_block(cr["visual"], big, side_w)
        layout = f"""
        <div style="margin-top:30px;">{visual}</div>"""
        text_max = w - 120
    else:
        side_w = int(w * 0.46)
        visual = visual_block(cr["visual"], big, side_w)
        layout = ""  # visual placed in the right column below

    sub_html = (f'<div style="color:{B["grey"]};font-size:{subsize}px;margin-top:14px;max-width:'
                f'{560 if big else 470}px;line-height:1.45;">{cr["sub"]}</div>') if cr["sub"] else ""

    header = (f'<div style="display:flex;justify-content:space-between;align-items:center;">{_logo()}'
              f'<span style="color:{B["grey"]};font-size:13px;font-weight:600;letter-spacing:2px;text-transform:uppercase;">{B["tag"]}</span></div>')
    pill = (f'<span style="display:inline-block;background:rgba(201,22,91,.16);color:{B["magenta"]};'
            f'border:1px solid {B["magenta"]};font-size:13px;font-weight:700;padding:5px 12px;border-radius:999px;letter-spacing:.5px;">{cr["pill"]}</span>')
    head = (f'<div style="font-size:{hsize}px;font-weight:900;line-height:1.03;margin-top:16px;letter-spacing:-1px;color:#fff;">'
            f'{cr["headline"]}<br><span style="color:{B["yellow"]};">{cr["highlight"]}</span></div>')
    cta = (f'<div style="display:flex;align-items:center;gap:14px;">'
           f'<span style="display:inline-block;background:{B["yellow"]};color:{B["ink"]};font-weight:800;'
           f'font-size:{19 if big else 16}px;padding:{15 if big else 13}px {30 if big else 24}px;border-radius:10px;">{cr["cta"]} &rarr;</span>'
           f'<span style="color:{B["grey"]};font-size:{15 if big else 13}px;">{cr["foot"]}</span></div>')

    glows = (f'<div style="position:absolute;width:{int(w*0.4)}px;height:{int(w*0.4)}px;border-radius:50%;filter:blur(90px);opacity:.4;background:{B["magenta"]};top:-140px;right:-60px;"></div>'
             f'<div style="position:absolute;width:{int(w*0.3)}px;height:{int(w*0.3)}px;border-radius:50%;filter:blur(90px);opacity:.18;background:{B["yellow"]};bottom:-140px;left:-80px;"></div>')

    if big:
        inner = f"""
        {header}
        <div style="margin-top:30px;">{pill}{head}{sub_html}</div>
        {layout}
        <div style="margin-top:auto;">{cta}</div>"""
    else:
        inner = f"""
        {header}
        <div style="display:flex;gap:36px;align-items:center;margin-top:30px;flex:1;">
          <div style="flex:1.05;min-width:0;">{pill}{head}{sub_html}</div>
          <div style="flex:1;min-width:0;">{visual}</div>
        </div>
        {cta}"""

    return f"""<!doctype html><html><head><meta charset="utf-8">{FONT}
<style>*{{box-sizing:border-box;margin:0}}body{{font-family:'Inter',sans-serif;-webkit-print-color-adjust:exact}}</style></head>
<body><div style="width:{w}px;height:{h}px;background:{B['bg']};overflow:hidden;position:relative;">
{glows}
<div style="position:relative;padding:{pad};height:100%;display:flex;flex-direction:column;">{inner}</div>
</div></body></html>"""


async def main():
    keys = sys.argv[1:]
    crs = [c for c in CREATIVES if not keys or c["key"] in keys]
    if not crs:
        print("No matching keys. Available:", ", ".join(c["key"] for c in CREATIVES)); return
    async with async_playwright() as p:
        br = await p.chromium.launch()
        for cr in crs:
            for w, h in SIZES:
                pg = await br.new_page(viewport={"width": w, "height": h}, device_scale_factor=2)
                await pg.set_content(render(cr, w, h), wait_until="networkidle")
                await pg.wait_for_timeout(700)
                name = f"{cr['key']}_{w}x{h}.png"
                await pg.screenshot(path=str(OUT / name), clip={"x": 0, "y": 0, "width": w, "height": h})
                await pg.close()
                print("wrote", name)
        await br.close()
    print(f"\n{len(crs)} angles x {len(SIZES)} sizes = {len(crs)*len(SIZES)} creatives\ndir: {OUT}")


if __name__ == "__main__":
    asyncio.run(main())
