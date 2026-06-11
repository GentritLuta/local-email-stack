# -*- coding: utf-8 -*-
"""_fix-algoalpha-replyto.py — set every algoalpha persona reply_to to the one
monitored mailbox (info@aureonglobal.de), in place, WITHOUT touching from_domains
(so it won't clobber provisioning progress / resend_domain_ids).
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sequences"))
from profile_lib import load_profile, save_profile  # noqa

REPLY_TO = "info@aureonglobal.de"
p = load_profile("algoalpha")
n = 0
for persona in p.get("personas", []):
    if persona.get("reply_to") != REPLY_TO:
        persona["reply_to"] = REPLY_TO
        n += 1
save_profile(p)
print(f"algoalpha: set reply_to=info@aureonglobal.de on {n} personas "
      f"({len(p.get('personas', []))} total). from_domains untouched "
      f"({len(p['relay']['from_domains'])} domains).")
