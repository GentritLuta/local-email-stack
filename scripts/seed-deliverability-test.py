#!/usr/bin/env python3
"""seed-deliverability-test.py — automated inbox-placement + auth probe.

For each ACTIVE profile, sends one realistic campaign-style seed from that
profile's own sending domain (persona[0].from_addr) to info@aureonglobal.de,
then reports where it landed (INBOX vs Junk/Spam) and whether SPF/DKIM/DMARC
passed (from the received Authentication-Results header).

HONEST SCOPE: this measures placement at Hostinger (info@'s provider) only. It
does NOT measure Gmail/Outlook placement, where most prospects are — that needs
seed accounts at those providers (which cannot be auto-created). A Junk result
here is a strong red flag; an INBOX result only means Hostinger accepted it.

  py scripts/seed-deliverability-test.py            # send + check all active profiles
  py scripts/seed-deliverability-test.py --check    # re-check placement of the last run (no send)
"""
from __future__ import annotations
import argparse, json, sys, time, imaplib, email, glob
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SEED_TO = "info@aureonglobal.de"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def env(p: Path) -> dict:
    out = {}
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        s = ln.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1); out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def supa_get(q):
    import urllib.request
    e = env(REPO / "sequences" / "supabase.env")
    url = e["SUPABASE_URL"].rstrip("/"); key = e.get("SUPABASE_SERVICE_KEY", "")
    req = urllib.request.Request(url + "/rest/v1/" + q,
                                 headers={"apikey": key, "Authorization": f"Bearer {key}"})
    return json.loads(urllib.request.urlopen(req, timeout=40).read().decode())


def resend_key(slug: str) -> str | None:
    f = REPO / "profiles" / f"{slug}.private.json"
    if f.exists():
        return (json.load(open(f, encoding="utf-8")).get("relay") or {}).get("resend_api_key")
    return None


def send_seed(from_addr: str, from_name: str, key: str, tag: str) -> tuple[int, str]:
    import httpx
    body = (f"Hi there,\n\nQuick note from our team. We put together a short overview that "
            f"might be useful and wanted to share it. If it is worth a look, just reply.\n\n"
            f"Best,\n{from_name}\n\nUnsubscribe: https://example.com/u/{tag}\n")
    r = httpx.post("https://api.resend.com/emails",
                   headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
                   json={"from": f"{from_name} <{from_addr}>", "to": [SEED_TO],
                         "subject": f"A quick overview for you [{tag}]", "text": body},
                   timeout=30)
    return r.status_code, (r.json().get("id", "") if r.status_code == 200 else r.text[:120])


def check_placement(tags: dict[str, str], wait_s: int = 180) -> None:
    he = env(REPO / "sequences" / "hostinger.env")
    user, pw = he.get("SMTP_USER", SEED_TO), he.get("SMTP_PASS", "")
    folders = [("INBOX", "INBOX"), ("INBOX.Junk", "JUNK"), ("Junk", "JUNK"), ("INBOX.Spam", "SPAM")]
    found: dict[str, tuple[str, str]] = {}
    deadline = time.time() + wait_s
    while time.time() < deadline and len(found) < len(tags):
        try:
            M = imaplib.IMAP4_SSL("imap.hostinger.com", 993); M.login(user, pw)
            for fname, label in folders:
                try:
                    if M.select(fname, readonly=True)[0] != "OK":
                        continue
                except Exception:
                    continue
                for slug, tag in tags.items():
                    if slug in found:
                        continue
                    _, data = M.search(None, f'(SUBJECT "{tag}")')
                    if data and data[0]:
                        mid = data[0].split()[-1]
                        _, md = M.fetch(mid, '(BODY.PEEK[HEADER.FIELDS (AUTHENTICATION-RESULTS)])')
                        ar = ""
                        if md and md[0]:
                            ar = email.message_from_bytes(md[0][1]).get("Authentication-Results", "") or ""
                        auth = ",".join(t for t in ("spf=pass", "dkim=pass", "dmarc=pass") if t in ar.lower()) or "auth?"
                        found[slug] = (label, auth)
            M.logout()
        except Exception as ex:
            print("  imap error:", type(ex).__name__, str(ex)[:70])
        if len(found) < len(tags):
            time.sleep(15)
    print("\n=== placement (Hostinger info@ inbox) ===")
    for slug in tags:
        if slug in found:
            label, auth = found[slug]
            flag = "OK  " if label == "INBOX" else "!!  "
            print(f"  {flag}{slug:16s} -> {label:6s} | {auth}")
        else:
            print(f"  ??  {slug:16s} -> NOT DELIVERED (not in INBOX/Junk/Spam within {wait_s}s)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="re-check last run's tags (no send)")
    a = ap.parse_args()
    stamp = int(time.time())
    tagfile = REPO / "logs" / "seed-test-tags.json"
    if a.check:
        tags = json.loads(tagfile.read_text(encoding="utf-8"))
        check_placement(tags); return 0

    profiles = supa_get("profiles?select=slug,active,config&active=eq.true")
    tags: dict[str, str] = {}
    print("sending seeds from each active domain -> info@aureonglobal.de")
    for p in profiles:
        slug = p["slug"]; c = p["config"]; ps = c.get("personas") or []
        if not ps:
            print(f"  {slug}: no personas, skip"); continue
        key = resend_key(slug)
        if not key:
            print(f"  {slug}: no resend key, skip"); continue
        persona = ps[0]
        tag = f"SEEDTEST-{slug}-{stamp}"
        st, info = send_seed(persona["from_addr"], persona.get("from_name", "Team"), key, tag)
        print(f"  {slug:16s} from {persona['from_addr']:32s} -> resend {st} {info[:30]}")
        if st == 200:
            tags[slug] = tag
    tagfile.parent.mkdir(parents=True, exist_ok=True)
    tagfile.write_text(json.dumps(tags), encoding="utf-8")
    if tags:
        check_placement(tags)
    return 0


if __name__ == "__main__":
    sys.exit(main())
