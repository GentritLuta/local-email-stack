"""Deliver Jake Stiles the divorce/estate/probate attorney referral list.

  py scripts/_send-jake-list.py --test   # send to info@aureonglobal.de to review
  py scripts/_send-jake-list.py --dry    # print, do not send
  py scripts/_send-jake-list.py          # REAL send to jake@cbstiles.com (bcc info@)

Plain note (no in-body table) + apology that the first file came through bugged.
The list ships as a styled .xlsx + a clean BOM .csv. Real mode BCCs info@ and
marks Jake's reply fulfilled so the scheduled auto-fulfiller never double-sends.
"""
import base64, html, importlib.util, json, sys, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TEST = "--test" in sys.argv
DRY = "--dry" in sys.argv

_spec = importlib.util.spec_from_file_location("bjl", REPO / "scripts" / "build-jake-list.py")
bjl = importlib.util.module_from_spec(_spec); _spec.loader.exec_module(bjl)
data, XLSX, CSVF = bjl.build()
n = len(data)

FROM = "Anna from Aureon Global <anna@outreach.aureonglobal.de>"
REPLY_TO = "anna@outreach.aureonglobal.de"
BCC = "info@aureonglobal.de"
REPLY_ID = "1aa6d600-36f9-4f7a-abcd-12018f33bdd5"   # Jake's "List" reply
STATE = REPO / "referral-lists" / ".fulfilled.json"

if TEST:
    TO = "info@aureonglobal.de"; bcc = None; SUBJECT = "[TEST] Re: still yours if you want it"
else:
    TO = "jake@cbstiles.com"; bcc = [BCC]; SUBJECT = "Re: still yours if you want it"

paras = [
    "Hey Jake,",
    "Quick correction on my last message. The list came through as a jumbled "
    "file on your end. That was a glitch on my side and I am sorry about that.",
    f"Here is the clean version, attached two ways: an Excel file and a CSV you "
    f"can import straight into your CRM. It is {n} firms across Greenwood, "
    f"Indianapolis, and the surrounding metro, covering divorce and family law "
    f"plus estate and probate, the two groups whose clients most often need to "
    f"sell a home fast. For each firm you get the lead attorney to ask for, "
    f"their practice focus, a direct phone, an email where the firm publishes "
    f"one, the website, and the office address.",
    "The fastest way to use it: start with the Greenwood firms grouped at the "
    "top, call or email the lead attorney, and offer to be the agent they send "
    "any client who needs to sell quickly. Probate and divorce sellers are "
    "usually motivated, so even one or two firms saying yes can mean steady "
    "listings.",
    "No call needed and no strings. If you ever want us to run the seller "
    "outbound that keeps a pipeline like this full for you, just reply and I "
    "will send the details.",
]
sig = ("Anna Bauer", "Senior Partnership Manager, Aureon Global")

text_body = "\n\n".join(paras) + "\n\n" + sig[0] + "\n" + sig[1]
html_body = (
    '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif;'
    'color:#1e293b;max-width:580px;line-height:1.55;font-size:15px">'
    + "".join(f"<p>{html.escape(p)}</p>" for p in paras)
    + f'<p style="margin-top:18px">{html.escape(sig[0])}<br>'
    f'<span style="color:#64748b">{html.escape(sig[1])}</span></p></div>'
)

attachments = [
    {"filename": "Attorney-Referral-List-Indianapolis.xlsx",
     "content": base64.b64encode(XLSX.read_bytes()).decode()},
    {"filename": "Attorney-Referral-List-Indianapolis.csv",
     "content": base64.b64encode(CSVF.read_bytes()).decode()},
]
payload = {"from": FROM, "to": [TO], "reply_to": REPLY_TO, "subject": SUBJECT,
           "html": html_body, "text": text_body, "attachments": attachments,
           "tags": [{"name": "kind", "value": "referral_fulfilment"}]}
if bcc:
    payload["bcc"] = bcc

print(f"mode     : {'TEST -> info@' if TEST else 'REAL -> Jake'}")
print(f"to       : {TO}" + (f"  (bcc {BCC})" if bcc else ""))
print(f"subject  : {SUBJECT}")
print(f"firms    : {n}  | attached: xlsx ({XLSX.stat().st_size} b) + csv ({CSVF.stat().st_size} b)")
if DRY:
    print("\n--- TEXT BODY ---\n" + text_body + "\n\n[dry] not sending."); sys.exit(0)


def resend_key() -> str:
    try:
        priv = json.loads((REPO / "profiles" / "aureon.private.json").read_text(encoding="utf-8"))
        if priv.get("relay", {}).get("resend_api_key"):
            return priv["relay"]["resend_api_key"]
    except Exception:
        pass
    for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
        if line.startswith("RESEND_FULL_ACCESS_API_KEY"):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


key = resend_key()
if not key:
    sys.exit("! no Resend API key found")
req = urllib.request.Request(
    "https://api.resend.com/emails", data=json.dumps(payload).encode(), method="POST",
    headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
             "User-Agent": "local-email-stack jake-fulfil/1.0"})
try:
    resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
    print("\nSENT OK  resend id:", resp.get("id", "(none)"))
except Exception as e:
    body = getattr(e, "read", lambda: b"")()
    sys.exit(f"\n! send failed: {e}  {body[:300]}")

if not TEST:
    done = set(json.loads(STATE.read_text())) if STATE.exists() else set()
    done.add(REPLY_ID)
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(sorted(done)))
    print("marked reply", REPLY_ID, "fulfilled (no double-send).")
