"""Render the Team Minik pilot proposal to a polished, branded one-page PDF via
the Playwright/Chromium already installed for scraping."""
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "notes" / "Aureon-TeamMinik-Pilot-Proposal.pdf"
OUT.parent.mkdir(exist_ok=True)

HTML = """<!doctype html><html><head><meta charset="utf-8"><style>
@page { size: Letter; margin: 0.55in 0.6in; }
* { box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif; color:#1e293b;
       font-size: 11.2px; line-height: 1.5; margin:0; }
.brand { display:flex; align-items:baseline; justify-content:space-between;
         border-bottom: 2px solid #0f172a; padding-bottom: 8px; }
.brand .name { font-size: 17px; font-weight: 800; letter-spacing: 2px; color:#0f172a; }
.brand .tag { font-size: 10px; color:#64748b; }
h1 { font-size: 18px; color:#0f172a; margin: 16px 0 2px; }
.sub { color:#64748b; font-size: 10.5px; margin-bottom: 14px; }
h2 { font-size: 11.5px; text-transform: uppercase; letter-spacing: 1px; color:#2563eb;
     margin: 14px 0 5px; }
p { margin: 5px 0; }
ul { margin: 4px 0; padding-left: 18px; }
li { margin: 3px 0; }
.box { background:#f8fafc; border:1px solid #e2e8f0; border-left:3px solid #2563eb;
       border-radius:6px; padding:10px 14px; margin:8px 0; }
.k { color:#0f172a; font-weight:600; }
.muted { color:#64748b; font-style: italic; font-size:10.3px; }
.steps { counter-reset: s; list-style:none; padding-left:0; }
.steps li { counter-increment:s; padding-left:24px; position:relative; margin:5px 0; }
.steps li::before { content: counter(s); position:absolute; left:0; top:0;
  width:17px; height:17px; background:#0f172a; color:#fff; border-radius:50%;
  font-size:10px; text-align:center; line-height:17px; font-weight:700; }
.foot { border-top:1px solid #e2e8f0; margin-top:18px; padding-top:8px;
        color:#64748b; font-size:10px; display:flex; justify-content:space-between; }
.pill { display:inline-block; background:#dbeafe; color:#1e40af; font-weight:600;
        font-size:9.5px; padding:1px 8px; border-radius:10px; }
</style></head><body>

<div class="brand">
  <span class="name">AUREON&nbsp;GLOBAL</span>
  <span class="tag">Done-for-you seller &amp; listing outbound for real estate teams</span>
</div>

<h1>Seller Outbound Pilot &mdash; for Team Minik</h1>
<div class="sub">Prepared for Michelle Minik &nbsp;·&nbsp; 30-day pilot &nbsp;·&nbsp; <span class="pill">White-labeled under Team Minik</span></div>

<h2>The opportunity</h2>
<p>Your team has buyer flow handled. The harder, higher-value side is <span class="k">listings</span> &mdash;
the one thing portals and most lead vendors do not deliver. Aureon runs done-for-you seller
outbound that books <span class="k">listing appointments</span>, and we run it under the Team
Minik brand, so it strengthens what you already give your agents.</p>

<h2>What the pilot is</h2>
<p>We run seller / listing outbound for <span class="k">3 to 5 of your agents</span>, in
<span class="k">one market</span>, for <span class="k">30 days</span>, fully managed by us:</p>
<div class="box">
<ul>
  <li><span class="k">White-labeled</span> &mdash; every touch goes out under Team Minik / the agent's name.</li>
  <li><span class="k">Zero lift for your agents</span> &mdash; we do the outreach; they just take the appointments.</li>
  <li><span class="k">They keep everything</span> &mdash; 100% of every commission and every lead we source is yours.</li>
  <li><span class="k">Exclusive</span> &mdash; appointments are never shared and never resold.</li>
  <li>Live appointment alerts + a simple weekly numbers report, so you see it working.</li>
</ul>
</div>

<h2>What you are looking for at day 30</h2>
<p>A clear answer to one question: <span class="k">did it put real listing appointments in front
of your agents?</span> If yes, we scale it across your network. If not, you walk away having
risked almost nothing.</p>

<h2>Investment</h2>
<p><span class="k">Performance-based</span> &mdash; you pay only for booked, qualified listing
appointments. No long-term contract, cancel anytime. Exact terms confirmed on our call so we
size it to the market and your agents.</p>
<p class="muted">The system and sourcing are our IP &mdash; the pilot shows you everything that matters: the listings.</p>

<h2>Next steps</h2>
<ol class="steps">
  <li>You pick <span class="k">3&ndash;5 agents</span> + the <span class="k">market</span>.</li>
  <li>We set up in 3&ndash;5 business days and start the 30-day clock.</li>
  <li>Weekly check-in; decision to scale at day 30.</li>
</ol>
<p>To start: reply with the agents + market and a start date, and I will send the short
onboarding (one quick form per agent).</p>

<div class="foot">
  <span>Aureon Global &nbsp;·&nbsp; aureonglobal.de</span>
  <span>info@aureonglobal.de</span>
</div>
</body></html>"""

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page()
    page.set_content(HTML, wait_until="networkidle")
    page.pdf(path=str(OUT), format="Letter", print_background=True,
             margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
    b.close()
print("wrote", OUT, f"({OUT.stat().st_size} bytes)")
