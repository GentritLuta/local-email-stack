"""provision-atalsolidrocks.py — one-shot script that creates 12 name-based
sending subdomains for atalsolidrocks.io on Resend (eu-west-1), captures all
DNS records that need to be published, and saves them to a paste-ready file.

Why not provision_subdomain.py directly? We don't have a Hostinger API token
for the atalsolidrocks.io account yet, so DNS push will 403. This script
sidesteps the abort by skipping the Hostinger push and writing a
records.txt the user can paste in Hostinger's DNS Zone Editor UI by hand.

After the user adds the records and DNS propagates (~5-60 min), run
`provision_subdomain.py verify atalsolidrocks <subdomain>` per entry to
poll Resend and stamp verified_at.

Run:
    py scripts/provision-atalsolidrocks.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))

# Force UTF-8 on Windows console
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from profile_lib import load_profile, save_profile  # noqa: E402

NAMES = ["lukas", "anna", "tobias", "lea", "felix", "sara",
         "jonas", "mira", "niklas", "lena", "elias", "nora"]
ROOT_DOMAIN = "atalsolidrocks.io"
PROFILE_SLUG = "atalsolidrocks"
REGION = "eu-west-1"
RESEND_API = "https://api.resend.com"

env = {}
for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
RESEND_KEY = env.get("RESEND_FULL_ACCESS_API_KEY")
if not RESEND_KEY:
    sys.exit("no RESEND_FULL_ACCESS_API_KEY in sequences/hostinger.env")


def resend_create_domain(name: str) -> dict:
    with httpx.Client(timeout=20) as c:
        r = c.post(f"{RESEND_API}/domains",
                   headers={"Authorization": f"Bearer {RESEND_KEY}",
                            "Content-Type": "application/json"},
                   json={"name": name, "region": REGION})
        if r.status_code in (200, 201):
            return r.json()
        raise RuntimeError(f"Resend create {name} failed: {r.status_code} {r.text[:300]}")


def fresh_domain_entry(subdomain: str, resend_id: str) -> dict:
    return {
        "domain":           subdomain,
        "resend_domain_id": resend_id,
        "verified_at":      None,
        "warmup": {
            "enabled":         True,
            "current_day":     0,
            "started_at":      None,
            "ramp_curve":      "snowball_v1",
            "max_daily_sends": 50,
            "reputation":      {"bounce_rate_7d": 0.0, "complaint_rate_7d": 0.0, "delivered_7d": 0, "last_check": None},
        },
    }


def deterministic_records(subdomain: str) -> list[dict]:
    """SPF + DMARC records we always publish (independent of Resend's response).
    These mirror what provision_subdomain.py adds."""
    sub_label = subdomain.replace("." + ROOT_DOMAIN, "")
    return [
        {
            "name":    sub_label,
            "type":    "TXT",
            "content": "v=spf1 include:amazonses.com ~all",
            "_source": "deterministic SPF",
        },
        {
            "name":    f"_dmarc.{sub_label}",
            "type":    "TXT",
            "content": f"v=DMARC1; p=none; rua=mailto:dmarc@{ROOT_DOMAIN}; ruf=mailto:dmarc@{ROOT_DOMAIN}; pct=100; adkim=s; aspf=s",
            "_source": "deterministic DMARC",
        },
    ]


def normalize_resend_record(rec: dict) -> dict:
    """Convert a Resend record (name, type, value, [priority]) to our format."""
    content = rec.get("value") or rec.get("content") or ""
    if rec.get("type") == "MX" and not str(content).strip().split(" ", 1)[0].isdigit():
        content = f"{rec.get('priority', 10)} {content}"
    return {
        "name":    rec.get("name"),
        "type":    rec.get("type"),
        "content": content,
        "_source": f"Resend {rec.get('record')}",
    }


def main() -> int:
    profile = load_profile(PROFILE_SLUG)
    existing = {d["domain"] for d in profile.get("relay", {}).get("from_domains", [])}
    print(f"=== Provisioning {len(NAMES)} subdomains for {ROOT_DOMAIN} on Resend ({REGION}) ===\n")

    all_records: list[tuple[str, dict]] = []  # (subdomain, record)
    created: list[str] = []
    skipped: list[str] = []
    failed: list[tuple[str, str]] = []

    for name in NAMES:
        sub = f"{name}.{ROOT_DOMAIN}"
        if sub in existing:
            print(f"  [skip] {sub} already in profile")
            skipped.append(sub)
            continue
        try:
            print(f"  [create] {sub} ... ", end="", flush=True)
            resp = resend_create_domain(sub)
            domain_id = resp["id"]
            print(f"ok (id={domain_id[:8]}..., {len(resp.get('records', []))} records)")
            # Add to profile
            profile.setdefault("relay", {}).setdefault("from_domains", []).append(
                fresh_domain_entry(sub, domain_id)
            )
            # Collect records
            for rec in resp.get("records", []):
                all_records.append((sub, normalize_resend_record(rec)))
            for rec in deterministic_records(sub):
                all_records.append((sub, rec))
            created.append(sub)
            time.sleep(0.4)  # gentle on Resend
        except Exception as e:
            print(f"FAIL: {e}")
            failed.append((sub, str(e)))

    # Persist profile JSON
    save_profile(profile)
    print(f"\n→ Updated profiles/{PROFILE_SLUG}.json with {len(created)} new entries.")

    # Save DNS records to a single paste-ready file
    out = REPO / "out" / "atalsolidrocks-dns-records.txt"
    out.parent.mkdir(exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(f"# DNS records to publish on atalsolidrocks.io @ Hostinger\n")
        f.write(f"# Generated: 2026-05-21 by scripts/provision-atalsolidrocks.py\n")
        f.write(f"# {len(all_records)} records across {len(created)} subdomains.\n")
        f.write(f"# Paste into https://hpanel.hostinger.com/domain/atalsolidrocks.io → DNS Zone Editor\n")
        f.write(f"# After propagation (5-60 min), run:\n")
        f.write(f"#   for sub in {' '.join(NAMES)}; do py sequences/provision_subdomain.py verify atalsolidrocks $sub.atalsolidrocks.io; done\n")
        f.write(f"#\n# Format: TYPE  NAME  CONTENT\n\n")
        # Group by subdomain for readability
        by_sub: dict[str, list[dict]] = {}
        for sub, rec in all_records:
            by_sub.setdefault(sub, []).append(rec)
        for sub in sorted(by_sub.keys()):
            f.write(f"## {sub}\n")
            for rec in by_sub[sub]:
                src = rec.get("_source", "")
                f.write(f"  {rec['type']:6}  {rec['name']:50}  {rec['content']}\n")
                if src: f.write(f"          # source: {src}\n")
            f.write("\n")
    print(f"→ Wrote {len(all_records)} DNS records to {out}")

    print(f"\n=== SUMMARY ===")
    print(f"  created : {len(created)}")
    print(f"  skipped : {len(skipped)}")
    print(f"  failed  : {len(failed)}")
    if failed:
        for s, e in failed:
            print(f"    ! {s}: {e[:120]}")
    if created:
        print(f"\nNext step: paste the records from {out} into Hostinger's DNS Zone Editor.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
