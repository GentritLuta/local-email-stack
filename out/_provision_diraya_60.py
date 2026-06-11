# -*- coding: utf-8 -*-
"""Create all 60 Diraya sending subdomains at Resend (us-east-1), capture each
one's DNS records (SPF/DKIM/DMARC), write resend_domain_id back into
profiles/diraya.json, and emit a per-root DNS export ready to publish on
ClouDNS / Spaceship.

Idempotent: if a subdomain already exists at Resend (same name), it reuses the
existing domain_id instead of erroring. Safe to re-run.

Run: py out/_provision_diraya_60.py
"""
import sys, os, json, time
from pathlib import Path

SEQ = Path(r"C:\Users\bernh\local-email-stack\sequences")
sys.path.insert(0, str(SEQ)); os.chdir(SEQ)
import httpx
import provision_subdomain as ps
from profile_lib import load_profile, save_profile

OUT = Path(r"C:\Users\bernh\local-email-stack\out")
REGION = "us-east-1"
# Use the NEW (g-luta) account key for Diraya provisioning.
_env = ps._load_env_file(SEQ / "hostinger.env")
key = _env.get("RESEND_NEW_ACCOUNT_API_KEY") or ps._resend_full_key()
assert key, "no Resend key"
print(f"using key ...{key[-6:]}")

H = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

# Pull existing Resend domains once (name -> id) for idempotency.
with httpx.Client(timeout=30) as c:
    r = c.get("https://api.resend.com/domains", headers=H)
    r.raise_for_status()
    existing = {d["name"]: d["id"] for d in r.json().get("data", [])}
print(f"existing resend domains: {len(existing)}")

profile = load_profile("diraya")
fd = profile["relay"]["from_domains"]
print(f"subdomains to provision: {len(fd)}")

records_by_root = {}   # root -> list of record dicts
created, reused, failed = 0, 0, 0

def norm(rec):
    return {
        "name": rec.get("name") or rec.get("record"),
        "type": rec.get("type") or rec.get("record_type"),
        "value": rec.get("value") or rec.get("content"),
        "ttl": rec.get("ttl", "Auto"),
        "priority": rec.get("priority"),
    }

with httpx.Client(timeout=30) as c:
    for entry in fd:
        sub = entry["domain"]
        root = sub.split(".", 1)[1]
        records_by_root.setdefault(root, [])
        rid = None; recs = []
        if sub in existing:
            rid = existing[sub]
            g = c.get(f"https://api.resend.com/domains/{rid}", headers=H)
            if g.status_code == 200:
                recs = g.json().get("records", [])
            reused += 1
        else:
            cr = c.post("https://api.resend.com/domains", headers=H,
                        json={"name": sub, "region": REGION})
            if cr.status_code in (200, 201):
                j = cr.json()
                rid = j.get("id"); recs = j.get("records", [])
                created += 1
            else:
                print(f"  FAIL {sub}: {cr.status_code} {cr.text[:120]}")
                failed += 1
                time.sleep(0.4)
                continue
        entry["resend_domain_id"] = rid or ""
        for rec in recs:
            n = norm(rec); n["_subdomain"] = sub
            records_by_root[root].append(n)
        print(f"  ok {sub:34} id={rid}  records={len(recs)}")
        time.sleep(0.4)  # stay under Resend rate limit

save_profile(profile)
print(f"\ncreated={created} reused={reused} failed={failed}")

# Write DNS export, one file per root domain.
exp_dir = OUT / "diraya-dns-export"
exp_dir.mkdir(exist_ok=True)
for root, recs in records_by_root.items():
    lines = [f"# DNS records to publish on {root}",
             f"# {len(recs)} records · publish at your DNS host (ClouDNS / Spaceship)",
             f"# Generated for Diraya 60-subdomain cold-email setup", ""]
    for r in recs:
        prio = f"  priority={r['priority']}" if r.get("priority") else ""
        lines.append(f"{r['type']:6} {r['name']}")
        lines.append(f"       -> {r['value']}{prio}  (ttl={r['ttl']})")
    (exp_dir / f"{root}.txt").write_text("\n".join(lines), encoding="utf-8")
    print(f"  wrote {exp_dir / (root + '.txt')}  ({len(recs)} records)")

# Also a single JSON for programmatic publishing later.
(exp_dir / "_all_records.json").write_text(
    json.dumps(records_by_root, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"  wrote {exp_dir / '_all_records.json'}")
print("\nDONE.")
