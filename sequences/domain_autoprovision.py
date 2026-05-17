"""domain_autoprovision.py — drain queued subdomains in Supabase profiles.

The Domains route in the desktop app appends rows to
  profiles.config.relay.from_domains[]
with verified_at=null and resend_domain_id=null. This worker scans for those
rows and walks each one through the full provisioning pipeline:

  1. POST /domains at Resend → get the DKIM record + domain_id
  2. Push DKIM + SPF + DMARC to Hostinger via the DNS API
  3. Trigger Resend verify
  4. Poll until Resend reports verified
  5. Stamp verified_at + resend_domain_id back into profile.config

Requires (in sequences/hostinger.env):
  RESEND_FULL_ACCESS_API_KEY = re_... (full access, NOT send-only)
  HOSTINGER_API_TOKEN        = ...    (hPanel → API)

Without them, the worker logs the missing creds, leaves the queue untouched,
and exits cleanly so it can keep retrying every scheduler tick.

CLI:
    py sequences/domain_autoprovision.py once             # one pass over every profile
    py sequences/domain_autoprovision.py once --slug X    # only profile X
    py sequences/domain_autoprovision.py once --limit 3   # cap how many domains we touch per tick

Schedule (every 10 min):
    schtasks /Create /TN "LES-domain-autoprovision" /SC MINUTE /MO 10 ^
      /TR "py C:\\Users\\bernh\\local-email-stack\\sequences\\domain_autoprovision.py once" /F
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from provision_subdomain import (  # noqa: E402
    _resend_full_key, _hostinger_token,
    resend_create_domain, resend_get_domain, resend_verify_domain,
    hostinger_push_records, _root_of,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE  = REPO_ROOT / "sequences" / "supabase.env"


def _supabase() -> tuple[str, str]:
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env["SUPABASE_URL"].rstrip("/"), env["SUPABASE_ANON_KEY"]


def _patch_profile(url: str, key: str, slug: str, config: dict) -> None:
    with httpx.Client(timeout=15,
                      headers={"apikey": key, "Authorization": f"Bearer {key}",
                               "Content-Type": "application/json"}) as c:
        r = c.patch(f"{url}/rest/v1/profiles?slug=eq.{slug}",
                    json={"config": config, "updated_at": dt.datetime.utcnow().isoformat() + "Z"})
        if r.status_code not in (200, 204):
            raise RuntimeError(f"profile patch {r.status_code}: {r.text[:200]}")


def _is_pending(d: dict) -> bool:
    return not d.get("verified_at")


def _process_one(profile: dict, d: dict, resend_key: str, host_token: str | None) -> tuple[bool, str]:
    """Walk one queued domain through provisioning. Mutates `d` in place when
    we make progress so the caller can persist it."""
    domain = d.get("domain", "").lower()
    if not domain: return False, "missing domain"

    # 1. Create at Resend if we haven't yet
    if not d.get("resend_domain_id"):
        print(f"  → Resend create {domain}")
        try:
            created = resend_create_domain(resend_key, domain)
        except Exception as e:
            return False, f"resend create failed: {e}"
        d["resend_domain_id"] = created.get("id")
        d["_pending_records"] = created.get("records") or []
        print(f"    domain_id = {d['resend_domain_id']} (records: {len(d['_pending_records'])})")

    # 2. Push DNS — only if we have a Hostinger token and there's a payload
    if host_token and d.get("_pending_records"):
        # Filter out SPF/DMARC if Resend already returned them; otherwise add ours.
        records = list(d["_pending_records"])
        # Normalize record shape to Hostinger's expectation
        normalized = []
        for r in records:
            name = r.get("name") or r.get("record") or "@"
            kind = r.get("type") or r.get("record_type")
            val  = r.get("value") or r.get("content")
            if not (kind and val): continue
            normalized.append({"name": name, "type": kind, "content": val})
        root = _root_of(domain)
        ok, msg = hostinger_push_records(host_token, root, normalized)
        print(f"  → DNS push to Hostinger: {msg}")
        if ok:
            d["_pending_records"] = []   # records published

    # 3. Trigger + poll verify
    try:
        print(f"  → Resend verify trigger for {domain}")
        resend_verify_domain(resend_key, d["resend_domain_id"])
    except Exception as e:
        print(f"    verify-trigger raised {e} — continuing to poll status")

    try:
        info = resend_get_domain(resend_key, d["resend_domain_id"])
    except Exception as e:
        return False, f"resend get-domain failed: {e}"
    status = (info.get("status") or "").lower()
    print(f"    resend status = {status}")
    if status in ("verified", "active"):
        d["verified_at"] = dt.datetime.utcnow().isoformat() + "Z"
        d.pop("_pending_records", None)
        return True, "verified"

    return False, f"still {status or 'pending'}"


def autoprovision_once(slug_filter: str | None = None, limit: int = 5) -> int:
    resend_key = _resend_full_key()
    host_token = _hostinger_token()
    if not resend_key:
        print("!  Missing RESEND_FULL_ACCESS_API_KEY in sequences/hostinger.env or sequences/resend.env.")
        print("   Queued domains stay queued until a full-access Resend key is added.")
        return 0
    if not host_token:
        print("⚠ Missing HOSTINGER_API_TOKEN — DNS records will not be auto-pushed.")
        print("  The worker will still create the Resend domain and attempt verify polls,")
        print("  but verification won't succeed until the operator manually adds DNS records")
        print("  shown via `py sequences/provision_subdomain.py records <profile> <domain>`.")

    url, key = _supabase()
    with httpx.Client(timeout=15,
                      headers={"apikey": key, "Authorization": f"Bearer {key}"}) as c:
        q = "/profiles?select=slug,config&active=eq.true"
        if slug_filter: q += f"&slug=eq.{slug_filter}"
        r = c.get(f"{url}/rest/v1{q}"); r.raise_for_status()
        profiles = r.json()

    examined = touched = verified = failed = 0
    for prof in profiles:
        cfg = prof.get("config") or {}
        pool = (cfg.get("relay") or {}).get("from_domains") or []
        pending = [d for d in pool if _is_pending(d)]
        if not pending:
            continue
        print(f"\n=== profile {prof['slug']}: {len(pending)} pending domain(s)")
        progress = False
        for d in pending[:limit]:
            examined += 1
            ok, msg = _process_one(prof, d, resend_key, host_token)
            touched += 1
            if ok:
                verified += 1; progress = True
            else:
                print(f"  - {d.get('domain')}: {msg}")
                # progress also flips true if we mutated the entry (e.g. got resend_domain_id)
                if d.get("resend_domain_id") or d.get("_pending_records"): progress = True
        if progress:
            try:
                _patch_profile(url, key, prof["slug"], cfg)
                print(f"  ✓ patched profile {prof['slug']}")
            except Exception as e:
                failed += 1; print(f"  ! patch failed: {e}")

    print(f"\n=== summary === examined={examined} touched={touched} verified={verified} failed={failed}")
    return 0 if failed == 0 else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("once")
    p.add_argument("--slug",  default=None)
    p.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()
    if args.cmd == "once":
        return autoprovision_once(args.slug, args.limit)
    return 0


if __name__ == "__main__":
    sys.exit(main())
