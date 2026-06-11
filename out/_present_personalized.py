# -*- coding: utf-8 -*-
"""Render the PERSONALIZED fulfilment email for each agent who already replied with
a ZIP/LIST intent, so we can present them. Reuses the live fulfiller's functions."""
import importlib.util, json, urllib.parse, urllib.request, sys
from pathlib import Path
REPO = Path(r"C:\Users\bernh\local-email-stack")
spec = importlib.util.spec_from_file_location("fz", REPO/"scripts"/"fulfill-referral-requests.py")
fz = importlib.util.module_from_spec(spec); spec.loader.exec_module(fz)
if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8",errors="replace")

env = fz.load_env()
index = json.loads(fz.CURATED.read_text(encoding="utf-8"))
ids = json.loads((REPO/"referral-lists"/".fulfilled.json").read_text())

# capture the payload send_list would POST, instead of sending
captured = []
orig = fz.urllib.request.urlopen
def fake(req, *a, **k):
    try: captured.append(json.loads(req.data.decode()))
    except Exception: pass
    class R:  # minimal stub
        def read(self,*a): return b'{"id":"dry"}'
        def __enter__(self): return self
        def __exit__(self,*a): return False
    return R()

out_dir = REPO/"out"
print(f"{'AGENT':<34}{'METRO':<22}{'ZIP':<7}{'COMPANY':<26}FOCUS")
for rid in ids:
    rep = fz.supa_get(env, f"replies?id=eq.{rid}&select=from_addr,body_snippet&limit=1")
    if not rep: continue
    addr = (rep[0].get("from_addr") or "").lower()
    if not addr or fz.is_ours(addr): continue
    ps = fz.supa_get(env, f"prospects?email=eq.{urllib.parse.quote(addr)}"
                          f"&select=first_name,company,website,city,state,phone&limit=1")
    if not ps: 
        print(f"{addr:<34}(not a prospect)"); continue
    p = ps[0]
    ac = fz.area_code(p.get("phone"))
    zc = fz.zip_in_reply(rep[0].get("body_snippet"))
    entry = fz.resolve(index, p.get("city"), p.get("state"), ac, zc)
    if not entry:
        print(f"{addr:<34}{'(uncovered)':<22}{zc or '-':<7}{(p.get('company') or '-')[:25]:<26}"); continue
    site = fz.fetch_site(fz.site_url_for(p, addr))
    focus = fz.site_focus(site)
    note = fz.personal_note(p, site)
    # render the exact email via send_list (capture, don't send)
    fz.urllib.request.urlopen = fake
    fz.send_list(env, addr, p, entry, zc, site, dry=False)
    fz.urllib.request.urlopen = orig
    if captured:
        pay = captured[-1]
        safe = addr.replace("@","_at_").replace(".","_")
        (out_dir/f"_personal_{safe}.html").write_text(pay["html"], encoding="utf-8")
    print(f"{addr:<34}{entry['metro']:<22}{zc or '-':<7}{(p.get('company') or '-')[:25]:<26}{focus or '-'}")
    print(f"    note: {note or '(generic open)'}")
