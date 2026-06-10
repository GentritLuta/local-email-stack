# -*- coding: utf-8 -*-
"""build-home-value-funnel.py — generate a branded "Free Home Value Report"
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
              zip_code: str, accent: str = "#d4af37") -> str:
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
<title>Free Home Value Report — {company}</title>
<style>
 :root{{--accent:{accent}}}
 *{{box-sizing:border-box}} body{{margin:0;font-family:system-ui,-apple-system,Segoe UI,sans-serif;
   background:#0a0a0a;color:#f5f5f5;line-height:1.5}}
 .wrap{{max-width:560px;margin:0 auto;padding:48px 22px}}
 .card{{background:#141414;border:1px solid #262626;border-radius:16px;padding:30px}}
 h1{{font-size:26px;margin:0 0 8px}} .sub{{color:#a3a3a3;margin:0 0 24px}}
 label{{display:block;font-size:13px;color:#d4d4d4;margin:14px 0 6px}}
 input{{width:100%;padding:12px 13px;border-radius:9px;border:1px solid #333;background:#1c1c1c;
   color:#fff;font-size:15px}}
 button{{width:100%;margin-top:22px;padding:14px;border:0;border-radius:9px;background:var(--accent);
   color:#0a0a0a;font-weight:700;font-size:16px;cursor:pointer}}
 button:disabled{{opacity:.5;cursor:default}}
 .foot{{color:#737373;font-size:12px;margin-top:18px;text-align:center}}
 .ok{{display:none;text-align:center;padding:20px 0}} .ok h2{{color:var(--accent)}}
 .err{{display:none;color:#f87171;font-size:13px;margin-top:10px}}
 .tag{{color:var(--accent);font-weight:700;letter-spacing:.08em;font-size:12px;text-transform:uppercase}}
</style></head>
<body><div class="wrap"><div class="card">
 <div class="tag">{company}</div>
 <h1>What is your home worth today?</h1>
 <p class="sub">Get a free, no-obligation home value report for your property{(' in ' + z) if z else ''}.
    Prepared by {name}. No spam, no pushy calls — just the number and the local market read.</p>
 <form id="f">
   <label>Property address</label>
   <input id="addr" required placeholder="123 Main St, City, State ZIP">
   <label>Your name</label>
   <input id="name" required placeholder="First and last name">
   <label>Email</label>
   <input id="email" type="email" required placeholder="you@email.com">
   <label>Phone (optional, for a faster report)</label>
   <input id="phone" placeholder="(555) 555-5555">
   <button id="btn" type="submit">Get my free home value report</button>
   <div class="err" id="err"></div>
 </form>
 <div class="ok" id="ok"><h2>Got it.</h2>
   <p>Your free home value report is on its way. {name} will be in touch shortly.</p></div>
 <p class="foot">Your information is used only to prepare your report and is never sold.</p>
</div></div>
<script>
const SUPABASE_URL="{SUPABASE_URL}";
const SUPABASE_ANON="{SUPABASE_ANON}";
const CF={cf};
const f=document.getElementById('f'),btn=document.getElementById('btn'),err=document.getElementById('err');
f.addEventListener('submit',async(e)=>{{
  e.preventDefault(); btn.disabled=true; err.style.display='none';
  const addr=document.getElementById('addr').value.trim();
  const name=document.getElementById('name').value.trim();
  const email=document.getElementById('email').value.trim();
  const phone=document.getElementById('phone').value.trim();
  const parts=name.split(/\\s+/);
  const row={{
    profile_slug:"aureon", source:"home_value_funnel",
    email:email, first_name:parts[0]||"", last_name:parts.slice(1).join(' ')||"",
    company:addr, phone:phone, verified:true,
    custom_fields:Object.assign({{}},CF,{{address:addr,submitted_at:new Date().toISOString()}})
  }};
  try{{
    const r=await fetch(SUPABASE_URL+"/rest/v1/prospects",{{
      method:"POST",
      headers:{{apikey:SUPABASE_ANON,Authorization:"Bearer "+SUPABASE_ANON,
        "Content-Type":"application/json",Prefer:"return=minimal"}},
      body:JSON.stringify(row)
    }});
    if(!r.ok && r.status!==201 && r.status!==204) throw new Error("HTTP "+r.status);
    f.style.display='none'; document.getElementById('ok').style.display='block';
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
    a = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = slugify(a.agent_slug)
    out = OUT_DIR / f"{slug}.html"
    out.write_text(page_html(agent_name=a.agent_name, agent_company=a.agent_company,
                             agent_email=a.agent_email, zip_code=a.zip),
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
