"""suppress-bounced.py — mark every address that has ALREADY BOUNCED as
unsendable, so it never re-enrolls and stops dragging the bounce rate up.

Port 25 is blocked on this box, so a live SMTP re-probe of the pool can't get
definitive 550s (it falls back to mx_verified). The reliable dead-address signal
we DO have is Resend's own bounce events, logged in send_log.bounced=true. This
flips those prospects to verified=false (daily-fill's eligible-pool query requires
verified=true, so they drop out of every future enrollment).

A dead mailbox is dead for every brand, so suppression is by email across all
profiles. Idempotent.

Usage:
  py scripts/suppress-bounced.py --dry
  py scripts/suppress-bounced.py
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV = REPO / "sequences" / "supabase.env"

# Shared/free mail providers are NEVER domain-suppressed: a few bounces among
# millions of unrelated mailboxes says nothing about the domain. Only custom
# (company) domains get domain-level suppression.
FREE_PROVIDERS = {
    "gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "yahoo.co.uk",
    "hotmail.com", "hotmail.co.uk", "outlook.com", "live.com", "msn.com",
    "aol.com", "icloud.com", "me.com", "mac.com", "mail.com", "protonmail.com",
    "proton.me", "zoho.com", "yandex.com", "gmx.com", "gmx.net", "gmx.de",
    "web.de", "t-online.de", "comcast.net", "verizon.net", "att.net",
    "sbcglobal.net", "bellsouth.net", "cox.net", "charter.net", "earthlink.net",
}


def env():
    e = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            e[k.strip()] = v.strip().strip('"').strip("'")
    return e


E = env()
URL = E.get("SUPABASE_URL")
KEY = E.get("SUPABASE_SERVICE_ROLE_KEY") or E.get("SUPABASE_SERVICE_KEY") or E.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def get(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H), timeout=40).read())


def patch(path, body):
    r = urllib.request.Request(f"{URL}/rest/v1/{path}", data=json.dumps(body).encode(),
                               headers={**H, "Prefer": "return=minimal"}, method="PATCH")
    return urllib.request.urlopen(r, timeout=40).status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--domain-threshold", type=int, default=3,
                    help="suppress a whole (non-provider) domain once it has this many distinct bounced addresses")
    args = ap.parse_args()

    # 1. All bounced sends.
    rows, off = [], 0
    while True:
        b = get(f"send_log?select=to_addr,from_addr,error&bounced=is.true&order=id&limit=1000&offset={off}")
        rows += b
        if len(b) < 1000:
            break
        off += 1000
    # Reason-aware: the Resend webhook Worker writes error="{type}/{subType}: msg".
    # A TRANSIENT bounce (greylist, full mailbox, temporary defer) is recoverable, so
    # we do NOT permanently suppress a lead whose bounces are ALL transient — the
    # sequence can retry. Legacy rows (error="bounced", no type) and Permanent bounces
    # are treated as dead, exactly as before.
    def _transient(e: str) -> bool:
        e = (e or "").lower()
        return e.startswith("transient") or "delivery delayed" in e or "delivery_delayed" in e
    errs_by_addr = defaultdict(list)
    for r in rows:
        a = (r.get("to_addr") or "").lower()
        if a:
            errs_by_addr[a].append(r.get("error") or "")
    bounced = sorted(a for a, errs in errs_by_addr.items() if not all(_transient(e) for e in errs))
    skipped_transient = sum(1 for errs in errs_by_addr.values() if errs and all(_transient(e) for e in errs))
    print(f"bounced sends: {len(rows)}  ->  distinct bounced addresses: {len(bounced)} "
          f"(skipped {skipped_transient} transient-only)")

    # Which brands the bounces came from (context only).
    def dom(a): return a.split("@", 1)[1].lower() if a and "@" in a else "?"
    def root(d): p = d.split("."); return ".".join(p[-2:]) if len(p) >= 2 else d
    by_brand = Counter(root(dom(r.get("from_addr") or "")) for r in rows)
    print("by sending root:", dict(by_brand.most_common()))

    if not bounced:
        print("nothing to suppress."); return

    # 2. ADDRESS-LEVEL: prospects whose exact email bounced = dead mailbox.
    addr = []
    for i in range(0, len(bounced), 50):
        chunk = bounced[i:i + 50]
        q = ",".join('"' + e.replace('"', '') + '"' for e in chunk)
        ps = get(f"prospects?select=id,email,profile_slug,verified&email=in.({q})")
        addr += [p for p in ps if p.get("verified")]
    print(f"address-level (dead mailbox): {len(addr)} verified prospect rows")

    # 2b. DOMAIN-LEVEL: a custom (company) domain with several distinct bounced
    # mailboxes is a dead/blocking server (e.g. theagencytexas.com). Port 25 is
    # blocked so we can't probe mailboxes — domain bounce concentration is the
    # signal. Drop EVERY still-verified address at such domains from the sendable
    # pool. Free/shared providers (gmail etc.) are excluded so we never nuke
    # unrelated mailboxes.
    bounced_by_domain = Counter(dom(a) for a in bounced)
    bad_domains = sorted(
        d for d, c in bounced_by_domain.items()
        if c >= args.domain_threshold and d not in FREE_PROVIDERS and d != "?"
    )
    print(f"domain-level: {len(bad_domains)} bad domain(s) (>= {args.domain_threshold} distinct bounces, non-provider):")
    for d in bad_domains:
        print(f"    {d} ({bounced_by_domain[d]} bounced)")
    addr_ids = {p["id"] for p in addr}
    domain, seen = [], set(addr_ids)
    for d in bad_domains:
        ps = get(f"prospects?select=id,email,profile_slug,verified&email=ilike.{urllib.parse.quote('*@' + d)}&verified=is.true")
        for p in ps:
            if p["id"] not in seen:
                seen.add(p["id"]); domain.append(p)
    print(f"domain-level (bad-domain risk): {len(domain)} additional verified prospect rows")
    bp = Counter(p["profile_slug"] for p in (addr + domain))
    print("  total by profile:", dict(bp.most_common()))

    if args.dry:
        print("[DRY] address-level -> verified=false + unsubscribed=true; "
              "domain-level -> verified=false (reversible, not opted-out)."); return

    # 3. Apply. Dead mailboxes are opted out; bad-domain-risk rows just leave the
    # sendable pool (verified=false) and can be re-verified later if the domain recovers.
    def _apply(rows, body, label):
        ids = [p["id"] for p in rows]; done = 0
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            if patch(f"prospects?id=in.({','.join(chunk)})", body) in (200, 204):
                done += len(chunk)
        print(f"  {label}: {done}")
        return done

    _apply(addr, {"verified": False, "verification_method": "bounced", "unsubscribed": True},
           "address-level dead mailboxes -> unsubscribed")
    _apply(domain, {"verified": False, "verification_method": "domain_bounce_risk"},
           "domain-level bad-domain rows -> dropped from pool (reversible)")


if __name__ == "__main__":
    main()
