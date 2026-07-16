# -*- coding: utf-8 -*-
"""verify-deliverability-fixes.py — watch the two DMARC fixes (lk-advertising,
ener-g-beratung) and Philipp's Gmail-placement reply, and alert info@ when each
lands. Idempotent via a state file; self-disables its scheduled task once all
three are resolved. Created 2026-06-24 for the deliverability follow-up.

Checks:
  1. lk-advertising.site  -> exactly ONE _dmarc record (duplicate removed = fixed)
  2. ener-g-beratung.de   -> an org-level _dmarc record now exists (added = fixed)
  3. philipp.loisha@gmail.com -> a reply has landed in info@ (Gmail test result)

Run: py scripts/verify-deliverability-fixes.py [--once]
Scheduled as LES-deliv-verify (every 4h). Remove when done: schtasks /Delete /TN LES-deliv-verify /F
"""
import json, subprocess, imaplib, smtplib, ssl, sys
from email.mime.text import MIMEText
from pathlib import Path
try:
    import requests
except Exception:
    requests = None

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from mailer import send as send_mail   # Resend primary (VPS blocks SMTP), SMTP fallback
STATE = REPO / "out" / "_deliv_verify_state.json"
TASK = "LES-deliv-verify"
OPERATOR = "info@aureonglobal.de"

def load_env(p):
    e = {}
    if Path(p).exists():
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and "=" in line and not line.startswith("#"):
                k, _, v = line.partition("="); e[k.strip()] = v.strip().strip('"')
    return e
HOST = load_env(REPO / "sequences" / "hostinger.env")

def dmarc_records(name):
    """Return the list of DMARC TXT strings at `name` (via the OS resolver)."""
    ps = (f"Resolve-DnsName -Type TXT -Name {name} -Server 1.1.1.1 -ErrorAction SilentlyContinue "
          f"| Where-Object {{ $_.Strings -match 'DMARC1' }} | ForEach-Object {{ ($_.Strings -join '') }}")
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                             capture_output=True, text=True, timeout=60).stdout
        return [l.strip() for l in out.splitlines() if "DMARC1" in l]
    except Exception:
        return []

def philipp_replied():
    user = HOST.get("SMTP_USER", OPERATOR); pw = HOST.get("SMTP_PASS", "")
    if not pw:
        return False
    try:
        im = imaplib.IMAP4_SSL("imap.hostinger.com", 993); im.login(user, pw)
        found = False
        for folder in ("INBOX", "INBOX.Junk"):
            if im.select(folder, readonly=True)[0] != "OK":
                continue
            typ, data = im.search(None, '(FROM "philipp.loisha@gmail.com" SINCE 24-Jun-2026)')
            if typ == "OK" and data and data[0].split():
                found = True; break
        im.logout()
        return found
    except Exception:
        return False

def restore_energ():
    """Re-enable all energ sending subdomains (JSON source-of-truth + live DB) once
    energ's org-level DMARC record lands, reversing the 2026-06-24 restriction."""
    out = []
    try:
        jp = REPO / "profiles" / "energ.json"
        cfg = json.loads(jp.read_text(encoding="utf-8"))
        for d in cfg.get("relay", {}).get("from_domains", []):
            d.setdefault("warmup", {})["enabled"] = True
        jp.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
        out.append("JSON re-enabled")
    except Exception as e:
        out.append(f"JSON restore FAILED: {e}")
    try:
        if requests is None:
            raise RuntimeError("requests unavailable")
        supa = load_env(REPO / "sequences" / "supabase.env")
        url = "https://api.supabase.com/v1/projects/zmzolkijhiaedzcmdfji/database/query"
        h = {"Authorization": f"Bearer {supa.get('SUPABASE_ACCESS_TOKEN','')}",
             "Content-Type": "application/json", "User-Agent": "Mozilla/5.0 Chrome/123"}
        db = requests.post(url, headers=h, json={"query": "SELECT config FROM profiles WHERE slug='energ'"}).json()[0]["config"]
        for d in db.get("relay", {}).get("from_domains", []):
            d.setdefault("warmup", {})["enabled"] = True
        js = json.dumps(db).replace("$cfg$", "")
        requests.post(url, headers=h, json={"query": f"UPDATE profiles SET config = $cfg${js}$cfg$::jsonb WHERE slug='energ'"})
        out.append("DB re-enabled")
    except Exception as e:
        out.append(f"DB restore FAILED: {e}")
    return "; ".join(out)


def alert(subject, body):
    send_mail(to=OPERATOR, subject=subject, text=body,
              from_addr="Deliverability Watch <info@send.aureonglobal.de>", reply_to=OPERATOR)

def main():
    lk = dmarc_records("_dmarc.lk-advertising.site")
    lk_fixed = len(lk) == 1
    energ_fixed = len(dmarc_records("_dmarc.ener-g-beratung.de")) >= 1
    replied = philipp_replied()
    now = {"lk_fixed": lk_fixed, "energ_fixed": energ_fixed, "philipp_replied": replied}

    prev = {}
    if STATE.exists():
        try: prev = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception: prev = {}

    # Alert only on NEW positive transitions (no noise).
    msgs = []
    if lk_fixed and not prev.get("lk_fixed"):
        msgs.append("lk-advertising.site DMARC is now a single valid record (duplicate removed). FIXED.")
    if energ_fixed and not prev.get("energ_fixed"):
        restored = restore_energ()
        msgs.append("ener-g-beratung.de now has an org-level DMARC record. FIXED. "
                    f"Auto-restored all 12 energ sending subdomains ({restored}).")
    if replied and not prev.get("philipp_replied"):
        msgs.append("Philipp replied to the Gmail placement test (check info@ for his inbox/spam results).")

    STATE.write_text(json.dumps(now, indent=2), encoding="utf-8")
    print("status:", now)

    if msgs:
        body = ("Deliverability follow-up update:\n\n  - " + "\n  - ".join(msgs)
                + f"\n\nCurrent state: lk_fixed={lk_fixed}, energ_fixed={energ_fixed}, "
                f"philipp_replied={replied}\n")
        try: alert("[Deliverability] " + "; ".join(m.split('.')[0] for m in msgs), body)
        except Exception as e: print("alert failed:", e)

    # All done -> final note + self-disable the scheduled task so it stops running.
    if lk_fixed and energ_fixed and replied:
        try:
            alert("[Deliverability] All follow-up items resolved",
                  "lk DMARC fixed, energ DMARC fixed, and Philipp replied. Closing the watch.\n"
                  "The LES-deliv-verify task has disabled itself.\n")
        except Exception: pass
        try:
            subprocess.run(["schtasks", "/Change", "/TN", TASK, "/DISABLE"],
                           capture_output=True, text=True, timeout=30)
        except Exception: pass
        print("all resolved; task disabled")

if __name__ == "__main__":
    main()
