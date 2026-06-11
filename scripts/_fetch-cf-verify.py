"""Fetch the latest Cloudflare account-verification email from info@aureonglobal.de
and print the verification link(s) so we can complete signup verification."""
import imaplib, email, re, datetime as dt
from email.header import decode_header
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
user = env.get("SMTP_USER", "info@aureonglobal.de"); pw = env.get("SMTP_PASS", "")

def body_text(msg):
    out = []
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ("text/plain", "text/html"):
                try: out.append(part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "ignore"))
                except Exception: pass
    else:
        try: out.append(msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", "ignore"))
        except Exception: pass
    return "\n".join(out)

imap = imaplib.IMAP4_SSL("imap.hostinger.com", 993)
imap.login(user, pw)
since = (dt.datetime.utcnow() - dt.timedelta(hours=6)).strftime("%d-%b-%Y")
found = []
for folder in ["INBOX", "INBOX.Junk"]:
    if imap.select(folder, readonly=True)[0] != "OK":
        continue
    typ, data = imap.search(None, "SINCE", since)
    for num in (data[0].split() if data and data[0] else []):
        typ, md = imap.fetch(num, "(RFC822)")
        if typ != "OK":
            continue
        msg = email.message_from_bytes(md[0][1])
        frm = str(msg.get("From", "")); subj = str(msg.get("Subject", ""))
        if "cloudflare" not in (frm + subj).lower():
            continue
        body = body_text(msg)
        urls = re.findall(r'https?://[^\s"\'<>)]+', body)
        cf_urls = [u for u in urls if "cloudflare" in u and any(k in u.lower() for k in ("verif", "confirm", "activate", "email", "token", "t="))]
        found.append((str(msg.get("Date", "")), subj[:60], cf_urls[:3], urls[:6]))
imap.logout()

if not found:
    print("No Cloudflare email found in the last 6h (check spam / resend).")
for date, subj, cf, allu in found[-3:]:
    print(f"--- {date} | {subj}")
    print("  verify links:", cf or "(none matched; all urls below)")
    if not cf:
        for u in allu: print("    ", u[:160])
