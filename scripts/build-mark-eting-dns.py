#!/usr/bin/env python3
"""Pull all mark-eting (getmark-eting.com) subdomain DNS records from Resend and
write them to out/mark-eting-dns-records.txt in the push-client-dns.py format.

Adds a per-subdomain _dmarc TXT (Resend doesn't return one) so deliverability
matches the other clients. NAME is relative to the getmark-eting.com zone root.
"""
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

ROOT = "getmark-eting.com"
KEY = json.loads(Path("profiles/mark-eting.private.json").read_text())["relay"]["resend_api_key"]
PROFILE = json.loads(Path("profiles/mark-eting.json").read_text())
DOMAINS = PROFILE["relay"]["from_domains"]
DMARC = ("v=DMARC1; p=none; rua=mailto:dmarc@mark-eting.co; "
         "ruf=mailto:dmarc@mark-eting.co; pct=100; adkim=s; aspf=s")

HEADERS = {"Authorization": f"Bearer {KEY}", "User-Agent": "les-onboard/1.0"}


def rel(name: str) -> str:
    """Resend returns names already relative to the subdomain root; they include
    the subdomain label (e.g. 'resend._domainkey.outreach'). Strip nothing —
    they're already relative to getmark-eting.com."""
    return name


def main() -> int:
    out = [
        f"# mark-eting (Mark Eizema) — DNS records for {ROOT} (Hostinger, client account).",
        "# Generated from the live Resend API. Push via:",
        "#   py scripts/push-client-dns.py hostinger getmark-eting.com $HOSTINGER_API_TOKEN_MARK_ETING out/mark-eting-dns-records.txt",
        f"# NAME is relative to the {ROOT} zone root. Region us-east-1.",
        "",
    ]
    for d in DOMAINS:
        did = d["resend_domain_id"]
        sub = d["domain"].replace(f".{ROOT}", "")  # e.g. outreach
        r = httpx.get(f"https://api.resend.com/domains/{did}", headers=HEADERS, timeout=40)
        r.raise_for_status()
        data = r.json()
        out.append(f"# --- {d['domain']} (resend id {did}) ---")
        for rec in data.get("records", []):
            rtype = rec["type"]
            name = rel(rec["name"])
            val = rec["value"]
            if rtype == "MX":
                pr = rec.get("priority", 10)
                out.append(f"MX     {name:40s} {val} [priority {pr}]")
            else:
                out.append(f"{rtype:6s} {name:40s} {val}")
        # DMARC for this subdomain (Resend doesn't emit one)
        out.append(f"TXT    {'_dmarc.' + sub:40s} {DMARC}")
        out.append("")
        print(f"  {d['domain']}: {len(data.get('records', []))} records + dmarc")

    path = Path("out/mark-eting-dns-records.txt")
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"\nWrote {path} ({len(DOMAINS)} subdomains)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
