# -*- coding: utf-8 -*-
"""Demo: send the REAL Diraya step-1 nurture opener to the operator inbox via the
exact production render+send pipeline (build_payload), from a verified Diraya
persona on the new Resend account. One-off — does NOT enroll a full sequence."""
import sys, json, urllib.request
from pathlib import Path
REPO = Path(r"C:\Users\bernh\local-email-stack")
sys.path.insert(0, str(REPO / "sequences"))
from profile_lib import load_profile, iter_send_domains, materialize_persona  # noqa
from email_render import build_payload  # noqa

env = {}
for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
RK = env["RESEND_NEW_ACCOUNT_API_KEY"]
TO = "info@aureonglobal.de"

profile = load_profile("diraya")
persona = next(p for p in profile["personas"] if p["slug"] == "sami-hello")  # Sami Toumi
domain = iter_send_domains(profile)[0]
mat = materialize_persona(persona, domain)

variants = json.loads((REPO / "sequences" / "diraya-default" / "variants.json").read_text(encoding="utf-8"))["variants"]
v = next(x for x in variants if x.get("n") == 1)
DEMO = {"first_name": "Gentrit", "company": "Aureon Global"}
body, subject = v["body"], v["subject"]
for t, val in DEMO.items():
    body = body.replace("{" + t + "}", val); subject = subject.replace("{" + t + "}", val)

payload, _ = build_payload(persona=mat, to_addr=TO, subject=subject, body=body,
                           brand=profile.get("brand") or {}, step_n=1)
req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(),
                             method="POST", headers={"Authorization": "Bearer " + RK,
                             "Content-Type": "application/json", "User-Agent": "les-diraya-demo/1.0"})
try:
    r = json.loads(urllib.request.urlopen(req, timeout=30).read())
    print("DEMO SENT id=", r.get("id"))
    print("  from:", payload.get("from"))
    print("  to  :", TO)
    print("  subj:", subject)
except urllib.error.HTTPError as e:
    print("! send failed", e.code, e.read().decode()[:300])
