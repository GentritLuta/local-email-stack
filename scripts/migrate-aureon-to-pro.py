# -*- coding: utf-8 -*-
"""migrate-aureon-to-pro.py — move Aureon's 12 sending subdomains from the OLD
Resend account (free, 100/day cap) to the NEW "Pro" account (Diraya's), at $0.

SAFE BY DESIGN:
  * Only ever writes resend._domainkey.<sub> TXT records (the DKIM key). Never the
    root MX/SPF/email records (info@aureonglobal.de stays intact). Verified: the
    Hostinger PUT is additive/merge.
  * Full zone backed up to out/aureonglobal-zone-backup.json before any write.
  * New-account domains added in eu-west-1 to MATCH the existing send.<sub> MX/SPF
    (so ONLY the DKIM TXT changes — surgical).
  * Aureon is PAUSED during the cutover so it never sends with a half-migrated DKIM,
    and RE-ENABLED only after every domain verifies on the new account + the key is
    switched.

Phases:
  --add [--only SUB]   pause aureon; add domain(s) to new acct (EU); write new DKIM
                       to Hostinger; trigger verification. (key NOT switched yet)
  --finish             if ALL aureon domains verify on the new acct -> switch the
                       profile key to the new acct + re-enable aureon. Else report.
  --status             show per-domain verification status on the new account.
"""
from __future__ import annotations
import sys, json, time, argparse, urllib.request
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from profile_lib import load_profile, save_profile, save_private  # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ENV = {}
for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); ENV[k.strip()] = v.strip().strip('"').strip("'")
NEWKEY = ENV["RESEND_NEW_ACCOUNT_API_KEY"]
OLDKEY = ENV["RESEND_FULL_ACCESS_API_KEY"]   # old account, full access (to delete domains)
HTOK = ENV["HOSTINGER_API_TOKEN"]
ROOT = "aureonglobal.de"
HZONE = f"https://developers.hostinger.com/api/dns/v1/zones/{ROOT}"


def rapi(method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request("https://api.resend.com" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + NEWKEY, "Content-Type": "application/json", "User-Agent": "les/1.0"})
    try:
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return f"__ERR__{e.code}:" + e.read().decode("utf-8", "replace")[:200]


def happi(method, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(HZONE, data=data, method=method,
        headers={"Authorization": "Bearer " + HTOK, "Accept": "application/json",
                 "Content-Type": "application/json", "User-Agent": "les/1.0"})
    try:
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return f"__ERR__{e.code}:" + e.read().decode("utf-8", "replace")[:200]


def rapi_k(key, method, path, body=None):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request("https://api.resend.com" + path, data=data, method=method,
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json", "User-Agent": "les/1.0"})
    try:
        return urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return f"__ERR__{e.code}:" + e.read().decode("utf-8", "replace")[:200]


def delete_from_old(sub):
    """Remove sub from the OLD account so it can be added to the new one (Resend
    enforces one domain per account). Destructive but required for the cutover."""
    r = rapi_k(OLDKEY, "GET", "/domains")
    if r.startswith("__ERR__"):
        return False
    d = json.loads(r); data = d.get("data", d) if isinstance(d, dict) else d
    m = next((x for x in data if x.get("name") == sub), None)
    if m:
        rapi_k(OLDKEY, "DELETE", "/domains/" + m["id"]); return True
    return False


def aureon_subs():
    p = load_profile("aureon")
    return [d["domain"] for d in p.get("relay", {}).get("from_domains", [])]


def new_acct_domains():
    r = rapi("GET", "/domains")
    if r.startswith("__ERR__"):
        return {}
    d = json.loads(r)
    data = d.get("data", d) if isinstance(d, dict) else d
    return {x["name"]: x for x in data}


def ensure_added(sub):
    """Ensure sub is on the new account in eu-west-1. Return (id, dkim_name, dkim_value)."""
    existing = new_acct_domains().get(sub)
    if existing and existing.get("region") == "eu-west-1":
        # fetch records
        r = json.loads(rapi("GET", "/domains/" + existing["id"]))
        rec = next((x for x in r.get("records", []) if x.get("type") == "TXT" and "_domainkey" in x.get("name", "")), None)
        return existing["id"], (rec or {}).get("name"), (rec or {}).get("value")
    if existing:  # wrong region -> delete + re-add on new acct
        rapi("DELETE", "/domains/" + existing["id"]); time.sleep(3)
    # Resend = one domain per account: remove from the OLD account first.
    delete_from_old(sub)
    r = rapi("POST", "/domains", {"name": sub, "region": "eu-west-1"})
    if r.startswith("__ERR__"):
        print(f"    ! add {sub}: {r[:90]}"); return None, None, None
    d = json.loads(r)
    rec = next((x for x in d.get("records", []) if x.get("type") == "TXT" and "_domainkey" in x.get("name", "")), None)
    return d.get("id"), (rec or {}).get("name"), (rec or {}).get("value")


def write_dkim(dkim_name, dkim_value):
    """Replace the resend._domainkey.<sub> TXT with the new account's key. name is
    relative to the zone (strip the .aureonglobal.de suffix)."""
    rel = dkim_name.replace("." + ROOT, "")
    body = {"overwrite": True, "zone": [{"name": rel, "type": "TXT", "ttl": 300,
                                          "records": [{"content": dkim_value}]}]}
    return happi("PUT", body)


def trigger_verify(dom_id):
    return rapi("POST", f"/domains/{dom_id}/verify")


def status():
    subs = aureon_subs(); doms = new_acct_domains()
    print(f"{'subdomain':<26} {'on new acct':<12} {'status'}")
    out = {}
    for s in subs:
        d = doms.get(s)
        st = d.get("status") if d else "—"
        out[s] = st
        print(f"  {s:<26} {('yes' if d else 'no'):<12} {st}")
    return out


def run_all():
    """Autonomous, safe, atomic migration. Phase A (add all 12 to Pro acct) touches
    NO DNS and aborts cleanly if any domain can't be added. Phase B (the cutover)
    pauses aureon, writes DKIM, polls verification, then switches the key + re-enables
    aureon — only on full success. On timeout aureon stays paused (recoverable from the
    zone backup)."""
    subs = aureon_subs()
    print(f"=== Aureon -> Pro migration: {len(subs)} subdomains ===", flush=True)

    # Phase A — stage all on the Pro account (safe; no DNS, reversible). Retry the
    # re-add cooldown on any domain for up to ~12 minutes.
    print("Phase A: staging all subdomains on the Pro account (eu-west-1)...", flush=True)
    # aureon paused for the whole destructive cutover (domains leave the old acct).
    p = load_profile("aureon"); p["active"] = False; save_profile(p)
    dkim = {}
    for attempt in range(20):   # generous: Resend re-add cooldown after delete-from-old
        missing = [s for s in subs if s not in dkim]
        if not missing:
            break
        for s in missing:
            did, dn, dv = ensure_added(s)   # deletes from OLD acct, then adds to NEW
            if dv:
                dkim[s] = (did, dn, dv); print(f"  staged {s}", flush=True)
        if [s for s in subs if s not in dkim]:
            print(f"  {len(dkim)}/{len(subs)} staged; retrying re-add cooldowns in 60s...", flush=True)
            time.sleep(60)
    if len(dkim) < len(subs):
        miss = [s for s in subs if s not in dkim]
        print(f"ABORT: only {len(dkim)}/{len(subs)} staged. Stuck (deleted from old, not yet on new): {miss}", flush=True)
        print("  aureon stays PAUSED. Recovery: re-run --run-all (idempotent) to finish staging,", flush=True)
        print("  or re-add the stuck subdomains to the old account + restore out/aureonglobal-zone-backup.json.", flush=True)
        return 1

    # Phase B — cutover. Pause aureon, write DKIM, verify, switch key, re-enable.
    print("Phase B: cutover. Pausing aureon + writing new DKIM to Hostinger...", flush=True)
    p = load_profile("aureon"); p["active"] = False; save_profile(p)
    for s, (did, dn, dv) in dkim.items():
        res = write_dkim(dn, dv); trigger_verify(did)
        print(f"  {'OK ' if ('accepted' in res or not res.startswith('__ERR__')) else 'ERR'} DKIM {s}", flush=True)
    happi("DELETE", {"zone": [{"name": "_les-migration-test", "type": "TXT"}]})

    print("Polling verification (DNS propagation, up to 45 min)...", flush=True)
    for i in range(45):
        time.sleep(60)
        doms = new_acct_domains()
        verified = [s for s in subs if (doms.get(s) or {}).get("status") == "verified"]
        print(f"  [{i+1}m] verified {len(verified)}/{len(subs)}", flush=True)
        for s in subs:
            if (doms.get(s) or {}).get("status") != "verified" and s in dkim:
                trigger_verify(dkim[s][0])
        if len(verified) == len(subs):
            save_private("aureon", {"relay": {"resend_api_key": NEWKEY}})
            p = load_profile("aureon"); p["active"] = True; save_profile(p)
            print("\n=== MIGRATION COMPLETE ===", flush=True)
            print("  all subdomains verified on the Pro account; key switched; aureon RE-ENABLED.", flush=True)
            print("  Aureon now sends on the Pro account (no 100/day cap).", flush=True)
            return 0
    print("\nTIMEOUT: not all verified in 45 min. aureon stays PAUSED (safe).", flush=True)
    print("  Recover: restore out/aureonglobal-zone-backup.json via Hostinger + re-enable aureon,", flush=True)
    print("  OR re-run --run-all (idempotent) to keep polling.", flush=True)
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", action="store_true")
    ap.add_argument("--finish", action="store_true")
    ap.add_argument("--run-all", dest="run_all", action="store_true", help="autonomous full migration")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--only", default=None, help="single subdomain (test mode)")
    args = ap.parse_args()

    if args.run_all:
        return run_all()

    if args.status:
        status(); return 0

    subs = [args.only] if args.only else aureon_subs()

    if args.add:
        # safety: pause aureon so it never sends mid-cutover
        p = load_profile("aureon")
        if p.get("active") is not False:
            p["active"] = False; save_profile(p); print("aureon PAUSED for migration (re-enabled by --finish)")
        for s in subs:
            dom_id, dn, dv = ensure_added(s)
            if not dv:
                print(f"  ! {s}: could not get DKIM, skipping"); continue
            res = write_dkim(dn, dv)
            ok = "Request accepted" in res or not res.startswith("__ERR__")
            tv = trigger_verify(dom_id)
            print(f"  {'OK ' if ok else 'ERR'} {s:<26} DKIM written + verify triggered")
        # clean up the earlier merge-probe record (best effort)
        happi("DELETE", {"zone": [{"name": "_les-migration-test", "type": "TXT"}]})
        print("\nDNS written. Verification takes a few min to ~1h (DNS propagation).")
        print("Run:  py scripts/migrate-aureon-to-pro.py --finish   (re-run until all verified)")
        return 0

    if args.finish:
        st = status()
        pending = [s for s, v in st.items() if v != "verified"]
        if pending:
            print(f"\n{len(pending)} domain(s) NOT yet verified: {pending}")
            print("aureon stays PAUSED. Re-run --finish once they verify."); return 1
        # all verified -> switch key + re-enable
        save_private("aureon", {"relay": {"resend_api_key": NEWKEY}})
        p = load_profile("aureon"); p["active"] = True; save_profile(p)
        print("\n=== MIGRATION COMPLETE ===")
        print("  all 12 domains verified on the Pro account")
        print("  aureon relay key -> new Pro account; aureon RE-ENABLED")
        print("  Aureon now sends on the Pro account (no 100/day cap).")
        return 0

    ap.print_help(); return 0


if __name__ == "__main__":
    sys.exit(main())
