# -*- coding: utf-8 -*-
"""home_value_report.py — render a rich, branded Home Value Report as print-ready HTML
(-> PDF via headless Chrome) for the consented home-value funnel.

PURPOSE (why this exists): it is the bait in a consented seller-lead funnel. A homeowner
trades their contact details for this report; the agent gets a high-intent seller lead and
the report makes the agent look credible enough to earn the follow-up in-person CMA (-> a
listing -> commission). So it is built to CONVERT: detailed, professional, agent-branded,
with a clear next-step CTA. Every number is public county-assessor data or an openly-labelled
estimate derived from it — never a fabricated appraisal — and a disclaimer (property not
visited, statements not verified) sits in the footer of every page.

build_report_html(lookup, agent, owner) -> str  (full HTML; feed to Chrome --print-to-pdf)
"""
from __future__ import annotations
import datetime as dt
import html as _html
import re


def _num(av_str: str):
    """'$262,500' -> 262500 (int) or None."""
    if not av_str:
        return None
    m = re.search(r"[\d,]+", av_str)
    if not m:
        return None
    try:
        return int(m.group(0).replace(",", ""))
    except Exception:
        return None


def _money(n) -> str:
    try:
        return "$%s" % format(int(n), ",")
    except Exception:
        return "—"


def _ctx_pairs(context: str) -> list[tuple[str, str]]:
    """Turn the '|'-joined context string into (label, value) rows for the facts table."""
    pairs = []
    for part in (context or "").split("|"):
        part = part.strip()
        if not part:
            continue
        # patterns like 'built 1998', '2,140 sqft', 'last sale $182,000', 'sold 2003', 'acreage 0.19', 'use class X'
        m = re.match(r"^(built|sold)\s+(.+)$", part, re.I)
        if m:
            pairs.append(("Year built" if m.group(1).lower() == "built" else "Last sold", m.group(2)))
            continue
        m = re.match(r"^(.+?)\s+(sqft)$", part, re.I)
        if m:
            pairs.append(("Living area", m.group(1) + " sq ft")); continue
        m = re.match(r"^last sale\s+(.+)$", part, re.I)
        if m:
            pairs.append(("Last sale price", m.group(1))); continue
        m = re.match(r"^acreage\s+(.+)$", part, re.I)
        if m:
            pairs.append(("Lot size", m.group(1) + " acres")); continue
        m = re.match(r"^use class\s+(.+)$", part, re.I)
        if m:
            pairs.append(("Property type", m.group(1))); continue
        m = re.match(r"^(land value|improvement|homestead)\s+(.+)$", part, re.I)
        if m:
            lbl = {"land value": "Land value", "improvement": "Structure value",
                   "homestead": "Homestead"}[m.group(1).lower()]
            pairs.append((lbl, m.group(2))); continue
        pairs.append((part, ""))
    return pairs


def build_report_html(lookup: dict, agent: dict, owner: dict) -> str:
    esc = _html.escape
    today = dt.datetime.now().strftime("%B %d, %Y")
    addr = esc(lookup.get("address") or owner.get("address") or "your property")
    agent_name = esc(agent.get("name") or "Your agent")
    agent_company = esc(agent.get("company") or "")
    agent_email = esc(agent.get("email") or "")
    agent_phone = esc(agent.get("phone") or "")
    owner_first = esc((owner.get("first_name") or "there").strip() or "there")
    cal = esc(agent.get("cal") or "")

    av = _num(lookup.get("assessed_value", ""))
    comps = lookup.get("comps") or {}
    lo = lookup.get("market_low"); mid = lookup.get("market_mid"); hi = lookup.get("market_high")
    conf = (lookup.get("estimate_confidence") or "").capitalize()
    methods = lookup.get("estimate_method") or []
    found = bool(lookup.get("found")) and bool(mid)

    if found:
        conf_color = {"Higher": "#15803d", "Moderate": "#b45309", "Low": "#9ca3af"}.get(conf, "#64748b")
        method_html = "".join(f"<li>{esc(mline)}</li>" for mline in methods)
        val_block = f"""
      <div class="valbox">
        <div class="vlabel">Estimated market value range
          <span class="conf" style="background:{conf_color}">{esc(conf) or 'Estimate'} confidence</span></div>
        <div class="vrange">{_money(lo)} <span>&ndash;</span> {_money(hi)}</div>
        <div class="vmid">Midpoint estimate {_money(mid)}</div>
        <div class="vmethod"><span>How we calculated this</span><ul>{method_html}</ul></div>
        <div class="vassessed">County assessed value on record: <strong>{_money(av)}</strong></div>
      </div>"""
    else:
        val_block = f"""
      <div class="valbox">
        <div class="vlabel">Your personalised valuation is being prepared</div>
        <div class="vmid" style="margin-top:8px;">We are pulling the current comparable sales for
          {addr} and {agent_name} will follow up with your full market range shortly.</div>
      </div>"""

    # Market / comps section — the real-transaction evidence behind the estimate.
    if comps.get("n", 0) >= 5:
        market_block = f"""
   <h2>Your local market &mdash; the evidence</h2>
   <div class="market">
     <p>This estimate is built from <strong>{comps['n']} recent arms-length sales</strong> in
        {esc(owner.get('zip') or 'your area')}, not a generic formula.</p>
     <table class="facts">
       <tr><td class="fl">Median sale price per sq ft</td><td class="fv">{_money(comps.get('median_ppsf'))}</td></tr>
       <tr><td class="fl">Typical range (25th&ndash;75th percentile)</td><td class="fv">{_money(comps.get('ppsf_lo'))} &ndash; {_money(comps.get('ppsf_hi'))} / sq ft</td></tr>
       <tr><td class="fl">Sales analysed</td><td class="fv">{comps['n']} recent transactions</td></tr>
     </table>
     <p style="margin-top:12px;">The figure that ultimately matters is set by condition, finishes and how the
        home shows in person &mdash; which is exactly what {esc(agent_name)} confirms with a free in-person valuation.</p>
   </div>"""
    else:
        market_block = f"""
   <h2>Your local market</h2>
   <div class="market">
     <p>Recent comparable-sale detail is limited in the public record for {esc(owner.get('zip') or 'your area')},
        so the range above leans on the county assessment. {esc(agent_name)} can pull live MLS comparables and
        give you a precise current figure in a free in-person valuation.</p>
   </div>"""

    facts = _ctx_pairs(lookup.get("context", ""))
    facts_rows = "".join(
        f"<tr><td class='fl'>{esc(l)}</td><td class='fv'>{esc(v) or '&mdash;'}</td></tr>"
        for l, v in facts) or "<tr><td class='fl'>Property record</td><td class='fv'>On file with the county assessor</td></tr>"

    ppsf = ""
    if found:
        sqft = next((re.sub(r"[^\d]", "", v) for l, v in facts if l == "Living area"), "")
        if sqft.isdigit() and int(sqft) > 100:
            ppsf = _money(int(av / int(sqft))) + " / sq ft (assessed)"

    disclaimer = ("This report was prepared by Aureon Global on behalf of %s. It is an automated estimate "
                  "built from public county assessor records and recent local sales data. The property was "
                  "not visited or inspected, and the information has not been independently verified. It is "
                  "not an appraisal, an offer, or a guarantee of value, and should not be relied upon as one. "
                  "For an accurate current market value, request a full in-person comparative market analysis "
                  "(CMA) from %s." % (agent_name, agent_name))

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
 :root{{--ink:#0f172a;--accent:#0a0a0a;--gold:#b8860b;--muted:#64748b;--line:#e2e8f0;--bg:#f8fafc}}
 *{{box-sizing:border-box;margin:0;padding:0}}
 body{{font-family:'Inter',-apple-system,Segoe UI,sans-serif;color:#1e293b;line-height:1.5;background:#fff}}
 .page{{padding:46px 52px 70px;position:relative;min-height:100vh}}
 .top{{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:2px solid var(--ink);padding-bottom:16px}}
 .brand{{font-size:13px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:var(--ink)}}
 .brand .co{{display:block;font-size:11px;font-weight:500;color:var(--muted);letter-spacing:.04em;text-transform:none;margin-top:3px}}
 .date{{font-size:12px;color:var(--muted);text-align:right}}
 h1{{font-size:30px;font-weight:800;letter-spacing:-.02em;margin:30px 0 4px;color:var(--ink)}}
 .addr{{font-size:16px;color:var(--muted);font-weight:500}}
 .greet{{margin:22px 0 0;font-size:15px}}
 .valbox{{margin:24px 0;background:var(--bg);border:1px solid var(--line);border-left:4px solid var(--ink);border-radius:10px;padding:26px 28px}}
 .vlabel{{font-size:12px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}}
 .conf{{display:inline-block;color:#fff;font-size:10px;font-weight:700;letter-spacing:.05em;padding:2px 8px;border-radius:999px;margin-left:8px;vertical-align:middle;text-transform:none}}
 .vrange{{font-size:38px;font-weight:800;color:var(--ink);letter-spacing:-.02em;margin-top:6px}}
 .vrange span{{color:var(--muted);font-weight:500}}
 .vmid{{font-size:14px;color:#334155;margin-top:4px}}
 .vmethod{{margin-top:14px;font-size:12.5px;color:#475569}}
 .vmethod span{{font-weight:700;color:#334155;display:block;margin-bottom:4px}}
 .vmethod ul{{margin:0;padding-left:18px}} .vmethod li{{margin-bottom:3px}}
 .vassessed{{font-size:13px;color:var(--muted);margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}}
 h2{{font-size:15px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--ink);margin:34px 0 12px;padding-bottom:6px;border-bottom:1px solid var(--line)}}
 table.facts{{width:100%;border-collapse:collapse}}
 table.facts td{{padding:9px 0;border-bottom:1px solid var(--line);font-size:14px;vertical-align:top}}
 td.fl{{color:var(--muted);width:46%}} td.fv{{color:var(--ink);font-weight:600}}
 .market p{{font-size:14px;color:#334155;margin-bottom:10px}}
 .ppsf{{display:inline-block;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 14px;font-size:13px;color:#334155;margin-top:4px}}
 .cta{{margin-top:30px;background:var(--ink);color:#fff;border-radius:12px;padding:28px 30px}}
 .cta h3{{font-size:20px;font-weight:800;margin-bottom:8px}}
 .cta p{{font-size:14px;color:#cbd5e1;margin-bottom:16px;max-width:54ch}}
 .ctabtn{{display:inline-block;background:#fff;color:var(--ink);font-weight:700;font-size:15px;padding:12px 22px;border-radius:9px;text-decoration:none}}
 .agentcard{{margin-top:18px;display:flex;gap:14px;align-items:center;font-size:13px;color:#cbd5e1}}
 .agentcard b{{color:#fff;display:block;font-size:15px}}
 .callout{{margin-top:20px;background:#fffbeb;border:1px solid #fde68a;border-radius:9px;padding:14px 16px;font-size:12.5px;color:#78350f;line-height:1.55}}
 .footer{{position:fixed;bottom:0;left:0;right:0;padding:10px 52px;border-top:1px solid var(--line);font-size:9.5px;color:#94a3b8;line-height:1.4;background:#fff}}
 @media print{{.footer{{position:fixed}} .page{{min-height:auto}}}}
</style></head>
<body>
 <div class="page">
   <div class="top">
     <div class="brand">{agent_company or agent_name}<span class="co">Home Value Report</span></div>
     <div class="date">Prepared {today}<br>for {owner_first}</div>
   </div>

   <h1>Home Value Report</h1>
   <div class="addr">{addr}</div>

   <p class="greet">Hi {owner_first}, thank you for requesting your home value report. This report was prepared
      for you by Aureon Global on behalf of {agent_name}, using current public records and recent local sales.</p>

   {val_block}

   <h2>Property facts</h2>
   <table class="facts">{facts_rows}</table>
   {('<div class="ppsf">' + ppsf + '</div>') if ppsf else ''}

   {market_block}

   <div class="callout">
     <strong>How this estimate was made.</strong> {esc(disclaimer)}
   </div>

   <div class="cta">
     <h3>Want your exact number?</h3>
     <p>Book a free, no-obligation in-person valuation (CMA) with {agent_name}. You get a precise current
        market price and a simple plan to maximise it &mdash; no pressure to list.</p>
     {('<a class="ctabtn" href="' + cal + '">Book your free valuation &rarr;</a>') if cal else '<a class="ctabtn" href="mailto:' + agent_email + '">Reply to book your free valuation &rarr;</a>'}
     <div class="agentcard">
       <div><b>{agent_name}</b>{agent_company}{(' &middot; ' + agent_phone) if agent_phone else ''}{(' &middot; ' + agent_email) if agent_email else ''}</div>
     </div>
   </div>
 </div>
 <div class="footer">
   Prepared by Aureon Global on behalf of {agent_name}. Automated estimate from public county assessor records
   and recent local sales; the property was not visited or inspected and the information has not been
   independently verified. Not an appraisal, an offer, or a guarantee of value. For informational use only.
 </div>
</body></html>"""
