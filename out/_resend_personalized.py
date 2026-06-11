# -*- coding: utf-8 -*-
"""Re-send the PERSONALIZED list to the 4 agents who replied (Taylor now gets the
corrected Bloomington list). Reuses the live fulfiller. --send to actually send."""
import importlib.util, json, sys, urllib.parse
from pathlib import Path
REPO = Path(r"C:\Users\bernh\local-email-stack")
spec = importlib.util.spec_from_file_location("fz", REPO/"scripts"/"fulfill-referral-requests.py")
fz = importlib.util.module_from_spec(spec); spec.loader.exec_module(fz)
if hasattr(sys.stdout,"reconfigure"): sys.stdout.reconfigure(encoding="utf-8",errors="replace")
SEND = "--send" in sys.argv
env = fz.load_env(); index = json.loads(fz.CURATED.read_text(encoding="utf-8"))
ADDRS = ["austin@mynexthomeelite.com","taylorvanhoy@kw.com",
         "rachel.firestone@talktotucker.com","courtney@thestewarthomegroup.com"]
for addr in ADDRS:
    ps = fz.supa_get(env, f"prospects?email=eq.{urllib.parse.quote(addr)}"
                          f"&select=first_name,company,website,city,state,phone,unsubscribed&limit=1")
    if not ps: print(f"  ! {addr}: not a prospect (skip)"); continue
    p = ps[0]
    if p.get("unsubscribed"): print(f"  ! {addr}: unsubscribed (skip)"); continue
    rep = fz.supa_get(env, "replies?from_addr=eq."+urllib.parse.quote(addr)+
                      "&select=body_snippet&order=received_at.desc&limit=1")
    zc = fz.zip_in_reply(rep[0].get("body_snippet")) if rep else None
    ac = fz.area_code(p.get("phone"))
    entry = fz.resolve(index, p.get("city"), p.get("state"), ac, zc)
    q = (entry or {}).get("quality") or {}
    if not (entry and q.get("passed")):
        print(f"  ! {addr}: no QC-passed metro (zip={zc} ac={ac}) — SKIP"); continue
    site = fz.fetch_site(fz.site_url_for(p, addr)) if SEND else None
    note = fz.personal_note(p, site)
    tag = "SENT" if SEND else "dry"
    ok = fz.send_list(env, addr, p, entry, zc, site, dry=not SEND)
    print(f"  [{tag}] {addr} -> {entry['metro']} (zip={zc or '-'}) ok={ok}")
    print(f"        note: {note or '(generic)'}")
