"""Verify the Jake list email actually went out: (1) ask Resend for the most
recent emails to jake@cbstiles.com, (2) check the info@ inbox for the BCC copy."""
import imaplib, email, json, urllib.request, datetime as dt
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

def env(fname):
    d = {}
    for line in (REPO / "sequences" / fname).read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1); d[k.strip()] = v.strip().strip('"').strip("'")
    return d

host = env("hostinger.env")

# --- (1) Resend: try to fetch the email we just sent by listing recent ---
key = ""
try:
    priv = json.loads((REPO / "profiles" / "aureon.private.json").read_text(encoding="utf-8"))
    key = priv.get("relay", {}).get("resend_api_key", "")
except Exception:
    pass
if not key:
    key = host.get("RESEND_FULL_ACCESS_API_KEY", "")

print("=== Resend API check ===")
for path in ("https://api.resend.com/emails?limit=5", "https://api.resend.com/emails"):
    try:
        req = urllib.request.Request(path, headers={"Authorization": f"Bearer {key}"})
        data = json.loads(urllib.request.urlopen(req, timeout=20).read())
        items = data.get("data") or data.get("items") or []
        print(f"  {path} -> {len(items)} items")
        for it in items[:8]:
            print("   ", it.get("created_at",""), it.get("to",""), "|", it.get("subject",""), "|", it.get("last_event",""))
        if items:
            break
    except Exception as e:
        b = getattr(e, "read", lambda: b"")()
        print(f"  {path} -> {e} {b[:120]}")

# --- (2) IMAP: look for the BCC copy in info@aureonglobal.de ---
print("\n=== IMAP BCC check (info@aureonglobal.de inbox) ===")
user = host.get("SMTP_USER", "info@aureonglobal.de"); pw = host.get("SMTP_PASS", "")
try:
    imap = imaplib.IMAP4_SSL("imap.hostinger.com", 993)
    imap.login(user, pw)
    since = (dt.datetime.utcnow() - dt.timedelta(hours=1)).strftime("%d-%b-%Y")
    imap.select("INBOX", readonly=True)
    typ, data = imap.search(None, "SINCE", since)
    hits = 0
    for num in (data[0].split() if data and data[0] else [])[::-1][:40]:
        typ, md = imap.fetch(num, "(BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE)])")
        if typ != "OK":
            continue
        hdr = md[0][1].decode("utf-8", "ignore")
        if "outreach.aureonglobal.de" in hdr and "still yours" in hdr.lower():
            print("  FOUND BCC copy:\n   " + hdr.replace("\r\n", "\n   ").strip())
            hits += 1
    if not hits:
        print("  (no BCC copy yet — may still be propagating; Resend check above is authoritative)")
    imap.logout()
except Exception as e:
    print("  IMAP error:", e)
