"""Verify the open + click tracker fires updates against send_log.

Uses the most recent step-5 test send to info@aureonglobal.de (just sent
by _e2e-prove-everything.py). Pulls its message_id, constructs the pixel
+ click URLs deterministically (we control the template), hits both,
asserts opened_at/clicked_at populate.

This validates the LAST 4 failures from the previous e2e test, which
were a search-bug cascade — not actual pipeline failures.
"""
from __future__ import annotations
import datetime as dt, json, os, sys, time, urllib.parse, urllib.request
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO/"sequences"/"supabase.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k,v=line.split("=",1); env[k.strip()]=v.strip()
URL=env["SUPABASE_URL"]; KEY=env["SUPABASE_ANON_KEY"]
H_R={"apikey":KEY,"Authorization":f"Bearer {KEY}"}
TRACKER_BASE = os.environ.get("AUREON_TRACKER_BASE","http://127.0.0.1:8765")

def get(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H_R), timeout=15).read())

PASSES, FAILS = [], []
def check(name, cond, detail=""):
    PASSES.append(name) if cond else FAILS.append((name,detail))
    print(f"  {'OK' if cond else 'FAIL':4} {name}  {detail}")
    return cond

print("="*70)
print("TRACKING PIXEL + CLICK VERIFICATION")
print(f"TRACKER_BASE = {TRACKER_BASE}")
print("="*70)

# Step 1: find the most recent step-5 send to info@aureonglobal.de
rows = get("send_log?to_addr=eq.info@aureonglobal.de&step_n=eq.5&select=id,sent_at,subject,message_id,opened_at,clicked_at&order=sent_at.desc&limit=1")
check("found recent step-5 send_log row", bool(rows), f"rows={len(rows)}")
if not rows: sys.exit(1)
r = rows[0]
print(f"  send_log_id   = {r['id']}")
print(f"  sent_at       = {r['sent_at']}")
print(f"  subject       = {r['subject']}")
print(f"  message_id    = {r['message_id']}")
print(f"  opened_at(pre)= {r['opened_at']}")
print(f"  clicked_at(pre)={r['clicked_at']}")

# Extract track token (hex part of message_id)
msg_id = r['message_id'] or ""
track_token = msg_id.strip("<>").split(".")[0] if msg_id else ""
check("track_token extractable", len(track_token)==32 and all(c in "0123456789abcdef" for c in track_token), f"token={track_token}")

# Step 2: GET the pixel URL — simulate recipient opening the email
print("\n[OPEN] hitting pixel URL...")
pixel_url = f"{TRACKER_BASE}/open/{track_token}.gif"
print(f"  GET {pixel_url}")
body = urllib.request.urlopen(pixel_url, timeout=10).read()
check("pixel GET returned image bytes", len(body) > 0 and len(body) < 1000, f"len={len(body)}")

# Wait a moment for the patch to propagate
time.sleep(1.5)
r2 = get(f"send_log?id=eq.{r['id']}&select=opened_at")[0]
check("opened_at populated", r2.get("opened_at") is not None, f"opened_at={r2.get('opened_at')}")

# Step 3: GET a click URL — simulate recipient clicking
print("\n[CLICK] hitting click URL...")
click_url = f"{TRACKER_BASE}/click/{track_token}?u={urllib.parse.quote('https://aureonglobal.de', safe='')}"
print(f"  GET {click_url}")
# Don't follow the 302 (we just care that the click was logged)
import http.client as _hc, urllib.parse as _up
parsed = _up.urlparse(click_url)
conn = _hc.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=10)
conn.request("GET", parsed.path + "?" + parsed.query)
resp = conn.getresponse()
loc = resp.getheader("Location")
print(f"  response: status={resp.status} Location={loc}")
check("click returned 302 redirect", resp.status == 302, f"status={resp.status}")
check("click redirected to original URL", loc == "https://aureonglobal.de", f"loc={loc}")

time.sleep(1.5)
r3 = get(f"send_log?id=eq.{r['id']}&select=clicked_at")[0]
check("clicked_at populated", r3.get("clicked_at") is not None, f"clicked_at={r3.get('clicked_at')}")

print("\n" + "="*70)
print(f"PASS: {len(PASSES)}  FAIL: {len(FAILS)}")
for n,d in FAILS: print(f"  - {n}  {d}")
print("="*70)
sys.exit(0 if not FAILS else 1)
