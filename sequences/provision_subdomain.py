"""provision_subdomain.py — add a new sending subdomain to a client profile.

Lifecycle of a new sending subdomain (e.g. outreach.aureonglobal.de):

  1. POST /domains at Resend with the subdomain → Resend returns a
     domain_id and a list of DNS records to publish (SPF + DKIM + DMARC).
     Requires a Resend `Full access` API key. Send-only keys reject this.
  2. Publish those records on the customer's DNS host (Hostinger here).
     Either via the Hostinger DNS API (when HOSTINGER_API_TOKEN is set in
     sequences/hostinger.env) or by printing them for manual paste.
  3. Click `Verify` in Resend dashboard → status flips to `verified` once
     DNS propagation finishes (typically minutes, up to an hour).
  4. This script polls Resend until the domain is marked verified, then
     stamps `verified_at` in profile.relay.from_domains[i].

This script encapsulates all of that. The autonomous path runs end-to-end
when both API tokens are present. Otherwise it falls back to print-and-paste
mode and waits for the operator to do the manual steps.

CLI:
    py sequences/provision_subdomain.py add <profile> <subdomain>          # POST to Resend, push DNS, write profile
    py sequences/provision_subdomain.py verify <profile> <subdomain>       # poll Resend until verified, stamp profile
    py sequences/provision_subdomain.py list <profile>                     # show pool + warmup days
    py sequences/provision_subdomain.py records <profile> <subdomain>      # re-print the DNS records you need to add
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_lib import REPO_ROOT, load_profile, save_profile, save_private  # noqa: E402

RESEND_API = "https://api.resend.com"
HOSTINGER_API = "https://developers.hostinger.com/api"


# ─── Env / credentials ─────────────────────────────────────────────────────

def _load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = dict(os.environ)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _resend_full_key() -> str | None:
    """Prefer a separate RESEND_FULL_ACCESS_API_KEY if the operator added one;
    otherwise try the existing `relay.resend_api_key` (works if they generated
    a full-access key as the profile's primary)."""
    env = _load_env_file(REPO_ROOT / "sequences" / "hostinger.env")
    env.update(_load_env_file(REPO_ROOT / "sequences" / "resend.env"))
    return env.get("RESEND_FULL_ACCESS_API_KEY") or env.get("RESEND_API_KEY") or None


def _hostinger_token() -> str | None:
    env = _load_env_file(REPO_ROOT / "sequences" / "hostinger.env")
    return env.get("HOSTINGER_API_TOKEN") or env.get("HOSTINGER_TOKEN")


# ─── Resend integration ────────────────────────────────────────────────────

def resend_create_domain(api_key: str, name: str, region: str = "eu-west-1") -> dict:
    with httpx.Client(timeout=20) as c:
        r = c.post(f"{RESEND_API}/domains",
                   headers={"Authorization": f"Bearer {api_key}",
                            "Content-Type": "application/json"},
                   json={"name": name, "region": region})
        if r.status_code in (200, 201):
            return r.json()
        raise RuntimeError(f"Resend create-domain failed: {r.status_code} {r.text[:200]}")


def resend_get_domain(api_key: str, domain_id: str) -> dict:
    with httpx.Client(timeout=15) as c:
        r = c.get(f"{RESEND_API}/domains/{domain_id}",
                  headers={"Authorization": f"Bearer {api_key}"})
        if r.status_code == 200:
            return r.json()
        raise RuntimeError(f"Resend get-domain failed: {r.status_code} {r.text[:200]}")


def resend_verify_domain(api_key: str, domain_id: str) -> dict:
    """Triggers Resend's verification pass."""
    with httpx.Client(timeout=20) as c:
        r = c.post(f"{RESEND_API}/domains/{domain_id}/verify",
                   headers={"Authorization": f"Bearer {api_key}"})
        if r.status_code in (200, 202):
            return r.json() if r.text else {}
        raise RuntimeError(f"Resend verify failed: {r.status_code} {r.text[:200]}")


# ─── Hostinger DNS integration (optional / best-effort) ────────────────────

def hostinger_push_records(token: str, root_domain: str, records: list[dict]) -> tuple[bool, str]:
    """Push DKIM / SPF / DMARC records via the Hostinger DNS REST endpoint.
    Returns (ok, message).

    Endpoint discovered 2026-05-17 by direct probing — the actual working path
    is PUT /api/dns/v1/zones/{domain} (not /domains/v1/portfolio/.../dns/records
    as the older Hostinger docs suggest). With overwrite=false the API merges
    new records into the existing zone without deleting anything, which is
    what we want for autoprovision."""
    url = f"{HOSTINGER_API}/dns/v1/zones/{root_domain}"
    body = {"overwrite": False, "zone": [_record_payload(r) for r in records]}
    try:
        with httpx.Client(timeout=30) as c:
            r = c.put(url,
                      headers={"Authorization": f"Bearer {token}",
                               "Content-Type": "application/json",
                               "Accept": "application/json"},
                      json=body)
        if r.status_code in (200, 201, 202, 204):
            return True, f"DNS push ok ({r.status_code})"
        return False, f"DNS push failed: {r.status_code} {r.text[:300]}"
    except Exception as e:
        return False, f"DNS push exception: {e}"


def _record_payload(rec: dict) -> dict:
    return {"name":  rec.get("name", "@"),
            "type":  rec.get("type"),
            "ttl":   rec.get("ttl", 3600),
            "records": [{"content": rec.get("content") or rec.get("value")}]}


def _root_of(subdomain: str) -> str:
    """outreach.aureonglobal.de → aureonglobal.de"""
    parts = subdomain.split(".")
    return ".".join(parts[-2:]) if len(parts) >= 2 else subdomain


# ─── Profile patching ──────────────────────────────────────────────────────

def _ensure_domains_list(profile: dict) -> list[dict]:
    relay = profile.setdefault("relay", {})
    relay.setdefault("from_domains", [])
    return relay["from_domains"]


def _find_entry(profile: dict, subdomain: str) -> dict | None:
    for d in (profile.get("relay") or {}).get("from_domains", []):
        if d.get("domain", "").lower() == subdomain.lower():
            return d
    return None


def _fresh_domain_entry(subdomain: str, resend_id: str | None = None) -> dict:
    return {
        "domain":           subdomain,
        "resend_domain_id": resend_id,
        "verified_at":      None,
        "warmup": {
            "enabled":         True,
            "current_day":     0,
            "started_at":      None,
            "ramp_curve":      "snowball_v1",
            "max_daily_sends": 90,
            "reputation":      {"bounce_rate_7d": 0.0, "complaint_rate_7d": 0.0, "delivered_7d": 0, "last_check": None},
        },
    }


# ─── Commands ──────────────────────────────────────────────────────────────

def cmd_add(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    if _find_entry(profile, args.subdomain):
        print(f"!  {args.subdomain} already in profile pool — use `verify` to check status, or `records` to re-print DNS")
        return 1

    full_key = _resend_full_key()
    records: list[dict] = []
    resend_id: str | None = None

    if full_key:
        print(f"→ Resend: creating domain {args.subdomain}")
        try:
            created = resend_create_domain(full_key, args.subdomain)
            resend_id = created.get("id")
            records   = created.get("records") or []
            print(f"  resend domain_id = {resend_id}, records returned: {len(records)}")
        except Exception as e:
            print(f"!  Resend create-domain failed: {e}")
            print("   Fall back: add the domain manually at https://resend.com/domains/add and re-run with --resend-id <id>")
            if not args.force: return 2
    elif args.resend_id:
        resend_id = args.resend_id
        print(f"→ Skipping Resend POST (no full-access key). Using supplied resend-id={resend_id}.")
        print(f"   You'll need to paste the DKIM record from the Resend UI when prompted.")
    else:
        print("!  No RESEND_FULL_ACCESS_API_KEY in sequences/hostinger.env (or sequences/resend.env).")
        print("   Either add a Full Access Resend key OR add the domain manually at")
        print(f"   https://resend.com/domains/add, then re-run with `--resend-id <id> --dkim-cname <value>`.")
        if not args.force: return 2

    # SPF + DMARC are deterministic and don't depend on Resend's response.
    root = _root_of(args.subdomain)
    sub_label = args.subdomain.replace("." + root, "")
    spf_record = {
        "name":    sub_label,
        "type":    "TXT",
        "content": "v=spf1 include:amazonses.com ~all",
    }
    dmarc_record = {
        "name":    f"_dmarc.{sub_label}",
        "type":    "TXT",
        "content": f"v=DMARC1; p=none; rua=mailto:dmarc@{root}; ruf=mailto:dmarc@{root}; pct=100; adkim=s; aspf=s",
    }
    if not records:
        records.append(spf_record)
        records.append(dmarc_record)
        if args.dkim_cname:
            records.append({
                "name":    f"resend._domainkey.{sub_label}",
                "type":    "CNAME",
                "content": args.dkim_cname,
            })

    # Push to Hostinger (or print)
    token = _hostinger_token()
    if token:
        ok, msg = hostinger_push_records(token, root, records)
        print(f"→ Hostinger DNS push: {msg}")
        if not ok and not args.force:
            print("   Aborting — set HOSTINGER_API_TOKEN in sequences/hostinger.env or use `records` command to copy manually.")
            return 3
    else:
        print("→ No HOSTINGER_API_TOKEN found. Records to add manually at https://hpanel.hostinger.com → Domains → DNS:")
        _print_records_table(records)

    # Update profile
    _ensure_domains_list(profile)
    entry = _fresh_domain_entry(args.subdomain, resend_id)
    profile["relay"]["from_domains"].append(entry)
    save_profile(profile)
    print(f"\n✓ Added {args.subdomain} to profile {args.profile}.")
    print(f"  Now wait for DNS to propagate (5–60 min), then run:")
    print(f"      py sequences/provision_subdomain.py verify {args.profile} {args.subdomain}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    entry = _find_entry(profile, args.subdomain)
    if not entry:
        sys.exit(f"{args.subdomain} not found in profile {args.profile}")

    full_key = _resend_full_key()
    if not full_key:
        print("!  No RESEND_FULL_ACCESS_API_KEY — can't poll Resend automatically.")
        print("   Click `Verify` in the Resend dashboard for this domain; once it shows 'verified', re-run with `--manual`.")
        if args.manual:
            entry["verified_at"] = dt.datetime.utcnow().isoformat() + "Z"
            save_profile(profile)
            print(f"\n✓ Marked {args.subdomain} as verified (manual stamp).")
            return 0
        return 2

    rid = entry.get("resend_domain_id")
    if not rid:
        sys.exit(f"profile entry for {args.subdomain} has no resend_domain_id — can't poll")

    # Trigger a verify, then poll up to N times
    print(f"→ Resend: triggering verify for {args.subdomain} ({rid})")
    try: resend_verify_domain(full_key, rid)
    except Exception as e: print(f"  (verify trigger raised {e} — continuing to poll)")

    deadline = time.time() + 60 * 30  # 30 min
    while time.time() < deadline:
        info = resend_get_domain(full_key, rid)
        status = info.get("status") or "unknown"
        print(f"  resend status: {status}")
        if status.lower() in ("verified", "active"):
            entry["verified_at"] = dt.datetime.utcnow().isoformat() + "Z"
            save_profile(profile)
            print(f"\n✓ Verified. {args.subdomain} is now part of the warmup pool starting day 0.")
            return 0
        time.sleep(30)
    print("!  Timed out after 30 minutes. Run this command again later — DNS can take a bit.")
    return 4


def cmd_list(args: argparse.Namespace) -> int:
    profile = load_profile(args.profile)
    rows = (profile.get("relay") or {}).get("from_domains", [])
    if not rows:
        print(f"{args.profile} has no domains in pool.")
        return 0
    print(f"\n=== {profile.get('name', args.profile)}: sending domain pool ===")
    print(f"{'domain':40} {'verified':10} {'day':>4} {'ceil':>5} {'resend_id'}")
    for d in rows:
        w = d.get("warmup") or {}
        verified = (d.get("verified_at") or "")[:10] or "—"
        rid = (d.get("resend_domain_id") or "—")[:36]
        print(f"{d.get('domain',''):40} {verified:10} {w.get('current_day', 0):>4} {w.get('max_daily_sends', 0):>5} {rid}")
    return 0


def cmd_records(args: argparse.Namespace) -> int:
    """Just print the DNS records for a known subdomain entry — handy when DNS
    drift means the operator needs to re-paste them."""
    profile = load_profile(args.profile)
    entry = _find_entry(profile, args.subdomain)
    if not entry:
        sys.exit(f"{args.subdomain} not found in profile {args.profile}")
    full_key = _resend_full_key()
    rid = entry.get("resend_domain_id")
    if full_key and rid:
        info = resend_get_domain(full_key, rid)
        records = info.get("records") or []
        if records:
            _print_records_table([_normalize(r) for r in records])
            return 0
    # Best-effort defaults
    root = _root_of(args.subdomain)
    sub_label = args.subdomain.replace("." + root, "")
    _print_records_table([
        {"name": sub_label,             "type": "TXT", "content": "v=spf1 include:amazonses.com ~all"},
        {"name": f"_dmarc.{sub_label}", "type": "TXT", "content": f"v=DMARC1; p=none; rua=mailto:dmarc@{root}; pct=100"},
        {"name": f"resend._domainkey.{sub_label}", "type": "CNAME", "content": "(get DKIM target from Resend dashboard)"},
    ])
    return 0


def _normalize(rec: dict) -> dict:
    return {"name":    rec.get("name") or rec.get("record"),
            "type":    rec.get("type") or rec.get("record_type"),
            "content": rec.get("value") or rec.get("content"),
            "ttl":     rec.get("ttl", 3600)}


def _print_records_table(records: list[dict]) -> None:
    print(f"\n{'name':40} {'type':6} content")
    print("-" * 100)
    for r in records:
        print(f"{r.get('name',''):40} {r.get('type',''):6} {r.get('content','')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_add = sub.add_parser("add", help="add a new subdomain to a profile + push DNS + register at Resend")
    p_add.add_argument("profile")
    p_add.add_argument("subdomain", help="e.g. outreach.aureonglobal.de")
    p_add.add_argument("--resend-id",   default=None, help="paste a domain_id if you added the domain manually in Resend")
    p_add.add_argument("--dkim-cname",  default=None, help="paste the DKIM CNAME target if Resend gave you one manually")
    p_add.add_argument("--force",       action="store_true", help="continue even if Resend or DNS push fails")

    p_v = sub.add_parser("verify", help="poll Resend until the domain is verified, then stamp profile.verified_at")
    p_v.add_argument("profile")
    p_v.add_argument("subdomain")
    p_v.add_argument("--manual", action="store_true", help="bypass the Resend poll and stamp verified_at locally")

    p_l = sub.add_parser("list", help="print every domain in this profile's pool")
    p_l.add_argument("profile")

    p_r = sub.add_parser("records", help="print the DNS records to add for a subdomain entry")
    p_r.add_argument("profile")
    p_r.add_argument("subdomain")

    args = ap.parse_args()
    if   args.cmd == "add":     return cmd_add(args)
    elif args.cmd == "verify":  return cmd_verify(args)
    elif args.cmd == "list":    return cmd_list(args)
    elif args.cmd == "records": return cmd_records(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
