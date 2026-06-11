"""provision-energ.py — create ENER-G's 8 sending subdomains on Resend
(NEW account, eu-west-1), stamp resend_domain_id into profiles/energ.json,
and write a paste-ready DNS records file grouped by root domain.

Why a dedicated script (not provision_subdomain.py)? ENER-G sends under the
NEW Resend account (key in profiles/energ.private.json -> relay.resend_api_key),
not the RESEND_FULL_ACCESS_API_KEY that provision_subdomain.py uses. The domains
must be CREATED in the same account they SEND from, or verification never matches.
Also we have no DNS API token for the ener-g-beratung.* domains, so DNS is
manual-paste only.

After you paste the records into your DNS panel and they propagate (5-60 min),
verify each with:
    py scripts/provision-energ.py verify

Run:
    py scripts/provision-energ.py            # create all 8 + write DNS file
    py scripts/provision-energ.py verify     # poll Resend, stamp verified_at
"""
from __future__ import annotations

import json
import sys
import time
import datetime as dt
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from profile_lib import load_profile, save_profile  # noqa: E402

PROFILE_SLUG = "energ"
REGION = "eu-west-1"
RESEND_API = "https://api.resend.com"


def _resend_key() -> str:
    """ENER-G's sending key = the NEW account key in its private profile."""
    priv = json.loads((REPO / "profiles" / "energ.private.json").read_text(encoding="utf-8"))
    k = (priv.get("relay") or {}).get("resend_api_key", "").strip()
    if not k:
        sys.exit("no relay.resend_api_key in profiles/energ.private.json")
    return k


def _root_of(subdomain: str) -> str:
    # hello.ener-g-beratung.de -> ener-g-beratung.de
    return ".".join(subdomain.split(".")[-2:])


def resend_create_domain(key: str, name: str) -> dict:
    with httpx.Client(timeout=20) as c:
        r = c.post(f"{RESEND_API}/domains",
                   headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                   json={"name": name, "region": REGION})
        if r.status_code in (200, 201):
            return r.json()
        raise RuntimeError(f"create {name}: {r.status_code} {r.text[:300]}")


def resend_get_domain(key: str, domain_id: str) -> dict:
    with httpx.Client(timeout=15) as c:
        r = c.get(f"{RESEND_API}/domains/{domain_id}",
                  headers={"Authorization": f"Bearer {key}"})
        r.raise_for_status()
        return r.json()


def resend_verify(key: str, domain_id: str) -> None:
    with httpx.Client(timeout=20) as c:
        c.post(f"{RESEND_API}/domains/{domain_id}/verify",
               headers={"Authorization": f"Bearer {key}"})


def normalize_record(rec: dict) -> dict:
    content = rec.get("value") or rec.get("content") or ""
    if rec.get("type") == "MX" and not str(content).split(" ", 1)[0].isdigit():
        content = f"{rec.get('priority', 10)} {content}"
    return {"name": rec.get("name"), "type": rec.get("type"),
            "content": content, "_source": f"Resend {rec.get('record', '')}"}


def deterministic_records(subdomain: str) -> list[dict]:
    root = _root_of(subdomain)
    sub_label = subdomain.replace("." + root, "")
    return [
        {"name": sub_label, "type": "TXT",
         "content": "v=spf1 include:amazonses.com ~all", "_source": "SPF"},
        {"name": f"_dmarc.{sub_label}", "type": "TXT",
         "content": f"v=DMARC1; p=none; rua=mailto:dmarc@{root}; ruf=mailto:dmarc@{root}; pct=100; adkim=s; aspf=s",
         "_source": "DMARC"},
    ]


def cmd_create() -> int:
    key = _resend_key()
    profile = load_profile(PROFILE_SLUG)
    domains = profile["relay"]["from_domains"]

    all_records: list[tuple[str, dict]] = []
    created, skipped, failed = [], [], []

    print(f"=== Provisioning {len(domains)} ENER-G subdomains on Resend ({REGION}, NEW account) ===\n")
    for fd in domains:
        sub = fd["domain"]
        if fd.get("resend_domain_id"):
            print(f"  [skip] {sub} already has resend_domain_id")
            skipped.append(sub)
            continue
        try:
            print(f"  [create] {sub} ... ", end="", flush=True)
            resp = resend_create_domain(key, sub)
            fd["resend_domain_id"] = resp["id"]
            print(f"ok (id={resp['id'][:8]}..., {len(resp.get('records', []))} records)")
            for rec in resp.get("records", []):
                all_records.append((sub, normalize_record(rec)))
            for rec in deterministic_records(sub):
                all_records.append((sub, rec))
            created.append(sub)
            time.sleep(0.4)
        except Exception as e:
            print(f"FAIL: {e}")
            failed.append((sub, str(e)))

    save_profile(profile)
    print(f"\n-> Updated profiles/{PROFILE_SLUG}.json with {len(created)} resend_domain_id values.")

    out = REPO / "out" / "energ-dns-records.txt"
    out.parent.mkdir(exist_ok=True)
    by_root: dict[str, list[tuple[str, dict]]] = {}
    for sub, rec in all_records:
        by_root.setdefault(_root_of(sub), []).append((sub, rec))
    with open(out, "w", encoding="utf-8") as f:
        f.write("# ENER-G DNS records to publish. Add these in your DNS panel for each root domain.\n")
        f.write("# Format: TYPE  NAME  CONTENT   (NAME is relative to the root domain / zone root)\n")
        f.write("# After propagation (5-60 min): py scripts/provision-energ.py verify\n\n")
        for root in sorted(by_root):
            f.write(f"\n########## {root} ##########\n")
            cur = None
            for sub, rec in by_root[root]:
                if sub != cur:
                    f.write(f"\n## {sub}\n"); cur = sub
                f.write(f"  {rec['type']:6} {rec['name']:45} {rec['content']}\n")
                if rec.get("_source"):
                    f.write(f"         # {rec['_source']}\n")
    print(f"-> Wrote {len(all_records)} DNS records to {out}")

    print("\n=== SUMMARY ===")
    print(f"  created: {len(created)}  skipped: {len(skipped)}  failed: {len(failed)}")
    for s, e in failed:
        print(f"    ! {s}: {e[:120]}")
    if created:
        print(f"\nNext: paste records from {out} into your DNS panel, then run:")
        print("  py scripts/provision-energ.py verify")
    return 0 if not failed else 1


def cmd_verify() -> int:
    key = _resend_key()
    profile = load_profile(PROFILE_SLUG)
    now = dt.datetime.utcnow().isoformat() + "Z"
    verified, pending = [], []
    for fd in profile["relay"]["from_domains"]:
        rid = fd.get("resend_domain_id")
        sub = fd["domain"]
        if not rid:
            print(f"  [skip] {sub} not created yet")
            continue
        if fd.get("verified_at"):
            print(f"  [ok] {sub} already verified")
            verified.append(sub)
            continue
        try:
            resend_verify(key, rid)
            info = resend_get_domain(key, rid)
            status = (info.get("status") or "unknown").lower()
            print(f"  {sub}: {status}")
            if status in ("verified", "active"):
                fd["verified_at"] = now
                verified.append(sub)
            else:
                pending.append(sub)
        except Exception as e:
            print(f"  {sub}: ERROR {e}")
            pending.append(sub)
    save_profile(profile)
    print(f"\n  verified: {len(verified)}  pending: {len(pending)}")
    if pending:
        print("  (DNS may still be propagating - re-run verify in a few minutes)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "verify":
        sys.exit(cmd_verify())
    sys.exit(cmd_create())
