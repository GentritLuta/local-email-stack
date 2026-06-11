# -*- coding: utf-8 -*-
"""_provision-algoalpha-cf.py — provision algoalpha's 12 tryalgoalpha.com sending
subdomains: create each in Resend, push its DKIM/SPF/MX records into the
tryalgoalpha.com Cloudflare zone, trigger verify. Idempotent: skips create if a
domain already exists, skips DNS records already present in the zone.

Uses RESEND_FULL_ACCESS_API_KEY + CF_API_TOKEN_ALGOALPHA + CF_ZONE_ID_ALGOALPHA
from sequences/hostinger.env. Stamps resend_domain_id / verified_at into the
profile + DB so the runner can later send from verified subdomains only.
"""
from __future__ import annotations
import sys, datetime as dt
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "sequences"))
from profile_lib import load_profile, save_profile  # noqa

REPO = Path(__file__).resolve().parent.parent
env = {}
for ln in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.split("=", 1); env[k.strip()] = v.strip()

RESEND = env["RESEND_FULL_ACCESS_API_KEY"]
CF_TOKEN = env["CF_API_TOKEN_ALGOALPHA"]
CF_ZONE = env["CF_ZONE_ID_ALGOALPHA"]
RH = {"Authorization": f"Bearer {RESEND}", "Content-Type": "application/json"}
CH = {"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"}


def resend_list():
    with httpx.Client(timeout=20) as c:
        return c.get("https://api.resend.com/domains", headers=RH).json().get("data", [])


def resend_create(name, region):
    with httpx.Client(timeout=20) as c:
        r = c.post("https://api.resend.com/domains", headers=RH,
                   json={"name": name, "region": region})
        r.raise_for_status()
        return r.json()


def resend_get(did):
    with httpx.Client(timeout=20) as c:
        return c.get(f"https://api.resend.com/domains/{did}", headers=RH).json()


def resend_verify(did):
    with httpx.Client(timeout=20) as c:
        c.post(f"https://api.resend.com/domains/{did}/verify", headers=RH)


def cf_existing_records():
    """Map of (type, name) -> id for the zone, to skip duplicates."""
    out = {}
    with httpx.Client(timeout=20) as c:
        page = 1
        while True:
            r = c.get(f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE}/dns_records?per_page=100&page={page}",
                      headers=CH).json()
            for rec in r.get("result", []):
                out[(rec["type"], rec["name"].rstrip("."))] = rec["id"]
            info = r.get("result_info", {})
            if info.get("page", 1) * info.get("per_page", 100) >= info.get("total_count", 0):
                break
            page += 1
    return out


def cf_create_record(rtype, name, content, ttl=3600, priority=None):
    body = {"type": rtype, "name": name, "content": content, "ttl": int(ttl) if str(ttl).isdigit() else 3600}
    if rtype == "MX":
        body["priority"] = priority if priority is not None else 10
    # Resend DKIM/SPF TXT and MX must NOT be proxied (DNS-only); CF defaults fine for TXT/MX.
    with httpx.Client(timeout=20) as c:
        r = c.post(f"https://api.cloudflare.com/client/v4/zones/{CF_ZONE}/dns_records",
                   headers=CH, json=body)
        return r.status_code, r.text[:200]


ZONE_ROOT = "tryalgoalpha.com"


def fqdn(record_name, domain):
    """Resend returns record names already relative to the ZONE ROOT
    (e.g. 'resend._domainkey.hello' for sending domain hello.tryalgoalpha.com).
    So the CF record name is {name}.{zone_root}, NOT {name}.{sending_domain}
    (that double-counts the subdomain -> hello.hello)."""
    rn = (record_name or "").rstrip(".")
    if rn.endswith(ZONE_ROOT):
        return rn
    return f"{rn}.{ZONE_ROOT}" if rn else ZONE_ROOT


def main():
    p = load_profile("algoalpha")
    region = p["relay"].get("resend_region", "us-east-1")
    existing = {d["name"]: d for d in resend_list()}
    cf_recs = cf_existing_records()
    changed = False

    for entry in p["relay"]["from_domains"]:
        name = entry["domain"]
        print(f"\n=== {name}")
        # 1. Resend create or reuse
        dom = existing.get(name)
        if not dom:
            dom = resend_create(name, region)
            print(f"  created in Resend ({region}): {dom.get('id')}")
        entry["resend_domain_id"] = dom["id"]
        # fetch records fresh
        full = resend_get(dom["id"])
        records = full.get("records", [])
        # 2. Push each record to Cloudflare if missing
        for rec in records:
            rtype = rec.get("type")
            rname = fqdn(rec.get("name"), name)
            content = rec.get("value", "")
            # CF wants TXT content quoted? API accepts raw; SPF/DKIM are plain strings.
            key = (rtype, rname)
            if key in cf_recs:
                print(f"  ~ {rtype} {rname} already in zone")
                continue
            sc, msg = cf_create_record(rtype, rname, content,
                                       ttl=rec.get("ttl", 3600), priority=rec.get("priority"))
            ok = sc in (200, 201)
            print(f"  {'+' if ok else '!'} {rtype} {rname} -> {sc}" + ("" if ok else f" {msg}"))
            if ok:
                cf_recs[key] = "new"
                changed = True
        # 3. Trigger verify (won't pass until DNS propagates)
        resend_verify(dom["id"])
        st = resend_get(dom["id"]).get("status")
        print(f"  resend status: {st}")
        if st in ("verified", "active"):
            entry["verified_at"] = dt.datetime.utcnow().isoformat() + "Z"
        changed = True

    if changed:
        save_profile(p)
        print("\nprofile saved with resend_domain_ids.")
    print("done. DNS pushed to Cloudflare; re-run to poll verify once propagated.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
