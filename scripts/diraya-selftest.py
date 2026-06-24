"""diraya-selftest.py - ONE-TIME confidence check. The moment a Diraya sender first
verifies in Resend, send a REAL GHOSTS + REVIEW email to the operator inbox
(info@aureonglobal.de) so the actual rendering, attachments, and links can be eyeballed
before any prospect sees them.

Sentinel-guarded so it fires exactly once. Reuses the live fulfiller's verified-sender
selection + send logic. After a successful send it writes the sentinel AND disables its
own scheduled task (LES-diraya-selftest) so it stops running. Safe to schedule every
15 min: it no-ops until a sender verifies, fires once, then no-ops / self-disables.
"""
from __future__ import annotations
import base64
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# import the hyphenated fulfiller module to reuse its helpers
_spec = importlib.util.spec_from_file_location("ff", REPO / "scripts" / "fulfill-diraya-magnets.py")
ff = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ff)

SENTINEL = REPO / "referral-lists" / ".diraya_selftest_sent"
TO = "info@aureonglobal.de"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    if SENTINEL.exists():
        print("self-test already sent [no-op]"); return 0
    env = ff.load_env()
    rk = env.get("RESEND_NEW_ACCOUNT_API_KEY")
    if not rk:
        print("no RESEND_NEW_ACCOUNT_API_KEY"); return 1
    persona = ff.pick_persona(ff.verified_roots(rk))
    if not persona:
        print("no verified Diraya sender yet [no-op]"); return 0

    print(f"VERIFIED -> sending self-test from {persona['from_addr']} to {TO}")
    gl = env.get("DIRAYA_GHOSTS_URL") or ""
    rl = env.get("DIRAYA_REVIEW_URL") or ""

    # GHOSTS: reuse the real handler (it has no bcc, ideal for a test)
    ok1 = ff.send_ghosts(env, TO, "Gentrit", persona, gl, False)

    # REVIEW: build inline so the test does NOT bcc Mohammed (info@diraya.ca)
    name = persona["from_name"].split(" from ")[0]
    paras = [
        "Hi Gentrit,",
        "As promised, your architecture review is attached. It is the reference build we "
        "start from, the three risks that kill most AI features before they ship, and a "
        "realistic 8-week timeline to production.",
    ]
    if rl:
        paras.append(f"Prefer a link: {rl}")
    paras.append(
        "This is the general version. For the review tailored to your exact stack and data, "
        "reply with two lines on what you are building and I send it back inside 48 hours, or "
        f"grab 15 minutes here: {ff.CALENDLY}")
    sig = persona.get("signature", f"{name}\nDiraya Inc")
    ok2 = ff._post_email(rk, {
        "from": f"{persona['from_name']} <{persona['from_addr']}>",
        "to": [TO], "reply_to": persona.get("reply_to", "info@diraya.ca"),
        "subject": "Your architecture review",
        "html": ff._wrap_html(paras, sig), "text": "\n\n".join(paras) + "\n\n" + sig,
        "attachments": [{"filename": ff.REVIEW_PDF.name,
                         "content": base64.b64encode(ff.REVIEW_PDF.read_bytes()).decode()}],
        "tags": [{"name": "kind", "value": "diraya_selftest"}],
    })

    print(f"ghosts={ok1}  review={ok2}")
    if ok1 and ok2:
        SENTINEL.write_text("sent")
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command",
                            "Disable-ScheduledTask -TaskName LES-diraya-selftest"],
                           capture_output=True, timeout=30,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception as e:
            print("note: could not disable own task:", e)
        print("SELF-TEST SENT to", TO, "(GHOSTS + REVIEW). Sentinel written; task disabled.")
        return 0
    print("send failed; will retry next run (no sentinel written)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
