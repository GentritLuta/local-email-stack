"""Render the Team Minik AGENT-RECRUITMENT outreach proposal to a polished
one-page PDF (the lead partnership angle) via Playwright/Chromium."""
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "notes" / "Aureon-TeamMinik-Recruitment-Proposal.pdf"
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
.foot { border-top:1px solid #e2e8f0; margin-top:16px; padding-top:8px;
        color:#64748b; font-size:10px; display:flex; justify-content:space-between; }
.pill { display:inline-block; background:#dcfce7; color:#166534; font-weight:600;
        font-size:9.5px; padding:1px 8px; border-radius:10px; }
.also { font-size:10.3px; color:#475569; }
</style></head><body>

<div class="brand">
  <span class="name">AUREON&nbsp;GLOBAL</span>
  <span class="tag">Done-for-you outreach engines for real estate teams</span>
</div>

<h1>Agent Recruitment Outreach &mdash; for Team Minik</h1>
<div class="sub">Prepared for Michelle Minik &nbsp;·&nbsp; 30-day pilot &nbsp;·&nbsp; <span class="pill">Booked recruiting calls, done for you</span></div>

<h2>The opportunity</h2>
<p>Team Minik grows by <span class="k">recruiting agents</span> &mdash; that is the engine
behind the splits, the revenue share, and the team. The bottleneck is always the same: a
steady flow of the right agents to talk to. <span class="k">That is exactly what we reach at
scale.</span> Our outreach already lands in front of real-estate agents every day &mdash; the
same people you recruit.</p>

<h2>What the pilot is</h2>
<p>For <span class="k">30 days</span>, in <span class="k">one market</span>, we run
done-for-you outreach to licensed agents carrying <span class="k">your</span> recruiting offer
&mdash; your credibility, your splits, your leads and coaching &mdash; and we
<span class="k">book qualified recruiting calls straight onto your team's calendar.</span></p>
<div class="box">
<ul>
  <li><span class="k">White-labeled</span> &mdash; it goes out as Team Minik / Michelle, not a vendor.</li>
  <li><span class="k">You stay the closer</span> &mdash; we do top-of-funnel; you run the recruiting calls.</li>
  <li><span class="k">Qualified only</span> &mdash; agents who raise their hand for better splits, leads, coaching.</li>
  <li><span class="k">Zero lift</span> &mdash; no work for your team beyond taking the calls.</li>
  <li>Live booking alerts + a simple weekly numbers report.</li>
</ul>
</div>

<h2>What you are looking for at day 30</h2>
<p>One answer: <span class="k">did it put qualified agents on your recruiting calendar?</span>
If yes, we scale across your markets. If not, you walk away having risked almost nothing.</p>

<h2>Investment</h2>
<p><span class="k">Performance-based</span> &mdash; you pay per booked, qualified recruiting
call (or per agent who joins). No long-term contract, cancel anytime. Exact terms set on our
call so we size it to your markets.</p>
<p class="muted">The system and sourcing are our IP &mdash; the pilot shows you everything that matters: the agents on your calendar.</p>

<h2>Next steps</h2>
<ol class="steps">
  <li>You share the <span class="k">recruiting offer</span> + pick the <span class="k">market</span>.</li>
  <li>We set up in 3&ndash;5 business days and start the 30-day clock.</li>
  <li>Weekly check-in; decision to scale at day 30.</li>
</ol>
<p class="also">Second lane, when you are ready: we can also run <span class="k">seller / listing
outbound</span> for the agents you already have, and <span class="k">referral-partner
outreach</span> (lenders, attorneys, builders) to feed the team deals.</p>

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
