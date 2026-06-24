# -*- coding: utf-8 -*-
"""Provision a client up to the standard 12-subdomain kit on the PRO Resend
account, push DNS, trigger verify, and stamp the profile + personas.

Standard 12 prefixes (Aureon kit): mail outreach hi connect partners hello reach
news send team desk hub.

DNS providers:
  - hostinger <token>  : push via Hostinger DNS API (LK -> lk-advertising.site)
  - netlify   <token>  : push via Netlify DNS API   (ENER-G -> ener-g-beratung.de)

Idempotent: subdomains already on PRO are reused; existing profile entries kept.

Usage:
  py scripts/_provision-12-kit.py <slug> <root_domain> <hostinger|netlify> <dns_token>
"""
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

REPO = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "les-provision/1.0"}
API = "https://api.resend.com"
HOSTINGER_API = "https://developers.hostinger.com/api"
NETLIFY_API = "https://api.netlify.com/api/v1"

PREFIXES = ["mail", "outreach", "hi", "connect", "partners", "hello",
            "reach", "news", "send", "team", "desk", "hub"]

# Persona names to assign to the 12 senders (first names, brand-neutral).
PERSONA_NAMES = ["alex", "sam", "jordan", "casey", "riley", "morgan",
                 "taylor", "jamie", "drew", "quinn", "avery", "parker"]


def load_env(path: Path) -> dict:
    d = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


ENV = load_env(REPO / "sequences" / "hostinger.env")
PRO = ENV["RESEND_NEW_ACCOUNT_API_KEY"]


def resend_list() -> dict:
    r = httpx.get(f"{API}/domains", headers={"Authorization": f"Bearer {PRO}", **UA}, timeout=30)
    r.raise_for_status()
    return {d["name"]: d for d in r.json().get("data", [])}


def resend_create(name: str, region: str = "eu-west-1") -> dict | None:
    r = httpx.post(f"{API}/domains",
                   headers={"Authorization": f"Bearer {PRO}", "Content-Type": "application/json", **UA},
                   json={"name": name, "region": region}, timeout=30)
    if r.status_code in (200, 201):
        return r.json()
    print(f"    ! create {name}: {r.status_code} {r.text[:140]}")
    return None


def resend_get(domain_id: str) -> dict:
    r = httpx.get(f"{API}/domains/{domain_id}", headers={"Authorization": f"Bearer {PRO}", **UA}, timeout=20)
    return r.json() if r.status_code == 200 else {}


def resend_verify(domain_id: str) -> None:
    httpx.post(f"{API}/domains/{domain_id}/verify", headers={"Authorization": f"Bearer {PRO}", **UA}, timeout=20)


# ── DNS push ────────────────────────────────────────────────────────────────

def push_hostinger(root: str, token: str, records: list[dict]) -> None:
    zone = []
    for rec in records:
        content = rec.get("value", "")
        if rec["type"] == "MX" and not str(content).split(" ")[0].isdigit():
            content = f'{rec.get("priority", 10)} {content}'
        zone.append({"name": rec["name"], "type": rec["type"], "ttl": 3600,
                     "records": [{"content": content}]})
    r = httpx.put(f"{HOSTINGER_API}/dns/v1/zones/{root}",
                  headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", **UA},
                  json={"overwrite": False, "zone": zone}, timeout=40)
    print(f"    hostinger DNS push: {r.status_code}")


def _netlify_zone_id(root: str, token: str) -> str:
    r = httpx.get(f"{NETLIFY_API}/dns_zones", headers={"Authorization": f"Bearer {token}"}, timeout=40)
    for z in r.json():
        if z.get("name", "").lower() == root.lower():
            return z["id"]
    raise SystemExit(f"netlify: no zone for {root}")


def push_netlify(root: str, token: str, records: list[dict], zone_id: str) -> None:
    existing = httpx.get(f"{NETLIFY_API}/dns_zones/{zone_id}/dns_records",
                         headers={"Authorization": f"Bearer {token}"}, timeout=40).json()
    have = {(e.get("type"), e.get("hostname", "").rstrip(".")) for e in existing}
    for rec in records:
        fqdn = f'{rec["name"]}.{root}'
        if (rec["type"], fqdn) in have:
            continue
        body = {"type": rec["type"], "hostname": fqdn, "value": rec["value"], "ttl": 3600}
        if rec["type"] == "MX":
            body["priority"] = rec.get("priority", 10)
        httpx.post(f"{NETLIFY_API}/dns_zones/{zone_id}/dns_records",
                   headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                   json=body, timeout=40)


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    slug, root, provider, token = sys.argv[1:5]
    profile_path = REPO / "profiles" / f"{slug}.json"
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    relay = profile.setdefault("relay", {})
    from_domains = relay.setdefault("from_domains", [])
    existing_subs = {d["domain"] for d in from_domains}
    region = relay.get("resend_region") or "eu-west-1"
    if region == "us-east-1":
        region = "eu-west-1"

    pro = resend_list()
    zone_id = _netlify_zone_id(root, token) if provider == "netlify" else None

    targets = [f"{p}.{root}" for p in PREFIXES]
    for name in targets:
        if name in existing_subs:
            print(f"  = {name} already in profile")
            continue
        # Create on PRO (or reuse if already there)
        if name in pro:
            dom = resend_get(pro[name]["id"])
            print(f"  = {name} already on PRO, reusing")
        else:
            print(f"  + creating {name} on PRO")
            dom = resend_create(name, region)
            if not dom:
                continue
        records = dom.get("records", [])
        # Push DNS
        if provider == "hostinger":
            push_hostinger(root, token, records)
        else:
            push_netlify(root, token, records, zone_id)
        resend_verify(dom["id"])
        # Add to profile from_domains
        from_domains.append({
            "domain": name,
            "resend_domain_id": dom["id"],
            "verified_at": None,
            "warmup": {"enabled": True, "current_day": 0,
                       "started_at": __import__("datetime").date.today().isoformat(),
                       "ramp_curve": "snowball_v1", "max_daily_sends": 50,
                       "reputation": {"bounce_rate_7d": 0.0, "complaint_rate_7d": 0.0,
                                      "delivered_7d": 0, "last_check": None}},
        })
        existing_subs.add(name)
        time.sleep(0.5)

    # Ensure 12 personas, one per subdomain prefix.
    personas = profile.setdefault("personas", [])
    have_addrs = {p.get("from_addr", "") for p in personas}
    brand_name = profile.get("brand", {}).get("wordmark") or profile.get("name", slug)
    reply_to = (profile.get("brand", {}).get("legal", {}) or {}).get("contact_email", "")
    for i, prefix in enumerate(PREFIXES):
        addr = f"{PERSONA_NAMES[i]}@{prefix}.{root}"
        if addr in have_addrs:
            continue
        # only add persona if its subdomain is in the pool
        if f"{prefix}.{root}" not in existing_subs:
            continue
        nm = PERSONA_NAMES[i].capitalize()
        personas.append({
            "slug": PERSONA_NAMES[i],
            "from_name": f"{nm} from {brand_name}",
            "from_addr": addr,
            "reply_to": reply_to or addr,
            "title": "Partnerships",
            "voice": {"register": "direct and confident",
                      "quirks": ["short sentences", "concrete"], "avoid": ["hype"]},
            "signature": f"{nm}\n{brand_name}",
        })

    profile_path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n{slug}: now {len(from_domains)} subdomains, {len(personas)} personas")
    print("Run `py sequences/supabase_sync.py push` to sync to the DB, then verify.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
