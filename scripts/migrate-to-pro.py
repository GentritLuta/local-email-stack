# -*- coding: utf-8 -*-
"""migrate-to-pro.py - move a profile's Resend sending domains from the OLD
full-access account to the PRO account, keeping DKIM identical so no DNS rework
is needed (SES Easy DKIM is domain-derived; recreating the same name re-issues
the same keypair).

Order is safe-by-construction:
  1. For each subdomain in the profile, CREATE it on the PRO account (idempotent:
     if it already exists on PRO, reuse it).
  2. Stamp the new PRO resend_domain_id into profiles/<slug>.json.
  3. Repoint profiles/<slug>.private.json relay.resend_api_key to the PRO key.
  4. Trigger verify on PRO (DNS already public, so it verifies fast).
  5. Only AFTER PRO creation succeeds, DELETE the domain from the OLD account
     (so we never leave the profile with no working domain).

Usage:
  py scripts/migrate-to-pro.py <slug> [--dry] [--no-delete-old]
"""
import json
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

REPO = Path(__file__).resolve().parent.parent
UA = {"User-Agent": "les-migrate/1.0"}
API = "https://api.resend.com"


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
OLD = ENV["RESEND_FULL_ACCESS_API_KEY"]


def list_domains(key: str) -> dict:
    r = httpx.get(f"{API}/domains", headers={"Authorization": f"Bearer {key}", **UA}, timeout=30)
    r.raise_for_status()
    return {d["name"]: d for d in r.json().get("data", [])}


def create_on_pro(name: str, region: str) -> dict | None:
    r = httpx.post(f"{API}/domains",
                   headers={"Authorization": f"Bearer {PRO}", "Content-Type": "application/json", **UA},
                   json={"name": name, "region": region}, timeout=30)
    if r.status_code in (200, 201):
        return r.json()
    print(f"    ! create {name} on PRO failed: {r.status_code} {r.text[:160]}")
    return None


def verify_on_pro(domain_id: str) -> None:
    httpx.post(f"{API}/domains/{domain_id}/verify",
               headers={"Authorization": f"Bearer {PRO}", **UA}, timeout=20)


def delete_on_old(domain_id: str, name: str) -> None:
    r = httpx.delete(f"{API}/domains/{domain_id}",
                     headers={"Authorization": f"Bearer {OLD}", **UA}, timeout=20)
    print(f"    deleted {name} from OLD: {r.status_code}")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    slug = sys.argv[1]
    dry = "--dry" in sys.argv
    delete_old = "--no-delete-old" not in sys.argv

    pf = REPO / "profiles" / f"{slug}.json"
    profile = json.loads(pf.read_text(encoding="utf-8"))
    region = (profile.get("relay") or {}).get("resend_region") or "eu-west-1"
    # Resend reported eu-west-1 for these; force eu-west-1 unless profile says otherwise.
    if region == "us-east-1":
        region = "eu-west-1"
    from_domains = (profile.get("relay") or {}).get("from_domains", [])

    pro_existing = list_domains(PRO)
    old_existing = list_domains(OLD)
    print(f"{slug}: {len(from_domains)} subdomains | region {region} "
          f"| PRO has {len(pro_existing)} | OLD has {len(old_existing)}")

    changed = False
    for d in from_domains:
        name = d.get("domain")
        if not name:
            continue
        old_id = d.get("resend_domain_id")
        if name in pro_existing:
            new_id = pro_existing[name]["id"]
            print(f"  = {name} already on PRO ({pro_existing[name]['status']}) id={new_id}")
            # if it somehow still exists on OLD too, clean that up
            if delete_old and not dry and name in old_existing:
                delete_on_old(old_existing[name]["id"], name)
        else:
            # Resend blocks the same domain name across accounts, so we MUST delete
            # it from OLD before creating on PRO. This opens a brief window where the
            # domain exists on neither account; acceptable for idle profiles, NOT for
            # a live high-volume sender (handle those at low-traffic hours).
            if dry:
                print(f"    [DRY] would DELETE {name} from OLD then CREATE on PRO ({region})")
                continue
            if name in old_existing:
                delete_on_old(old_existing[name]["id"], name)
                time.sleep(1)  # let Resend release the name
            print(f"  + creating {name} on PRO ...")
            created = create_on_pro(name, region)
            if not created:
                print(f"    ! PRO create failed for {name} AFTER OLD delete. Retrying once...")
                time.sleep(3)
                created = create_on_pro(name, region)
                if not created:
                    print(f"    !! {name} now on NEITHER account. Re-run to retry PRO create.")
                    continue
            new_id = created["id"]
            verify_on_pro(new_id)
            print(f"    created id={new_id}, verify triggered")
        # stamp new PRO id
        if not dry and d.get("resend_domain_id") != new_id:
            d["resend_domain_id"] = new_id
            changed = True

    if not dry:
        if changed:
            pf.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  stamped new PRO domain ids into {pf.name}")
        # repoint private key to PRO
        priv_path = REPO / "profiles" / f"{slug}.private.json"
        if priv_path.exists():
            priv = json.loads(priv_path.read_text(encoding="utf-8"))
            old_key = (priv.get("relay") or {}).get("resend_api_key", "")
            priv.setdefault("relay", {})["resend_api_key"] = PRO
            priv_path.write_text(json.dumps(priv, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  repointed {priv_path.name} key ...{old_key[-6:]} -> ...{PRO[-6:]} (PRO)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
