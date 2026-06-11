# -*- coding: utf-8 -*-
"""_provision_diraya_2more.py — stand up 2 more Diraya sending subdomains (10 -> 12),
fully end-to-end: create at Resend (new-account key), publish DNS to Spaceship
(additively), poll until verified, then stamp profiles/diraya.json.

Diraya domains live on Spaceship (not Hostinger), so the stock provision_subdomain.py
auto-DNS path can't publish them. This reuses the proven Spaceship DNS code from
out/_publish_diraya_dns.py + the Resend calls from sequences/provision_subdomain.py.

  py scripts/_provision_diraya_2more.py --dry   # show what it would do, no API writes
  py scripts/_provision_diraya_2more.py         # do it for real
"""
from __future__ import annotations
import argparse, json, sys, time, urllib.error, urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from profile_lib import load_profile, save_profile  # noqa

# The 2 new senders. Spread across two different roots for reputation diversity,
# matching the hello./team. naming already in use (these add a 3rd label each).
NEW = [
    {"subdomain": "reach.cleardiraya.com", "root": "cleardiraya.com",
     "localpart": "noah", "persona_slug": "noah-reach", "from_name": "Noah from Diraya",
     "full_name": "Noah Belkaid", "title": "AI Engineer, Diraya"},
    {"subdomain": "mail.dirayaget.com", "root": "dirayaget.com",
     "localpart": "leila", "persona_slug": "leila-mail", "from_name": "Leila from Diraya",
     "full_name": "Leila Mansour", "title": "ML Engineer, Diraya"},
]

env = {}
for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")

# Diraya's aureon-account subdomains are on RESEND_NEW_ACCOUNT_API_KEY (verified
# earlier). Prefer the diraya private key if set, else the new-account key.
priv = json.loads((REPO / "profiles" / "diraya.private.json").read_text(encoding="utf-8"))
RESEND_KEY = (priv.get("relay", {}).get("resend_api_key")
              or env.get("RESEND_NEW_ACCOUNT_API_KEY") or env.get("RESEND_FULL_ACCESS_API_KEY"))
SS_KEY, SS_SEC = env["SPACESHIP_API_KEY"], env["SPACESHIP_API_SECRET"]

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
RESEND_API = "https://api.resend.com"
SS_BASE = "https://spaceship.dev/api/v1"
SS_H = {"X-API-Key": SS_KEY, "X-API-Secret": SS_SEC,
        "Content-Type": "application/json", "User-Agent": UA}
TTL = 3600


# ─── Resend ──────────────────────────────────────────────────────────────────

def _resend(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{RESEND_API}{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {RESEND_KEY}",
                                          "Content-Type": "application/json", "User-Agent": UA})
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return e.code, {"error": e.read().decode()[:300]}


def resend_create(name: str) -> dict:
    st, j = _resend("POST", "/domains", {"name": name, "region": "us-east-1"})
    if st not in (200, 201):
        raise RuntimeError(f"create {name}: {st} {j}")
    return j


def resend_get(domain_id: str) -> dict:
    st, j = _resend("GET", f"/domains/{domain_id}")
    return j if st == 200 else {}


def resend_verify(domain_id: str) -> None:
    _resend("POST", f"/domains/{domain_id}/verify")


# ─── Spaceship DNS (additive, mirrors out/_publish_diraya_dns.py) ────────────

def to_ss(rec: dict) -> dict:
    """Resend record -> Spaceship record."""
    t = rec["type"]
    o = {"type": t, "name": rec["name"], "ttl": TTL}
    if t == "MX":
        o["exchange"] = rec.get("value") or rec.get("content")
        o["preference"] = int(rec.get("priority") or 10)
    else:
        o["value"] = rec.get("value") or rec.get("content")
    return o


def ss_get(domain: str) -> list:
    r = urllib.request.Request(f"{SS_BASE}/dns/records/{domain}?take=500&skip=0", headers=SS_H)
    return json.loads(urllib.request.urlopen(r, timeout=30).read()).get("items", [])


def ss_put(domain: str, items: list) -> tuple[int, str]:
    body = json.dumps({"force": True, "items": items}).encode()
    r = urllib.request.Request(f"{SS_BASE}/dns/records/{domain}", data=body, method="PUT", headers=SS_H)
    try:
        resp = urllib.request.urlopen(r, timeout=30)
        return resp.status, resp.read().decode()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]


def publish_dns(root: str, resend_records: list, dry: bool) -> str:
    new = [to_ss(r) for r in resend_records]
    existing = ss_get(root)

    def keyf(x): return (x["type"], x["name"], x.get("value") or x.get("exchange"))
    have = {keyf(e) for e in existing}
    missing = [n for n in new if keyf(n) not in have]
    if not missing:
        return f"{root}: all {len(new)} records already present — skip"
    if dry:
        return f"{root}: would ADD {len(missing)} records (have {len(existing)})"
    st, msg = ss_put(root, missing)          # additive: send only the new ones
    after = ss_get(root)
    return f"{root}: +{len(missing)} -> PUT {st} | now {len(after)} total"


# ─── profile patch ───────────────────────────────────────────────────────────

def fresh_domain_entry(subdomain: str, resend_id: str) -> dict:
    return {
        "domain": subdomain, "resend_domain_id": resend_id, "verified_at": None,
        "warmup": {"enabled": True, "current_day": 0, "started_at": None,
                   "ramp_curve": "snowball_v1", "max_daily_sends": 50,
                   "reputation": {"bounce_rate_7d": 0.0, "complaint_rate_7d": 0.0,
                                  "delivered_7d": 0, "last_check": None}}}


def make_persona(spec: dict, subdomain: str) -> dict:
    return {
        "slug": spec["persona_slug"],
        "from_name": spec["from_name"],
        "from_addr": f'{spec["localpart"]}@{subdomain}',
        "reply_to": "info@diraya.ca",
        "title": spec["title"],
        "voice": {"register": "founder-direct",
                  "quirks": ["short sentences", "concrete numbers", "no buzzwords"],
                  "avoid": ["marketing language", "exclamation marks", "emojis", "em-dashes"]},
        "signature": f'{spec["full_name"]}\n{spec["title"]}\ndiraya.ca',
        "full_name": spec["full_name"],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    prof = load_profile("diraya")
    have = {d["domain"].lower() for d in prof.get("relay", {}).get("from_domains", [])}
    print(f"diraya pool now: {len(have)} subdomains. Adding {len(NEW)}.\n")

    created_entries, created_personas = [], []
    for spec in NEW:
        sub = spec["subdomain"]
        if sub.lower() in have:
            print(f"· {sub}: already in profile — skip"); continue
        print(f"· {sub}")
        if args.dry:
            print(f"    [DRY] would create at Resend + publish DNS to {spec['root']}")
            continue
        created = resend_create(sub)
        rid = created.get("id")
        records = created.get("records") or []
        print(f"    Resend domain_id={rid}, {len(records)} DNS records")
        print("    " + publish_dns(spec["root"], records, dry=False))
        created_entries.append(fresh_domain_entry(sub, rid))
        created_personas.append(make_persona(spec, sub))
        time.sleep(1)

    if args.dry:
        print("\n[DRY] no changes written.")
        return 0

    if not created_entries:
        print("\nNothing new to add.")
        return 0

    # Trigger verification, poll up to ~10 min.
    print("\nTriggering Resend verification + polling...")
    ids = [e["resend_domain_id"] for e in created_entries]
    deadline = 600
    waited = 0
    for rid in ids:
        resend_verify(rid)
    while waited < deadline:
        statuses = {rid: resend_get(rid).get("status") for rid in ids}
        print(f"  [{waited:>3}s] {statuses}")
        if all(s == "verified" for s in statuses.values()):
            break
        time.sleep(30); waited += 30
        for rid, s in statuses.items():
            if s != "verified":
                resend_verify(rid)

    # Stamp profile (mark verified ones)
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    for e in created_entries:
        if resend_get(e["resend_domain_id"]).get("status") == "verified":
            e["verified_at"] = now
    prof["relay"]["from_domains"].extend(created_entries)
    prof["personas"].extend(created_personas)
    save_profile(prof)
    verified_n = sum(1 for e in created_entries if e["verified_at"])
    print(f"\nDONE. Added {len(created_entries)} subdomains "
          f"({verified_n} verified now), {len(created_personas)} personas. "
          f"Pool is now {len(prof['relay']['from_domains'])}.")
    if verified_n < len(created_entries):
        print("Note: some are still pending DNS propagation — re-run "
              "`py sequences/provision_subdomain.py verify diraya <sub>` later to stamp them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
