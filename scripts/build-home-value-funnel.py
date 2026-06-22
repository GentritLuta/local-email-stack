# -*- coding: utf-8 -*-
"""build-home-value-funnel.py, generate a branded "Free Home Value Report"
seller-capture page for one real-estate agent, hosted on GitHub Pages alongside
the other static pages in docs/.

This is the FREE, consented seller-lead engine for the done-for-you appointment
magnet (see docs/SELLER_OUTREACH_PLAN.md). Instead of buying/scraping cold seller
data, we MAKE sellers raise their hand: the page offers a free home-value report
for their address; homeowners opt in with address + name + contact. Each opt-in
is written straight to Supabase `prospects` (browser -> REST, anon key, same
pattern as the unsubscribe pages) tagged source='home_value_funnel' and
custom_fields.for_agent=<agent email>, so the seller-outreach engine can run the
report + outreach on that agent's behalf and book the listing appointment.

100% consented (the homeowner submits their own info), $0 data cost, real
hand-raisers. Lower volume than a bought list, far higher intent.

The page is given to the agent as the deliverable: their branded seller funnel,
run for them. We seed traffic to it (the agent shares it / we run it).

USAGE:
    py scripts/build-home-value-funnel.py --agent-slug atpropertiesind \
        --agent-name "Andrew" --agent-company "@properties Indianapolis" \
        --agent-email andrew@atpropertiesind.com --zip 46220
    # writes docs/home-value/atpropertiesind.html
"""
from __future__ import annotations

import argparse
import html
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "docs" / "home-value"
PAGES_BASE = "https://gentritluta.github.io/local-email-stack/home-value"

SUPABASE_URL = "https://ccmqkljsjiuavpydbkva.supabase.co"
SUPABASE_ANON = ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6"
                 "ImNjbXFrbGpzaml1YXZweWRia3ZhIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzkwMTYzNjUs"
                 "ImV4cCI6MjA5NDU5MjM2NX0.cCUuVEYMlShJkM4FlaCwYYYEn_-pQeuZAZgCRob0ONc")


def page_html(*, agent_name: str, agent_company: str, agent_email: str,
              zip_code: str, accent: str = "#d4af37", profile_slug: str = "aureon") -> str:
    esc = html.escape
    company = esc(agent_company)
    name = esc(agent_name)
    z = esc(zip_code)
    # custom_fields is sent as a JSON object; PostgREST accepts it for a jsonb column.
    # Carry the agent's display name + company so the fulfiller (fulfill-home-value.py) can
    # brand the homeowner's report properly instead of guessing from the email domain.
    cf = json.dumps({"for_agent": agent_email, "funnel": "home_value", "zip": zip_code,
                     "agent_name": agent_name, "agent_company": agent_company})
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Free Home Value Report, Aureon Global</title>
<style>
 :root{{--accent:{accent}}}
 *{{box-sizing:border-box}} body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;
   background:#0a0a0a;color:#f5f5f5;line-height:1.5}}
 .wrap{{max-width:560px;margin:0 auto;padding:48px 22px}}
 .card{{background:#141414;border:1px solid #262626;border-radius:16px;padding:30px}}
 h1{{font-size:26px;margin:0 0 8px}} .sub{{color:#a3a3a3;margin:0 0 24px}}
 label{{display:block;font-size:13px;color:#d4d4d4;margin:14px 0 6px}}
 input,select{{width:100%;padding:12px 13px;border-radius:9px;border:1px solid #333;background:#1c1c1c;
   color:#fff;font-size:15px}}
 select{{appearance:none;cursor:pointer}}
 .sec{{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--accent);font-weight:700;
   margin:22px 0 2px;padding-bottom:6px;border-bottom:1px solid #262626}}
 .sec:first-of-type{{margin-top:6px}}
 .more-note{{font-size:12px;color:#737373;margin:12px 0 2px}}
 .row2{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}
 .row3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}}
 .row2 label,.row3 label{{margin-top:14px}}
 button{{width:100%;margin-top:22px;padding:14px;border:0;border-radius:9px;background:var(--accent);
   color:#0a0a0a;font-weight:700;font-size:16px;cursor:pointer}}
 button:disabled{{opacity:.5;cursor:default}}
 .foot{{color:#737373;font-size:12px;margin-top:18px;text-align:center}}
 .ok{{display:none;text-align:center;padding:20px 0}} .ok h2{{color:var(--accent)}}
 .err{{display:none;color:#f87171;font-size:13px;margin-top:10px}}
 .brandbar{{display:flex;align-items:center;gap:11px;margin-bottom:22px}}
 .brandbar .wm{{font-weight:800;font-size:16px;color:#fff;line-height:1}}
 .brandbar .tl{{font-size:9px;letter-spacing:.28em;text-transform:uppercase;color:var(--accent);margin-top:3px;font-weight:600}}
 .stack{{list-style:none;padding:0;margin:20px 0 8px}}
 .stack li{{display:flex;gap:11px;align-items:flex-start;padding:9px 0;font-size:14.5px;color:#e5e5e5;border-bottom:1px solid #1e1e1e}}
 .stack li:last-child{{border-bottom:0}}
 .stack .ck{{flex:0 0 20px;height:20px;border-radius:50%;background:var(--accent);color:#0a0a0a;font-weight:800;
   font-size:12px;display:flex;align-items:center;justify-content:center;margin-top:1px}}
 .stack b{{color:#fff}}
 .worth{{background:#1c1c1c;border:1px solid #2a2a2a;border-radius:11px;padding:14px 16px;margin:18px 0;
   font-size:13px;color:#cfcfcf}} .worth b{{color:var(--accent)}}
 .badges{{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px}}
 .badge{{font-size:11px;color:#a3a3a3;background:#1a1a1a;border:1px solid #262626;border-radius:999px;padding:5px 11px}}
 .formtitle{{font-size:15px;font-weight:700;color:#fff;margin:26px 0 2px}}
</style></head>
<body><div class="wrap"><div class="card">
 <div class="brandbar">
   <svg width="34" height="34" viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg"><defs><linearGradient id="g" x1="10%" y1="10%" x2="90%" y2="90%"><stop offset="5%" stop-color="#FFF8D6"/><stop offset="35%" stop-color="#E6C259"/><stop offset="65%" stop-color="#B68E2D"/><stop offset="95%" stop-color="#755615"/></linearGradient></defs><g fill="url(#g)"><ellipse cx="50" cy="15" rx="20" ry="7"/><path d="M 18 26 Q 50 33 82 26 L 82 34 Q 50 41 18 34 Z"/><path d="M 8 40 Q 50 47 92 40 L 92 49 Q 50 56 8 49 Z"/><path d="M 8 55 Q 50 62 92 55 L 92 64 Q 50 71 8 64 Z"/><path d="M 18 70 Q 50 77 82 70 L 82 78 Q 50 85 18 78 Z"/><path d="M 32 84 Q 50 89 68 84 L 68 89 Q 50 94 32 89 Z"/></g></svg>
   <div><div class="wm">Aureon Global</div><div class="tl">Quality Converts</div></div>
 </div>
 <h1>What is your home really worth?</h1>
 <p class="sub">Most homeowners are sitting on more equity than they think. Get the real number
    for your home{(' in ' + z) if z else ''} in minutes. Free, and you are not committing to anything.</p>
 <ul class="stack">
   <li><span class="ck">&check;</span><div>Your <b>estimated market value range</b>, built from real recent sales near you</div></li>
   <li><span class="ck">&check;</span><div><b>What you could walk away with</b> after selling costs</div></li>
   <li><span class="ck">&check;</span><div><b>Recent comparable sales</b> on your street</div></li>
   <li><span class="ck">&check;</span><div>The <b>3 moves that add the most</b> before you list</div></li>
   <li><span class="ck">&check;</span><div>A <b>free professional CMA</b> (the analysis agents normally charge $400 to $600 for)</div></li>
 </ul>
 <div class="worth">Then book a quick call and a <b>local real estate expert reaches out as soon as possible</b>
   to confirm your exact number in person. No pressure. No obligation to ever list.</div>
 <div class="badges"><span class="badge">100% free</span><span class="badge">No obligation</span><span class="badge">Your data is never sold</span><span class="badge">Takes 60 seconds</span></div>
 <div class="formtitle">Get my free report</div>
 <form id="f">
   <div class="sec">Your property</div>
   <label>Property address *</label>
   <input id="addr" required placeholder="123 Main St, City, State ZIP">
   <div class="row2">
     <div><label>Unit / Apt (if any)</label><input id="unit" placeholder="Unit 4B"></div>
     <div><label>ZIP code *</label><input id="zip" required placeholder="{z}" value="{z}"></div>
   </div>
   <div class="more-note">The more you tell us about the home, the more precise your report. (All optional below.)</div>
   <div class="row3">
     <div><label>Beds</label><input id="beds" type="number" min="0" placeholder="3"></div>
     <div><label>Baths</label><input id="baths" type="number" min="0" step="0.5" placeholder="2"></div>
     <div><label>Approx. sq ft</label><input id="sqft" type="number" min="0" placeholder="1,800"></div>
   </div>
   <div class="row2">
     <div><label>Year built</label><input id="year" type="number" min="1800" max="2030" placeholder="1998"></div>
     <div><label>Property type</label>
       <select id="ptype"><option value="">Select…</option>
         <option>Single-family</option><option>Condo / Townhome</option><option>Multi-family</option>
         <option>Mobile / Manufactured</option><option>Land / Lot</option><option>Other</option></select></div>
   </div>
   <label>Recent updates or anything that affects value</label>
   <input id="updates" placeholder="New roof 2023, renovated kitchen, large lot…">
   <label>Condition</label>
   <select id="cond"><option value="">Select…</option>
     <option>Excellent / recently updated</option><option>Good</option>
     <option>Average</option><option>Needs work / as-is</option></select>
   <label>How soon are you thinking of selling?</label>
   <select id="timeframe"><option value="">Select…</option>
     <option>ASAP / actively looking</option><option>Within 3 months</option>
     <option>3, 6 months</option><option>6, 12 months</option>
     <option>Just curious about the value</option></select>

   <div class="sec">Where to send it</div>
   <label>Your name *</label>
   <input id="name" required placeholder="First and last name">
   <label>Email *</label>
   <input id="email" type="email" required placeholder="you@email.com">
   <label>Phone (for a faster, more accurate report)</label>
   <input id="phone" placeholder="(555) 555-5555">

   <div class="sec">Talk to a local expert (optional)</div>
   <p class="more-note">Want your exact number confirmed on a quick call? Pick a time and a local real
      estate expert will reach out to set it up. No pressure, no obligation to ever list.</p>
   <div class="row2">
     <div><label>Best day for a call</label><input id="bk_date" type="date"></div>
     <div><label>Best time</label>
       <select id="bk_win"><option value="">Select&hellip;</option>
         <option>Morning (8&ndash;12)</option><option>Afternoon (12&ndash;5)</option>
         <option>Evening (5&ndash;8)</option></select></div>
   </div>
   <button id="btn" type="submit">Show me what my home is worth &rarr;</button>
   <div class="err" id="err"></div>
 </form>
 <div class="ok" id="ok">
   <div id="book_confirm" style="display:none"><h2>You are set.</h2>
     <p>Your free home value report is on its way to your inbox. A local real estate expert will reach out
        to confirm your call for <b id="booked_when"></b> and walk you through your exact number. No pressure,
        no obligation to ever list.</p></div>
   <div id="book_default"><h2>Got it.</h2>
     <p>Your free home value report is on its way to your inbox. For your exact figure, book a quick call ,
        a local real estate expert will then reach out as soon as possible to confirm it.</p>
     <p style="margin-top:14px;"><a href="https://calendly.com/aureonglobal-info/30min" style="background:var(--accent);color:#0a0a0a;font-weight:700;padding:12px 20px;border-radius:9px;text-decoration:none;display:inline-block;">Book your free CMA call</a></p></div></div>
 <p class="foot">Prepared by Aureon Global. Your information is used only to prepare your report and is never sold.</p>
</div></div>
<script>
const SUPABASE_URL="{SUPABASE_URL}";
const SUPABASE_ANON="{SUPABASE_ANON}";
const CF={cf};
const f=document.getElementById('f'),btn=document.getElementById('btn'),err=document.getElementById('err');
f.addEventListener('submit',async(e)=>{{
  e.preventDefault(); btn.disabled=true; err.style.display='none';
  const val=id=>{{const e=document.getElementById(id);return e?e.value.trim():"";}};
  const addr=val('addr');
  const name=val('name');
  const email=val('email');
  const phone=val('phone');
  const zip=val('zip');
  const parts=name.split(/\\s+/);
  const bkDate=val('bk_date'), bkWin=val('bk_win');
  // Every detail the homeowner gives, captured to pin the property down + grade the lead.
  const details={{
    unit:val('unit'), zip:zip, beds:val('beds'), baths:val('baths'), sqft:val('sqft'),
    year_built:val('year'), property_type:val('ptype'), updates:val('updates'),
    condition:val('cond'), sell_timeframe:val('timeframe')
  }};
  // Self-hosted booking: a motivated homeowner picks a time -> captured here, surfaced to
  // the agent by fulfill-home-value as a HOT appointment request. Needs nothing from the agent.
  if(bkDate||bkWin){{ details.requested_call={{date:bkDate,window:bkWin,requested_at:new Date().toISOString()}}; }}
  const row={{
    profile_slug:"{profile_slug}", source:"home_value_funnel",
    email:email, first_name:parts[0]||"", last_name:parts.slice(1).join(' ')||"",
    company:addr, phone:phone, verified:true,
    custom_fields:Object.assign({{}},CF,{{address:addr,zip:zip||CF.zip,details:details,submitted_at:new Date().toISOString()}})
  }};
  try{{
    const r=await fetch(SUPABASE_URL+"/rest/v1/prospects",{{
      method:"POST",
      headers:{{apikey:SUPABASE_ANON,Authorization:"Bearer "+SUPABASE_ANON,
        "Content-Type":"application/json",Prefer:"return=minimal"}},
      body:JSON.stringify(row)
    }});
    if(!r.ok && r.status!==201 && r.status!==204) throw new Error("HTTP "+r.status);
    f.style.display='none';
    if(bkDate||bkWin){{
      document.getElementById('booked_when').textContent=[bkWin,bkDate?("on "+bkDate):""].filter(Boolean).join(' ');
      document.getElementById('book_default').style.display='none';
      document.getElementById('book_confirm').style.display='block';
    }}
    document.getElementById('ok').style.display='block';
  }}catch(ex){{ err.textContent="Something went wrong. Please try again."; err.style.display='block'; btn.disabled=false; }}
}});
</script></body></html>"""


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent-slug", required=True)
    ap.add_argument("--agent-name", required=True)
    ap.add_argument("--agent-company", required=True)
    ap.add_argument("--agent-email", required=True)
    ap.add_argument("--zip", default="")
    ap.add_argument("--profile", default="aureon", help="profile_slug the opt-ins are tagged with (aureon | lk-advertising)")
    a = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = slugify(a.agent_slug)
    out = OUT_DIR / f"{slug}.html"
    out.write_text(page_html(agent_name=a.agent_name, agent_company=a.agent_company,
                             agent_email=a.agent_email, zip_code=a.zip, profile_slug=a.profile),
                   encoding="utf-8")
    url = f"{PAGES_BASE}/{slug}.html"
    print(f"-> wrote {out}")
    print(f"-> hosted at (after git push to Pages): {url}")
    print(f"   Opt-ins land in prospects (source=home_value_funnel, "
          f"custom_fields.for_agent={a.agent_email}).")
    print(f"   Give this link to {a.agent_name} as their branded seller-capture funnel.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
