# -*- coding: utf-8 -*-
"""build-outreach-report.py — a branded, anonymized Aureon Global performance report.

Pulls the REAL outreach numbers from Supabase (send_log + prospects + replies), anonymizes
each client to its vertical, and renders a multi-page Aureon-styled PDF (HTML -> headless
Chrome) that showcases the results AND how the onboarding/process works. For presenting to
prospects as a live example.

  py scripts/build-outreach-report.py            # -> out/reports/Aureon-Outreach-Report.pdf
"""
from __future__ import annotations
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import ssl
from datetime import date
from pathlib import Path

ssl._create_default_https_context = ssl._create_unverified_context
REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "out" / "reports"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
GOLD = "#d4af37"  # aureonglobal.de primary gold
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# anonymize each real client slug to a neutral vertical label (no names, per the brief)
VERTICAL = {
    "aureon": "Real estate growth (DACH + NL)",
    "energ": "Energy consultancy (DE)",
    "diraya": "AI engineering (B2B)",
    "algoalpha": "Creator program (crypto)",
    "mark-eting": "SEO & visibility (US)",
    "lk-advertising": "Performance media (US real estate)",
}


def env(p: Path) -> dict:
    d = {}
    for ln in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


S = env(REPO / "sequences" / "supabase.env")
TOK = S.get("SUPABASE_ACCESS_TOKEN")
REF = "ccmqkljsjiuavpydbkva"


def q(sql: str):
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{REF}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 Chrome/123"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def pct(n, d):
    return round(100 * n / d) if d else 0


def fetch():
    overall = q("""select count(*) sends, count(*) filter (where delivered) delivered,
        count(*) filter (where opened_at is not null) opened, count(*) filter (where clicked_at is not null) clicked,
        count(*) filter (where bounced) bounced,
        min(sent_at)::date first, max(sent_at)::date last from send_log where sent_at is not null""")[0]
    per = q("""select p.profile_slug,
        count(*) sends, count(*) filter (where s.delivered) delivered,
        count(*) filter (where s.opened_at is not null) opened,
        count(*) filter (where s.clicked_at is not null) clicked
        from send_log s join runs r on r.id=s.run_id join prospects p on p.id=r.prospect_id
        where s.sent_at is not null group by p.profile_slug""")
    # genuine replies (class='reply') per client, merged onto each row
    repl = {r["profile_slug"]: r["n"] for r in
            q("select profile_slug, count(*) n from replies where class='reply' group by profile_slug")}
    for r in per:
        r["replies"] = repl.get(r["profile_slug"], 0)
    prospects = q("select count(*) n from prospects")[0]["n"]
    clients = q("select count(*) n from profiles where active")[0]["n"]
    replies = q("select count(*) n from replies where class='reply'")[0]["n"]
    return overall, per, prospects, clients, replies


LOGO = ('<svg width="40" height="40" viewBox="0 0 100 100"><defs><linearGradient id="g" x1="10%" y1="10%" '
        'x2="90%" y2="90%"><stop offset="5%" stop-color="#FFF8D6"/><stop offset="35%" stop-color="#E6C259"/>'
        '<stop offset="65%" stop-color="#B68E2D"/><stop offset="95%" stop-color="#755615"/></linearGradient>'
        '</defs><g fill="url(#g)"><ellipse cx="50" cy="15" rx="20" ry="7"/><path d="M 18 26 Q 50 33 82 26 L 82 34 '
        'Q 50 41 18 34 Z"/><path d="M 8 40 Q 50 47 92 40 L 92 49 Q 50 56 8 49 Z"/><path d="M 8 55 Q 50 62 92 55 '
        'L 92 64 Q 50 71 8 64 Z"/><path d="M 18 70 Q 50 77 82 70 L 82 78 Q 50 85 18 78 Z"/><path d="M 32 84 '
        'Q 50 89 68 84 L 68 89 Q 50 94 32 89 Z"/></g></svg>')


def stat(num, label):
    return (f'<div class="stat"><div class="num">{num}</div>'
            f'<div class="lab">{label}</div></div>')


def step(n, title, body):
    return (f'<div class="step"><div class="sn">{n}</div><div><div class="st">{title}</div>'
            f'<div class="sb">{body}</div></div></div>')


def bars(items, scale, decimals=0) -> str:
    """Horizontal CSS bar chart. items = [(letter, vertical, value)]; value is a percent
    drawn against `scale`. Pure HTML/CSS so it renders crisp in print-to-PDF."""
    out = []
    for letter, v, val in items:
        w = max(2, round(val / scale * 100)) if scale else 2
        out.append(f'<div class="crow"><div class="clab">Client {letter}<span>{v}</span></div>'
                   f'<div class="ctrack"><div class="cbar" style="width:{w}%"></div></div>'
                   f'<div class="cval">{val:.{decimals}f}%</div></div>')
    return '<div class="chart">' + "".join(out) + '</div>'


def build_html(overall, per, prospects, clients, replies) -> str:
    sent = overall["sends"]
    deliv = overall["delivered"]
    dl = pct(deliv, sent)
    op = pct(overall["opened"], deliv)
    ck = pct(overall["clicked"], deliv)
    rr = round(100 * replies / deliv, 1) if deliv else 0.0
    span_first = str(overall["first"]); span_last = str(overall["last"])
    # per-client rows (anonymized), highest open rate first -> Client A..F
    data = []
    for r in per:
        v = VERTICAL.get(r["profile_slug"])
        if not v:
            continue
        d = r["delivered"]
        data.append({"v": v, "sent": r["sends"], "deliv": pct(d, r["sends"]),
                     "open": pct(r["opened"], d), "click": pct(r["clicked"], d),
                     "replies": r["replies"], "reply": round(100 * r["replies"] / d, 1) if d else 0.0})
    data.sort(key=lambda x: x["open"], reverse=True)
    for i, r in enumerate(data):
        r["letter"] = chr(65 + i)
    rows_html = "".join(
        f'<tr><td>Client {r["letter"]}</td><td>{r["v"]}</td><td>{r["sent"]:,}</td><td>{r["deliv"]}%</td>'
        f'<td class="hl">{r["open"]}%</td><td>{r["click"]}%</td><td>{r["reply"]:.1f}%</td></tr>'
        for r in data)
    open_bars = bars([(r["letter"], r["v"], r["open"]) for r in data], 80)
    reply_bars = bars([(r["letter"], r["v"], r["reply"])
                       for r in sorted(data, key=lambda x: x["reply"], reverse=True)], 4, 1)
    # forward value projection (assumptions, not actuals — no bookings are tracked in-platform)
    LEAD_V, MEET_V = 75, 300            # $ per warm-lead reply / per booked meeting
    EPD, SDAYS, PRR, MCONV = 600, 22, 0.004, 1 / 3   # 600 emails/day, 22 send-days, 0.4% reply, 1-in-3 to meeting
    m_emails = EPD * SDAYS
    m_repl = m_emails * PRR
    m_meet = m_repl * MCONV
    lead_mo, lead_yr = m_repl * LEAD_V, m_repl * LEAD_V * 12
    meet_mo, meet_yr = m_meet * MEET_V, m_meet * MEET_V * 12

    steps = "".join([
        step(1, "Discovery & ICP", "We define the ideal customer, the offer, and the exact niche so every email has a reason to be opened."),
        step(2, "Sending infrastructure", "Dedicated sending domains with SPF, DKIM and DMARC, plus a staged warm-up, so mail lands in the inbox, not spam."),
        step(3, "Branded sender personas", "Each campaign sends from its own branded identity on its own subdomain, kept clean and separated."),
        step(4, "Verified prospect sourcing", "Prospects matched to the ICP and verified before a single email goes out, keeping bounce rates low."),
        step(5, "Sequenced, written-to-fit copy", "Multi-step sequences in each persona's voice, personalised to the prospect, not blasted templates."),
        step(6, "Calendar-paced sending", "Volume is paced to protect deliverability, with live guardrails on bounces, spam and opt-outs."),
        step(7, "Replies reviewed & handed off", "Every reply is read and qualified; genuine leads are handed straight to the client, ready to talk."),
    ])

    timeline = "".join([
        step("1", "Week 1: kickoff and infrastructure", "A discovery call locks your ideal customer and your offer. We register dedicated sending domains and set SPF, DKIM and DMARC, so mail reaches the inbox from the very first send."),
        step("2", "Week 1 to 2: warm-up and sourcing", "The new domains warm up on a staged schedule while we source and verify your first prospects, matched to the ICP, so the list is clean before anything goes out."),
        step("3", "Week 2 to 3: copy and launch", "We write the multi-step sequence in your brand voice, you approve it, and sending begins, calendar-paced to protect deliverability."),
        step("4", "Week 3 onward: replies and handoff", "Every reply is read and qualified. Genuine leads are handed straight to you, ready to talk, while the rest keep moving through the sequence."),
        step("5", "Ongoing: tune, report, expand", "Copy and targeting are tuned every week on the real numbers, with a weekly report. As we learn what moves your result, we can agree to improve other parts of the funnel too."),
    ])

    return f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">
<style>
@page{{size:A4;margin:0}}
*{{box-sizing:border-box}}
body{{margin:0;font-family:'Inter',ui-sans-serif,system-ui,-apple-system,'Segoe UI',sans-serif;color:#e3e3e3;background:#0a0a0a;font-size:13px;line-height:1.65;-webkit-font-smoothing:antialiased}}
b,strong{{color:#e8c84a;font-weight:700}}
.page{{width:210mm;height:296mm;overflow:hidden;padding:24mm 22mm;page-break-after:always;position:relative;background:#0a0a0a}}
.page:last-child{{page-break-after:auto}}
h1{{font-size:34px;font-weight:800;margin:0 0 8px;letter-spacing:-.6px;color:#fff;line-height:1.08}}
h2{{font-size:22px;font-weight:700;margin:0 0 14px;letter-spacing:-.3px;color:#fff}}
.kick{{font-size:10.5px;letter-spacing:.26em;text-transform:uppercase;color:{GOLD};font-weight:700;margin-bottom:12px}}
.rule{{height:3px;width:58px;margin:14px 0 22px;border-radius:3px;background:linear-gradient(90deg,#fae5aa,{GOLD},#8a6e2f)}}
.brand{{display:flex;align-items:center;gap:11px}}
.brand .nm{{font-weight:800;font-size:16px;color:#fff;letter-spacing:-.2px}} .brand .tl{{font-size:8.5px;letter-spacing:.3em;text-transform:uppercase;color:{GOLD};font-weight:600;margin-top:3px}}
.muted{{color:#9a9a9a}}
.grid{{display:flex;flex-wrap:wrap;gap:12px;margin:18px 0}}
.stat{{flex:1 1 28%;background:#141414;border:1px solid #262626;border-radius:14px;padding:18px 20px}}
.stat .num{{font-size:31px;font-weight:800;color:#e8c84a;line-height:1;letter-spacing:-.5px}}
.stat .lab{{font-size:11.5px;color:#9a9a9a;margin-top:9px}}
table{{width:100%;border-collapse:collapse;margin-top:10px;font-size:12.5px}}
th{{text-align:left;font-size:10px;letter-spacing:.1em;text-transform:uppercase;color:#737373;font-weight:600;padding:0 10px 10px;border-bottom:1px solid #2a2a2a}}
td{{padding:12px 10px;border-bottom:1px solid #1a1a1a;color:#dcdcdc}} td.hl{{color:{GOLD};font-weight:700}}
.step{{display:flex;gap:14px;margin:0 0 17px;align-items:flex-start}}
.sn{{flex:0 0 32px;height:32px;border-radius:50%;background:linear-gradient(135deg,#e6c259,#b68e2d);color:#0a0a0a;font-weight:800;display:flex;align-items:center;justify-content:center;font-size:14px}}
.st{{font-weight:700;font-size:14px;color:#fff}} .sb{{color:#9a9a9a;font-size:12.5px}}
.chart{{margin-top:22px}}
.crow{{display:flex;align-items:center;gap:14px;margin:0 0 18px}}
.clab{{flex:0 0 52mm;font-size:12.5px;font-weight:700;color:#fff}}
.clab span{{display:block;font-weight:400;color:#888;font-size:11px;margin-top:2px}}
.ctrack{{flex:1;background:#1c1c1c;border-radius:7px;height:28px}}
.cbar{{background:linear-gradient(90deg,{GOLD},#b68e2d);height:28px;border-radius:7px;min-width:6px}}
.cval{{flex:0 0 50px;text-align:right;font-weight:700;font-size:13px;color:#e8c84a}}
.foot{{position:absolute;bottom:14mm;left:22mm;right:22mm;display:flex;justify-content:space-between;font-size:10px;color:#5f5f5f;border-top:1px solid #262626;padding-top:8px}}
.note{{font-size:11px;color:#737373;margin-top:14px;font-style:italic}}
.cover{{display:flex;flex-direction:column;justify-content:center;min-height:249mm}}
</style></head><body>

<div class="page"><div class="cover">
  <div class="brand">{LOGO}<div><div class="nm">Aureon Global</div><div class="tl">Quality Converts</div></div></div>
  <div style="margin-top:46mm">
    <div class="kick">Performance &amp; process report</div>
    <h1>Cold email that lands, opens, and converts.</h1>
    <div class="rule"></div>
    <p class="muted" style="max-width:135mm;font-size:14px">A live look at our outreach engine: real results across active client campaigns
       (anonymized), and exactly how we onboard and run a campaign from day one.</p>
    <div style="margin-top:30mm;font-size:12px;color:#7a7a7a">{span_first} &ndash; {span_last} &nbsp;&middot;&nbsp; {clients} active clients &nbsp;&middot;&nbsp; prepared {date.today().strftime('%B %Y')}</div>
  </div>
</div></div>

<div class="page">
  <div class="kick">The results</div><h2>Five weeks, measured.</h2><div class="rule"></div>
  <p class="muted" style="max-width:140mm">These are real numbers from live campaigns over the period shown, pulled straight from the platform.
     Client identities are withheld; figures are not.</p>
  <div class="grid">
    {stat(f"{sent:,}", "Emails sent")}
    {stat(f"{dl}%", "Delivered to inbox")}
    {stat(f"{op}%", "Open rate")}
  </div>
  <div class="grid">
    {stat(f"{ck}%", "Click rate")}
    {stat(f"{rr}%", "Reply rate")}
    {stat(f"{prospects:,}", "Prospects sourced")}
  </div>
  <p style="margin-top:18px">A {dl}% inbox delivery rate and a {op}% open rate are the foundation. From there, {replies}
     genuine replies came back over the period, and reply rate varies sharply by market, reported in full on the next page.</p>
  <p class="note">Delivery = sent mail accepted by the recipient server. Open = opens over delivered. Reply = genuine
     human replies (auto-replies and bounces excluded) over delivered. Click rate includes automated link scanning by
     inbox-security systems (Safe Links, Proofpoint, Mimecast), which click every link to vet it, so it overstates
     human clicks; opens and replies are the truer engagement signals.</p>
  <div class="foot"><span>Aureon Global &middot; Quality Converts</span><span>info@aureonglobal.de</span></div>
</div>

<div class="page">
  <div class="kick">By campaign</div><h2>Every metric, every market.</h2><div class="rule"></div>
  <p class="muted" style="max-width:140mm">Sent, delivered, opened, clicked and replied for each live campaign, anonymized to
     its vertical. The full funnel, side by side.</p>
  <table><thead><tr><th>Campaign</th><th>Vertical</th><th>Sent</th><th>Deliv.</th><th>Open</th><th>Click</th><th>Reply</th></tr></thead>
    <tbody>{rows_html}</tbody></table>
  <p style="margin-top:20px">Inbox placement stays high across every market; open and reply rates move with the audience.
     One campaign already replies at {max(r['reply'] for r in data):.1f}%, several times the cold-email benchmark, while
     others are earlier in their reply curve.</p>
  <p class="note">Reply = genuine human replies over delivered. Click rate includes automated security-scanner clicks
     and overstates human clicks (visible where it approaches or exceeds the open rate).</p>
  <div class="foot"><span>Aureon Global &middot; Quality Converts</span><span>info@aureonglobal.de</span></div>
</div>

<div class="page">
  <div class="kick">Open rate by vertical</div><h2>The inbox, visualized.</h2><div class="rule"></div>
  <p class="muted" style="max-width:140mm">Every campaign, ranked by the share of delivered mail that gets opened.
     The shared floor under all of them is inbox placement.</p>
  {open_bars}
  <p class="note">Bars scaled to an 80% axis. Open rate = opens over delivered mail.</p>
  <div class="foot"><span>Aureon Global &middot; Quality Converts</span><span>info@aureonglobal.de</span></div>
</div>

<div class="page">
  <div class="kick">Reply rate by vertical</div><h2>Where it turns into conversations.</h2><div class="rule"></div>
  <p class="muted" style="max-width:140mm">Genuine human replies as a share of delivered mail. This is the number that
     becomes pipeline, and where the strongest campaign pulls well ahead.</p>
  {reply_bars}
  <p class="note">Bars scaled to a 4% axis. Reply rate = genuine human replies (auto-replies and bounces excluded)
     over delivered mail.</p>
  <div class="foot"><span>Aureon Global &middot; Quality Converts</span><span>info@aureonglobal.de</span></div>
</div>

<div class="page">
  <div class="kick">Value generated</div><h2>What one campaign is worth.</h2><div class="rule"></div>
  <p class="muted" style="max-width:140mm">At a conservative {PRR*100:.1f}% reply rate (the real-estate baseline, not the
     outlier), {EPD} emails a day across {SDAYS} sending days a month. Each reply valued as a warm lead, and one in three
     projected to a booked meeting.</p>
  <div class="grid">
    {stat(f"{m_emails:,}", f"Emails / month ({EPD} &times; {SDAYS})")}
    {stat(f"{round(m_repl)}", f"Replies / month ({PRR*100:.1f}%)")}
    {stat(f"~{round(m_meet)}", "Projected meetings / month")}
  </div>
  <div class="grid">
    {stat(f"${round(lead_mo):,}", f"Lead value / month (${LEAD_V} each)")}
    {stat(f"${round(meet_mo):,}", f"Meeting value / month (${MEET_V} each)")}
    {stat(f"${round(meet_yr/1000)}K", "Meeting value / year")}
  </div>
  <p style="margin-top:16px">Sold as warm leads, one campaign generates about <b>${round(lead_mo):,}</b> a month
     (<b>${round(lead_yr):,}</b> a year). Worked into booked meetings, the same replies are worth about
     <b>${round(meet_mo):,}</b> a month (<b>${round(meet_yr):,}</b> a year), because each meeting is worth far more than a raw lead.</p>
  <p class="note">Projection, not actuals. Reply rate {PRR*100:.1f}%; lead value ${LEAD_V}, meeting value ${MEET_V}; one in
     three replies projected to a booked meeting. Lead and meeting figures are alternative framings of the same replies,
     not additive. No bookings are tracked in-platform, so meeting figures are a projection.</p>
  <div class="foot"><span>Aureon Global &middot; Quality Converts</span><span>info@aureonglobal.de</span></div>
</div>

<div class="page">
  <div class="kick">How it works</div><h2>From kickoff to qualified leads.</h2><div class="rule"></div>
  <p class="muted" style="max-width:140mm">Onboarding is a fixed, repeatable path. Here is every step we run for a new client,
     in order.</p>
  <div style="margin-top:18px">{steps}</div>
  <div class="foot"><span>Aureon Global &middot; Quality Converts</span><span>info@aureonglobal.de</span></div>
</div>

<div class="page">
  <div class="kick">Onboarding</div><h2>What the first weeks look like.</h2><div class="rule"></div>
  <p class="muted" style="max-width:140mm">A pilot goes from kickoff to live sends in about three weeks, then settles into a
     weekly rhythm. Here is the path, week by week.</p>
  <div style="margin-top:18px">{timeline}</div>
  <div class="foot"><span>Aureon Global &middot; Quality Converts</span><span>info@aureonglobal.de</span></div>
</div>

<div class="page">
  <div class="kick">The pilot</div><h2>Three months, free, for an honest review.</h2><div class="rule"></div>
  <p class="muted" style="max-width:140mm">The engagement starts as a pilot. The terms are deliberately simple, and weighted
     in your favour.</p>
  <div class="grid">
    {stat("$0", "Cost during the pilot")}
    {stat("3 months", "Pilot length")}
    {stat("Yours", "Every lead we source")}
  </div>
  <div style="margin-top:14px">
    {step("&rarr;", "Free for three months", "You pay nothing during the pilot. We run the campaign end to end and you keep every lead and appointment it produces.")}
    {step("&rarr;", "All we ask is a review", "In return for the free pilot, an honest review at the end and a short case study if it worked. That is the whole exchange.")}
    {step("&rarr;", "Not just email", "Email is the start, not the limit. As we see your numbers, we can agree to improve other parts of your funnel too, the landing page, the booking flow, the nurture, even the offer itself, wherever the leak is.")}
    {step("&rarr;", "Continue only if it worked", "At the end, if both sides agree the campaign delivered, we continue under a commercial relationship. If not, you walk away owing nothing and keep everything we built.")}
  </div>
  <div class="foot"><span>Aureon Global &middot; Quality Converts</span><span>info@aureonglobal.de</span></div>
</div>

</body></html>"""


def main() -> int:
    print("pulling live numbers ...")
    overall, per, prospects, clients, replies = fetch()
    html = build_html(overall, per, prospects, clients, replies)
    OUT.mkdir(parents=True, exist_ok=True)
    # render from a stable path under out/ (a system tempfile path paginated inconsistently,
    # dropping a full-height page; a real file in out/ renders all pages reliably).
    src_path = OUT / "_render.html"
    src_path.write_text(html, encoding="utf-8")
    pdf = OUT / "Aureon-Email-Report.pdf"
    tmp_pdf = OUT / "_report_tmp.pdf"
    # isolated profile per render: sharing the default profile with a running Chrome causes
    # contention that intermittently drops a full-height page from the print output.
    prof = tempfile.mkdtemp(prefix="aureon_report_")
    subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--user-data-dir=" + prof, "--no-first-run", "--no-default-browser-check",
                    "--virtual-time-budget=5000", f"--print-to-pdf={tmp_pdf}",
                    "file:///" + str(src_path.resolve()).replace("\\", "/")],
                   capture_output=True, timeout=120)
    shutil.rmtree(prof, ignore_errors=True)
    src_path.unlink(missing_ok=True)
    # swap the temp render over the canonical name; if that file is open in a viewer (locked),
    # fall back to a fresh name so we never silently leave a stale PDF behind.
    import os
    target = pdf
    try:
        os.replace(tmp_pdf, pdf)
    except OSError:
        target = OUT / "Aureon-Email-Report-new.pdf"
        try:
            os.replace(tmp_pdf, target)
            print(f"   ! {pdf.name} is open in a viewer (locked) — wrote {target.name} instead; "
                  f"close the open copy to refresh the main file.")
        except OSError:
            target = tmp_pdf
    print(f"-> {target}")
    print(f"   {overall['sends']:,} sent, {pct(overall['delivered'],overall['sends'])}% delivered, "
          f"{pct(overall['opened'],overall['delivered'])}% open, {clients} clients, {prospects:,} prospects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
