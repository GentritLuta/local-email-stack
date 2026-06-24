"""seed-test.py — inbox-placement seed test. Sends ONE real, fully branded
step-1 email from each active brand to a list of seed mailboxes you control
(Gmail / Outlook / Yahoo / etc.), so you can open each seed inbox and see the
actual folder (Primary / Promotions / Spam) each brand lands in.

This is the only way to get folder-level certainty beyond the open-rate proxy.

Seed addresses: put one per line in out/seed_addresses.txt, OR pass --to a,b,c
Use addresses on different providers (a @gmail.com, an @outlook.com, a @yahoo.com)
for a representative read.

Usage:
  py scripts/seed-test.py --to you@gmail.com,you@outlook.com --dry
  py scripts/seed-test.py                       # reads out/seed_addresses.txt, sends live
  py scripts/seed-test.py --brands aureon,diraya # limit to some brands
"""
from __future__ import annotations
import argparse
import json
import smtplib
import ssl
import sys
import urllib.request
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from email_render import render_html  # noqa: E402

UA = "LocalEmailStack-seedtest/1.0"
SAMPLE = {"greeting": "there", "first_name": "there", "company": "your company", "city": "your city"}


def env(path):
    e = {}
    for line in (REPO / "sequences" / path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); e[k.strip()] = v.strip().strip('"').strip("'")
    return e


HOST = env("hostinger.env")


def merge(s):
    for k, v in SAMPLE.items():
        s = s.replace("{" + k + "}", v)
    return s


def load(slug):
    prof = json.loads((REPO / "profiles" / f"{slug}.json").read_text(encoding="utf-8"))
    try:
        priv = json.loads((REPO / "profiles" / f"{slug}.private.json").read_text(encoding="utf-8"))
        prof.setdefault("relay", {}).update(priv.get("relay", {}))
    except Exception:
        pass
    return prof


def step1_body(slug):
    v = json.loads((REPO / "sequences" / f"{slug}-default" / "variants.json").read_text(encoding="utf-8"))["variants"]
    e = next((x for x in v if x["n"] == 1), v[0])
    return merge(e["body"]), merge(e["subject"])


def send_resend(key, from_addr, persona_name, to_addr, subject, html, text):
    payload = {"from": f"{persona_name} <{from_addr}>", "to": [to_addr],
               "subject": subject, "html": html, "text": text,
               "tags": [{"name": "kind", "value": "seed_test"}]}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(),
                                 method="POST", headers={"Authorization": f"Bearer {key}",
                                 "Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=25); return True, "resend ok"
    except urllib.error.HTTPError as e:
        return False, f"resend {e.code}: {e.read().decode()[:160]}"


def send_hostinger(to_addr, persona_name, subject, html, text):
    user, pw = HOST.get("SMTP_USER"), HOST.get("SMTP_PASS")
    if not pw:
        return False, "no SMTP_PASS"
    m = MIMEMultipart("alternative")
    m.attach(MIMEText(text, "plain", "utf-8")); m.attach(MIMEText(html, "html", "utf-8"))
    m["Subject"] = subject; m["From"] = f"{persona_name} from Aureon Global <{user}>"; m["To"] = to_addr
    try:
        with smtplib.SMTP_SSL("smtp.hostinger.com", 465, context=ssl.create_default_context()) as s:
            s.login(user, pw); s.sendmail(user, [to_addr], m.as_string())
        return True, "hostinger ok"
    except Exception as e:
        return False, str(e)[:160]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", default=None, help="comma-separated seed addresses")
    ap.add_argument("--brands", default=None, help="comma-separated profile slugs (default: all active)")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    seeds = ([s.strip() for s in args.to.split(",") if s.strip()] if args.to else
             [l.strip() for l in (REPO / "out" / "seed_addresses.txt").read_text(encoding="utf-8").splitlines()
              if l.strip() and not l.startswith("#")] if (REPO / "out" / "seed_addresses.txt").exists() else [])
    if not seeds:
        print("No seed addresses. Pass --to a@gmail.com,b@outlook.com or fill out/seed_addresses.txt")
        return 2

    slugs = ([s.strip() for s in args.brands.split(",")] if args.brands else
             [p.stem for p in (REPO / "profiles").glob("*.json")
              if "private" not in p.stem and json.loads(p.read_text(encoding="utf-8")).get("active")])
    print(f"Seed test -> {len(seeds)} seed(s), {len(slugs)} brand(s){' [DRY]' if args.dry else ''}\n")

    for slug in slugs:
        prof = load(slug)
        brand = prof.get("brand") or {}
        persona = (prof.get("personas") or [{}])[0]
        pname = persona.get("from_name", "Team")
        fds = (prof.get("relay") or {}).get("from_domains") or []
        from_dom = next((d.get("domain") for d in fds if d.get("verified_at")), None) or (fds[0].get("domain") if fds else None)
        local = (persona.get("local_part") or persona.get("slug") or "hello")
        try:
            body, subj = step1_body(slug)
        except Exception as e:
            print(f"  {slug:14} ! no variants ({e})"); continue
        subject = f"[seed:{slug}] {subj}"
        html = render_html(body=body, persona=persona, unsubscribe_token="seed-test",
                           brand=brand, step_n=1)
        for to in seeds:
            if args.dry:
                via = "hostinger" if slug == "aureon" else f"resend({from_dom or 'NO DOMAIN'})"
                print(f"  [DRY] {slug:14} -> {to:30} via {via}")
                continue
            if slug == "aureon":
                ok, msg = send_hostinger(to, pname, subject, html, body)
            else:
                key = (prof.get("relay") or {}).get("resend_api_key", "")
                from_addr = f"{local}@{from_dom}" if from_dom else None
                if not key or not from_addr:
                    ok, msg = False, "no resend key / from domain"
                else:
                    ok, msg = send_resend(key, from_addr, pname, to, subject, html, body)
            print(f"  {'OK  ' if ok else 'FAIL'} {slug:14} -> {to:30} {msg}")
    if not args.dry:
        print("\nNow open each seed inbox and note the FOLDER per [seed:<brand>] subject.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
