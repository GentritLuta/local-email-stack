# -*- coding: utf-8 -*-
"""Compose ONE gallery page: the 4 personalized fulfilment emails (real, rendered)
+ the new Bloomington verified list, for visual inspection."""
import csv, html, sys
from pathlib import Path
REPO = Path(r"C:\Users\bernh\local-email-stack")
OUT = REPO/"out"
if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8",errors="replace")

# the 4 ZIP-repliers (exclude Jake — suppressed)
agents = [
    ("Austin — My Next Home Elite", "Indianapolis (ZIP 47383)", "_personal_austin_at_mynexthomeelite_com.html"),
    ("Taylor Van Hoy — Keller Williams", "Bloomington (ZIP 47448) NEW", "_personal_taylorvanhoy_at_kw_com.html"),
    ("Rachel Firestone — Talk to Tucker", "Indianapolis (ZIP 46033) — site focus: luxury homes", "_personal_rachel.firestone_at_talktotucker_com.html"),
    ("Courtney — The Stewart Home Group", "Indianapolis (ZIP 46121) — site focus: ranch & land", "_personal_courtney_at_thestewarthomegroup_com.html"),
]
cards = []
for name, meta, fn in agents:
    f = OUT/fn
    body = f.read_text(encoding="utf-8") if f.exists() else "<i>(not rendered)</i>"
    cards.append(f'''<div style="margin:0 0 34px"><div style="font:700 15px Inter,sans-serif;color:#0a0a0a">{html.escape(name)}</div>
<div style="font:12px Inter,sans-serif;color:#FF6B00;margin:2px 0 10px">{html.escape(meta)}</div>
<div style="border:1px solid #e5e7eb;border-radius:12px;overflow:hidden">{body}</div></div>''')

# Bloomington list as a table
rows = list(csv.reader((REPO/"referral-lists"/"Attorney-Referral-List-Bloomington.csv").open(encoding="utf-8-sig")))
head, data = rows[0], rows[1:]
th = "".join(f'<th style="text-align:left;padding:6px 10px;font:600 11px Inter;color:#94a3b8;border-bottom:2px solid #0f172a;white-space:nowrap">{html.escape(h)}</th>' for h in head)
trs = []
for r in data:
    tds = "".join(f'<td style="padding:6px 10px;font:12px Inter;color:#0f172a;border-bottom:1px solid #eef2f7">{html.escape(c)}</td>' for c in r)
    trs.append(f"<tr>{tds}</tr>")
table = f'<table style="border-collapse:collapse;width:100%"><thead><tr>{th}</tr></thead><tbody>{"".join(trs)}</tbody></table>'

page = f'''<!doctype html><meta charset="utf-8"><body style="margin:0;background:#f5f5f5;padding:30px">
<div style="max-width:680px;margin:0 auto">
<h1 style="font:800 22px Inter,sans-serif;color:#0a0a0a">Personalized referral-list emails — 4 agents who replied</h1>
<p style="font:13px Inter,sans-serif;color:#475569">Each email is tailored from REAL data only: their brokerage (when it's a clean name), their city, and the market their own website emphasizes. No fabrication. Below the emails: the brand-new, QC-passed Bloomington list (17 firms) that Taylor now receives.</p>
{"".join(cards)}
<h2 style="font:800 18px Inter,sans-serif;color:#0a0a0a;margin-top:40px">Bloomington & South-Central Indiana — {len(data)} verified firms</h2>
<p style="font:12px Inter,sans-serif;color:#475569">100% verified: live law-firm site + named lead attorney + direct 812 phone. This is what Taylor Van Hoy (47448) receives.</p>
<div style="background:#fff;border:1px solid #e5e7eb;border-radius:12px;padding:8px;overflow-x:auto">{table}</div>
</div></body>'''
p = OUT/"_diraya_aureon_presentation.html"
p.write_text(page, encoding="utf-8")
print("wrote", p, len(page), "bytes;", len(data), "Bloomington firms")
