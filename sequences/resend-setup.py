"""resend-setup.py — automate Resend domain provisioning for a profile.

Calls Resend's API to:
  1. Add the profile's sending domain (or fetch existing)
  2. Return the DNS records you must paste into Cloudflare
  3. Poll Resend until the domain flips to 'verified' status
  4. Persist relay.domain_verified_at into the profile

Usage:
    py resend-setup.py add     <profile_slug>          # adds domain + prints DNS
    py resend-setup.py verify  <profile_slug> [--wait] # polls verification
    py resend-setup.py status  <profile_slug>          # one-shot status check

Requires RESEND_API_KEY set on the profile (Settings → Sender → paste key, then
this script reads it via profile_lib.load_profile).
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
import time

import httpx

from profile_lib import load_profile, save_profile

RESEND_API = "https://api.resend.com"


def _key(profile: dict) -> str:
    k = profile.get("relay", {}).get("resend_api_key", "").strip()
    if not k:
        sys.exit("profile has no relay.resend_api_key — set in Settings → Sender first")
    return k


def _client(profile: dict) -> httpx.Client:
    return httpx.Client(
        base_url=RESEND_API, timeout=30,
        headers={
            "Authorization": f"Bearer {_key(profile)}",
            "Content-Type":  "application/json",
        },
    )


def list_domains(profile: dict) -> list[dict]:
    with _client(profile) as c:
        r = c.get("/domains")
        r.raise_for_status()
        return r.json().get("data", [])


def find_domain(profile: dict, name: str) -> dict | None:
    for d in list_domains(profile):
        if d.get("name") == name:
            return d
    return None


def add_domain(profile: dict, name: str) -> dict:
    """Idempotent: returns existing if present, else creates."""
    existing = find_domain(profile, name)
    if existing:
        return existing
    with _client(profile) as c:
        r = c.post("/domains", json={"name": name})
        r.raise_for_status()
        return r.json()


def get_domain(profile: dict, domain_id: str) -> dict:
    with _client(profile) as c:
        r = c.get(f"/domains/{domain_id}")
        r.raise_for_status()
        return r.json()


def print_dns_records(domain: dict) -> None:
    """Pretty-print the records Resend expects you to add in Cloudflare."""
    name = domain.get("name") or "?"
    status = domain.get("status") or "?"
    print(f"\nDomain: {name}")
    print(f"Status: {status}")
    print(f"\nAdd these records in Cloudflare (Type, Name, Value, TTL):\n")
    records = domain.get("records") or []
    for r in records:
        rt = r.get("record") or r.get("type") or "?"
        n  = r.get("name") or "?"
        v  = r.get("value") or "?"
        ttl = r.get("ttl") or "Auto"
        prio = f" priority={r['priority']}" if r.get("priority") is not None else ""
        # Cloudflare advice: SPF/DKIM TXT can be on the apex of the subdomain;
        # MX must go on the subdomain root.
        print(f"  [{rt}] {n}")
        print(f"        value = {v}")
        print(f"        ttl   = {ttl}{prio}\n")


def status(profile: dict) -> dict | None:
    name = (profile.get("relay", {}).get("from_domains") or [None])[0]
    if not name:
        sys.exit("profile has no relay.from_domains")
    d = find_domain(profile, name)
    if not d:
        return None
    return d


def verify_loop(profile: dict, wait: bool) -> int:
    name = (profile.get("relay", {}).get("from_domains") or [None])[0]
    if not name:
        sys.exit("profile has no relay.from_domains")
    deadline = time.time() + 30 * 60  # 30 minutes max wait
    while True:
        d = find_domain(profile, name)
        if not d:
            print(f"domain {name} not in Resend yet — run `add` first")
            return 2
        st = d.get("status")
        print(f"  [{dt.datetime.now().strftime('%H:%M:%S')}] {name} → {st}")
        if st == "verified":
            profile.setdefault("relay", {})["domain_verified_at"] = dt.datetime.now().isoformat()
            save_profile(profile)
            print(f"\n✓ {name} verified. Profile updated.")
            return 0
        if not wait:
            return 1
        if time.time() > deadline:
            print("timed out waiting for verification — try again later")
            return 3
        time.sleep(20)


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("add", "verify", "status"):
        p = sub.add_parser(name)
        p.add_argument("slug")
        if name == "verify":
            p.add_argument("--wait", action="store_true",
                           help="poll until verified or timeout (30 min)")
    args = ap.parse_args()
    profile = load_profile(args.slug)

    if args.cmd == "add":
        name = (profile.get("relay", {}).get("from_domains") or [None])[0]
        if not name:
            sys.exit("set relay.from_domains[0] in the profile first")
        d = add_domain(profile, name)
        # Resend's /domains responses sometimes lack records; re-fetch by id
        if d.get("id") and not d.get("records"):
            d = get_domain(profile, d["id"])
        print_dns_records(d)
        return 0

    if args.cmd == "status":
        d = status(profile)
        if d is None:
            print("(not added in Resend yet)")
            return 2
        print_dns_records(d)
        return 0 if d.get("status") == "verified" else 1

    if args.cmd == "verify":
        return verify_loop(profile, wait=args.wait)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.HTTPStatusError as e:
        sys.stderr.write(f"Resend API error {e.response.status_code}: {e.response.text}\n")
        sys.exit(1)
