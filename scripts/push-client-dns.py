#!/usr/bin/env python3
"""Push a client's Resend DNS records into their authoritative DNS zone.

Reads one of the out/*-dns-records.txt files (the format is:
    TYPE   name-relative-to-zone-root   content...
lines, '#' comments ignored) and PUTs them into the live zone via either
the Hostinger DNS API or the Netlify DNS API. Merge-only (never deletes).

Usage:
  py scripts/push-client-dns.py hostinger <root_domain> <token> <records.txt>
  py scripts/push-client-dns.py netlify   <root_domain> <token> <records.txt>

The tokens are passed on the CLI on purpose so they are not stored in the repo.
"""
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

HOSTINGER_API = "https://developers.hostinger.com/api"
NETLIFY_API = "https://api.netlify.com/api/v1"


def parse_records(txt_path: Path, root: str) -> list[dict]:
    """Parse the out/*-dns-records.txt format into normalized record dicts.

    Each data line: TYPE  NAME  CONTENT...   (CONTENT may contain spaces).
    MX lines carry a trailing '[priority N]'. NAME is relative to the zone root.
    """
    recs: list[dict] = []
    for line in txt_path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split(None, 2)
        if len(parts) < 3:
            continue
        rtype, name, content = parts[0], parts[1], parts[2]
        priority = 10
        if "[priority" in content:
            head, _, tail = content.partition("[priority")
            content = head.strip()
            priority = int(tail.strip().rstrip("]").strip())
        # MX content may carry the priority inline at the start ("10 host."); split it
        # out so providers that take priority as a separate field don't embed it in the
        # hostname (Netlify did exactly this — invalid MX, Resend stayed pending).
        if rtype == "MX":
            first, _, rest = content.partition(" ")
            if first.isdigit() and rest:
                priority = int(first)
                content = rest.strip()
        recs.append({"type": rtype, "name": name, "content": content, "priority": priority})
    return recs


# ─── Hostinger ──────────────────────────────────────────────────────────────

def push_hostinger(root: str, token: str, recs: list[dict]) -> None:
    def payload(r: dict) -> dict:
        content = r["content"]
        if r["type"] == "MX" and not content.split(" ")[0].isdigit():
            content = f'{r["priority"]} {content}'
        return {"name": r["name"], "type": r["type"], "ttl": 3600,
                "records": [{"content": content}]}

    body = {"overwrite": False, "zone": [payload(r) for r in recs]}
    url = f"{HOSTINGER_API}/dns/v1/zones/{root}"
    resp = httpx.put(url, headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json",
                                   "Accept": "application/json"},
                     json=body, timeout=40)
    print(f"Hostinger PUT {root}: {resp.status_code}")
    if resp.status_code not in (200, 201, 202, 204):
        print(resp.text[:600])
        sys.exit(1)
    print(f"  pushed {len(recs)} records (merge, no overwrite)")


# ─── Netlify ────────────────────────────────────────────────────────────────

def _netlify_zone_id(root: str, token: str) -> str:
    r = httpx.get(f"{NETLIFY_API}/dns_zones",
                  headers={"Authorization": f"Bearer {token}"}, timeout=40)
    r.raise_for_status()
    for z in r.json():
        if z.get("name", "").lower() == root.lower():
            return z["id"]
    raise SystemExit(f"Netlify: no DNS zone found for {root}. Zones: "
                     + ", ".join(z.get("name", "?") for z in r.json()))


def push_netlify(root: str, token: str, recs: list[dict]) -> None:
    zone_id = _netlify_zone_id(root, token)
    print(f"Netlify zone {root} -> {zone_id}")
    # Existing records, to skip exact dupes (Netlify has no merge PUT; POST each).
    existing = httpx.get(f"{NETLIFY_API}/dns_zones/{zone_id}/dns_records",
                         headers={"Authorization": f"Bearer {token}"}, timeout=40).json()
    have = {(e.get("type"), e.get("hostname", "").rstrip(".")) for e in existing}
    for r in recs:
        fqdn = f'{r["name"]}.{root}' if r["name"] not in ("@", root) else root
        if (r["type"], fqdn) in have:
            print(f"  skip (exists): {r['type']} {fqdn}")
            continue
        rec = {"type": r["type"], "hostname": fqdn, "value": r["content"], "ttl": 3600}
        if r["type"] == "MX":
            rec["priority"] = r["priority"]
        resp = httpx.post(f"{NETLIFY_API}/dns_zones/{zone_id}/dns_records",
                          headers={"Authorization": f"Bearer {token}",
                                   "Content-Type": "application/json"},
                          json=rec, timeout=40)
        ok = resp.status_code in (200, 201)
        print(f"  {'OK  ' if ok else 'FAIL'} {r['type']} {fqdn} -> {resp.status_code}")
        if not ok:
            print("       " + resp.text[:300])


def main() -> int:
    if len(sys.argv) != 5:
        print(__doc__)
        return 2
    provider, root, token, txt = sys.argv[1:5]
    recs = parse_records(Path(txt), root)
    print(f"Parsed {len(recs)} records from {txt} for {root}")
    if provider == "hostinger":
        push_hostinger(root, token, recs)
    elif provider == "netlify":
        push_netlify(root, token, recs)
    else:
        print(f"Unknown provider: {provider}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
