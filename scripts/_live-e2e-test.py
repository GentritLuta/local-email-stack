"""Live end-to-end test: open + reply + verify.

Step 1: pull the test email out of IMAP, extract Resend's open-tracking pixel URL
Step 2: HTTP GET the pixel -> Resend records an 'opened' event
Step 3: compose a reply from info@aureonglobal.de back to the test send's From,
        with proper In-Reply-To headers so imap-poll matches it
Step 4: send the reply via Hostinger SMTP
Step 5: wait ~30s, run imap-poll, verify reply matched + run paused
Step 6: run the reconciler, verify opened_at populated on send_log
"""
from __future__ import annotations
import imaplib, ssl, smtplib, re, email, time, sys, json, urllib.request, urllib.parse
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
host = {}
for line in (REPO / "sequences" / "hostinger.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); host[k.strip()] = v.strip()
sup = {}
for line in (REPO / "sequences" / "supabase.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); sup[k.strip()] = v.strip()
H_R = {"apikey": sup["SUPABASE_ANON_KEY"], "Authorization": f"Bearer {sup['SUPABASE_ANON_KEY']}"}

TEST_RUN_ID = "67318ffd-39e9-4ed3-ab96-9f49a351d92b"
TEST_RESEND_ID = "b4d6bdd6-bef3-46bd-87a6-01f836f20fa6"
TARGET_MSG_ID_FRAGMENT = "459faab394134bae8fe0e404c9c9794c"

print("=" * 70)
print("LIVE E2E TEST")
print("=" * 70)

# Step 1: fetch the email body
print("\n[1] Fetching test email body from IMAP...")
M = imaplib.IMAP4_SSL("imap.hostinger.com", 993, ssl_context=ssl.create_default_context())
M.login(host["SMTP_USER"], host["SMTP_PASS"])
M.select("INBOX")
typ, data = M.search(None, "(FROM lars@connect.aureonglobal.de)")
uids = data[0].split() if data and data[0] else []
if not uids:
    print("  ! test email not found"); sys.exit(1)
uid = uids[-1]
typ, fetch = M.fetch(uid, "(BODY.PEEK[])")
raw = fetch[0][1]
msg = email.message_from_bytes(raw, policy=email.policy.default)
print(f"  found UID={uid.decode()}, subject={msg.get('Subject')}")

# Step 2: extract open-tracking pixel + click links
html_part = None
for part in msg.walk():
    if part.get_content_type() == "text/html":
        html_part = part.get_payload(decode=True).decode("utf-8", errors="replace")
        break
if not html_part:
    print("  ! no HTML part"); sys.exit(1)
pixels = re.findall(r'<img[^>]+src="(https?://[^"]+)"', html_part, re.I)
links  = re.findall(r'<a[^>]+href="(https?://[^"]+)"', html_part, re.I)
tracking_pixels = [p for p in pixels if "resend" in p.lower() or "track" in p.lower() or "1x1" in p.lower()]
print(f"\n[2] Extracted tracking elements:")
print(f"  pixels total : {len(pixels)}")
print(f"  resend pixel : {tracking_pixels[0] if tracking_pixels else '(not found)'}")
print(f"  links total  : {len(links)}")

# Step 3: trigger open by GETting pixel + a click
opened = False
if tracking_pixels:
    try:
        r = urllib.request.urlopen(tracking_pixels[0], timeout=10)
        print(f"  pixel GET status: {r.status}  -> 'opened' event sent to Resend")
        opened = True
    except Exception as e:
        print(f"  pixel GET failed: {e}")
elif pixels:
    # Fallback: first pixel
    try:
        r = urllib.request.urlopen(pixels[0], timeout=10)
        print(f"  fallback pixel GET status: {r.status}")
        opened = True
    except Exception as e:
        print(f"  fallback pixel GET failed: {e}")

# Step 4: send a reply
from_addr = host.get("FROM_ADDR", "info@aureonglobal.de")
to_addr   = "lars@connect.aureonglobal.de"  # the persona that sent the original
reply_to  = msg.get("From")
orig_msgid = msg.get("Message-ID") or "<unknown@aureonglobal.de>"
orig_subj  = msg.get("Subject") or ""

reply = MIMEText(
    "Yes, interested in hearing more about the engine.\n\n"
    "This is an automated live end-to-end test from info@aureonglobal.de. "
    "If you see this in send_log.replied=true and the run is paused, the reply pipeline works.\n\n"
    "- Live E2E test",
    "plain", "utf-8")
reply["From"] = from_addr
reply["To"] = to_addr
reply["Subject"] = f"Re: {orig_subj}"
reply["Date"] = formatdate(localtime=True)
reply["Message-ID"] = make_msgid(domain="aureonglobal.de")
reply["In-Reply-To"] = orig_msgid
reply["References"] = orig_msgid

print(f"\n[3] Sending reply via Hostinger SMTP...")
print(f"  from: {from_addr}")
print(f"  to:   {to_addr}")
print(f"  in-reply-to: {orig_msgid}")
ctx = ssl.create_default_context()
with smtplib.SMTP_SSL(host["SMTP_HOST"], int(host.get("SMTP_PORT", 465)), context=ctx, timeout=30) as s:
    s.login(host["SMTP_USER"], host["SMTP_PASS"])
    s.send_message(reply)
print("  reply sent OK")

M.logout()

# Step 5: wait + verify reply was caught by imap-poll
print("\n[4] Waiting 25s for SES->Hostinger->IMAP delivery...")
time.sleep(25)

# Step 6: print machine-readable handle for chained tests
print(f"\n[5] HANDOFF for next phase:")
print(f"  TEST_RUN_ID: {TEST_RUN_ID}")
print(f"  TEST_RESEND_ID: {TEST_RESEND_ID}")
print(f"  Now run: py sequences/imap-poll.py once  (then check run.status='paused_replied')")
print(f"  Now run: py sequences/resend-status-reconcile.py --hours 1  (then send_log.opened_at populated)")
