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

    logo_svg = ('<svg width="40" height="40" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">'
                '<defs><linearGradient id="g" x1="10%" y1="10%" x2="90%" y2="90%">'
                '<stop offset="5%" stop-color="#FFF8D6"/><stop offset="35%" stop-color="#E6C259"/>'
                '<stop offset="65%" stop-color="#B68E2D"/><stop offset="95%" stop-color="#755615"/>'
                '</linearGradient></defs><g fill="url(#g)">'
                '<ellipse cx="50" cy="15" rx="20" ry="7"/>'
                '<path d="M 18 26 Q 50 33 82 26 L 82 34 Q 50 41 18 34 Z"/>'
                '<path d="M 8 40 Q 50 47 92 40 L 92 49 Q 50 56 8 49 Z"/>'
                '<path d="M 8 55 Q 50 62 92 55 L 92 64 Q 50 71 8 64 Z"/>'
                '<path d="M 18 70 Q 50 77 82 70 L 82 78 Q 50 85 18 78 Z"/>'
                '<path d="M 32 84 Q 50 89 68 84 L 68 89 Q 50 94 32 89 Z"/></g></svg>')
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700;800&family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
 :root{{--ink:#050505;--gold:#d4af37;--gold-d:#b68e2d;--muted:#6b7280;--line:#e7e5e0;--bg:#faf9f6;--cream:#fbf8ef}}
 *{{box-sizing:border-box;margin:0;padding:0}}
 body{{font-family:'Inter',-apple-system,Segoe UI,sans-serif;color:#1a1a1a;line-height:1.55;background:#fff}}
 .page{{padding:0 0 76px;position:relative;min-height:100vh}}
 .masthead{{background:var(--ink);padding:30px 52px 26px;border-bottom:3px solid var(--gold);color:#fff}}
 .mh-top{{display:flex;justify-content:space-between;align-items:center}}
 .logo-lockup{{display:flex;align-items:center;gap:13px}}
 .logo-lockup .wm{{font-family:'Playfair Display',serif;font-size:21px;font-weight:800;color:#fff;letter-spacing:.01em;line-height:1}}
 .logo-lockup .tl{{font-size:9.5px;letter-spacing:.34em;text-transform:uppercase;color:var(--gold);margin-top:4px;font-weight:600}}
 .mh-meta{{text-align:right;font-size:11px;color:#9ca3af;letter-spacing:.02em}}
 .mh-meta b{{color:var(--gold);font-weight:600}}
 .doctitle{{margin-top:24px}}
 .doctitle .kick{{font-size:11px;letter-spacing:.28em;text-transform:uppercase;color:var(--gold);font-weight:700}}
 .doctitle h1{{font-family:'Playfair Display',serif;font-size:33px;font-weight:800;color:#fff;letter-spacing:-.01em;margin-top:7px;line-height:1.05}}
 .doctitle .addr{{font-size:15px;color:#cbd5e1;margin-top:7px}}
 .body{{padding:30px 52px 0}}
 .greet{{font-size:14.5px;color:#3f3f46}}
 .valbox{{margin:24px 0;background:var(--cream);border:1px solid #efe7cf;border-radius:14px;padding:28px 30px;position:relative}}
 .valbox::before{{content:"";position:absolute;left:0;top:18px;bottom:18px;width:4px;background:linear-gradient(180deg,var(--gold),var(--gold-d));border-radius:0 3px 3px 0}}
 .vlabel{{font-size:11px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:var(--gold-d)}}
 .conf{{display:inline-block;color:#fff;font-size:10px;font-weight:700;letter-spacing:.04em;padding:2px 9px;border-radius:999px;margin-left:8px;vertical-align:middle;text-transform:none}}
 .vrange{{font-family:'Playfair Display',serif;font-size:42px;font-weight:800;color:var(--ink);letter-spacing:-.02em;margin-top:8px;line-height:1}}
 .vrange span{{color:var(--gold-d);font-weight:600}}
 .vmid{{font-size:14px;color:#52525b;margin-top:7px}}
 .vmethod{{margin-top:16px;font-size:12.5px;color:#52525b}}
 .vmethod span{{font-weight:700;color:#3f3f46;display:block;margin-bottom:5px}}
 .vmethod ul{{margin:0;padding-left:18px}} .vmethod li{{margin-bottom:3px}}
 .vassessed{{font-size:12.5px;color:var(--muted);margin-top:14px;padding-top:13px;border-top:1px solid #efe7cf}}
 h2{{font-family:'Playfair Display',serif;font-size:19px;font-weight:700;color:var(--ink);margin:32px 0 13px;padding-bottom:8px;border-bottom:2px solid var(--gold)}}
 table.facts{{width:100%;border-collapse:collapse}}
 table.facts td{{padding:9px 2px;border-bottom:1px solid var(--line);font-size:14px;vertical-align:top}}
 td.fl{{color:var(--muted);width:46%}} td.fv{{color:var(--ink);font-weight:600;text-align:right}}
 .market p{{font-size:14px;color:#3f3f46;margin-bottom:10px}}
 .ppsf{{display:inline-block;background:var(--cream);border:1px solid #efe7cf;border-radius:8px;padding:8px 14px;font-size:13px;color:#52525b;margin-top:4px}}
 .cta{{margin:32px 0 0;background:var(--ink);border:1px solid #1f1f1f;border-radius:16px;padding:30px 32px;position:relative;overflow:hidden}}
 .cta::after{{content:"";position:absolute;right:-40px;top:-40px;width:160px;height:160px;border-radius:50%;background:radial-gradient(circle,rgba(212,175,55,.22),transparent 70%)}}
 .cta .kick{{font-size:10.5px;letter-spacing:.24em;text-transform:uppercase;color:var(--gold);font-weight:700}}
 .cta h3{{font-family:'Playfair Display',serif;font-size:23px;font-weight:800;margin:7px 0 9px;color:#fff}}
 .cta p{{font-size:14px;color:#cbd5e1;margin-bottom:18px;max-width:56ch}}
 .ctabtn{{display:inline-block;background:linear-gradient(135deg,var(--gold),var(--gold-d));color:#1a1a1a;font-weight:800;font-size:15px;padding:13px 24px;border-radius:10px;text-decoration:none}}
 .agentcard{{margin-top:20px;padding-top:16px;border-top:1px solid #262626;font-size:13px;color:#cbd5e1}}
 .agentcard b{{color:#fff;font-size:15px}}
 .callout{{margin-top:22px;background:#fbf8ef;border:1px solid #efe7cf;border-left:4px solid var(--gold);border-radius:10px;padding:15px 18px;font-size:12px;color:#6b5d2e;line-height:1.6}}
 .footer{{position:fixed;bottom:0;left:0;right:0;padding:11px 52px;border-top:2px solid var(--gold);background:var(--ink);font-size:9px;color:#9ca3af;line-height:1.45}}
 .footer b{{color:var(--gold);font-weight:600;letter-spacing:.02em}}
 @media print{{.footer{{position:fixed}} .page{{min-height:auto}}}}
</style></head>
<body>
 <div class="page">
   <div class="masthead">
     <div class="mh-top">
       <div class="logo-lockup">{logo_svg}<div><div class="wm">Aureon Global</div><div class="tl">Quality Converts</div></div></div>
       <div class="mh-meta">Prepared {today}<br>for <b>{owner_first}</b><br>on behalf of {agent_name}</div>
     </div>
     <div class="doctitle">
       <div class="kick">Confidential Home Value Report</div>
       <h1>What your home is worth today</h1>
       <div class="addr">{addr}</div>
     </div>
   </div>

   <div class="body">

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
     <div class="kick">Your next step</div>
     <h3>Get your exact number, in person.</h3>
     <p>Book a free, no-obligation in-person valuation with {agent_name}. You get a precise current
        market price and a simple plan to maximise it before you list &mdash; no pressure, no cost.</p>
     {('<a class="ctabtn" href="' + cal + '">Book your free valuation &rarr;</a>') if cal else '<a class="ctabtn" href="mailto:' + agent_email + '">Reply to book your free valuation &rarr;</a>'}
     <div class="agentcard">
       <b>{agent_name}</b>{(' &middot; ' + agent_company) if agent_company else ''}{(' &middot; ' + agent_phone) if agent_phone else ''}{(' &middot; ' + agent_email) if agent_email else ''}
     </div>
   </div>
   </div>
 </div>
 <div class="footer">
   <b>Aureon Global &middot; Quality Converts</b> &nbsp;|&nbsp; Prepared by Aureon Global on behalf of {agent_name}.
   Automated estimate from public county assessor records and recent local sales; the property was not visited
   or inspected and the information has not been independently verified. Not an appraisal, an offer, or a
   guarantee of value. For informational use only.
 </div>
</body></html>"""
