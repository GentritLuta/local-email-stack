"""safeguard-domain-check.py - daily verification that every send-domain
in Resend is still status=verified, with valid DKIM/SPF/DMARC.

If any domain reports a non-verified status or has DKIM/SPF/DMARC
problems, send an alert email to info@aureonglobal.de. This is the
catch-all that detects: Resend deactivation, DNS drift, expired DKIM
keys, or any other slow-burning domain-reputation problem the runtime
guards can't see.

Runs daily via LES-safeguard-domain-check (07:30 — earlier than any
sending so an alert lands before the day's outreach starts).
"""
from __future__ import annotations
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from safeguards import send_alert  # noqa: E402

HOST_ENV = REPO / "sequences" / "hostinger.env"
host = {}
for line in HOST_ENV.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        host[k.strip()] = v.strip()
RESEND_FULL = host["RESEND_FULL_ACCESS_API_KEY"]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "Chrome/123.0.0.0 Safari/537.36")
HEAD = {"Authorization": f"Bearer {RESEND_FULL}", "User-Agent": UA,
        "Accept": "application/json"}


def fetch_domains() -> list[dict]:
    req = urllib.request.Request("https://api.resend.com/domains", headers=HEAD)
    return json.loads(urllib.request.urlopen(req, timeout=20).read()).get("data", [])


def fetch_domain_detail(domain_id: str) -> dict:
    req = urllib.request.Request(f"https://api.resend.com/domains/{domain_id}", headers=HEAD)
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


# Profiles known to be legacy / paused / test-only — their domains are not
# part of the active send pool. Each domain we add here is documented with
# why it's excluded. To re-include later, just drop it from this set.
KNOWN_INACTIVE_PROFILES = {
    "northstar",          # initial test profile, mail.northstar-marketing.com
                          # was never finished verifying — no active campaigns
    "lk-advertising",     # currently paused; partners./connect.aureonglobal.de
                          # are verified but no active sequence
}


def active_pool_domains() -> set[str]:
    """Read every relay.from_domains entry from every NON-inactive profile.
    Only those are part of the live send pool we care about alerting on."""
    active: set[str] = set()
    for pf in (REPO / "profiles").glob("*.json"):
        if pf.stem in KNOWN_INACTIVE_PROFILES:
            continue
        try:
            d = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            continue
        for fd in d.get("relay", {}).get("from_domains", []) or []:
            if fd.get("domain"):
                active.add(fd["domain"])
    return active


def main() -> int:
    domains = fetch_domains()
    active = active_pool_domains()
    total = len(domains)
    domains = [d for d in domains if d["name"] in active]
    print(f"checking {len(domains)} active Resend domains "
          f"(skipped {total - len(domains)} legacy/inactive)...")
    bad: list[tuple[str, str]] = []
    soft_warn: list[tuple[str, str]] = []
    ok_count = 0
    for d in domains:
        name = d["name"]
        status = d["status"]
        if status != "verified":
            bad.append((name, f"status={status}"))
            print(f"  X {name:35s} status={status}")
            continue
        # Pull detail to check DKIM/SPF/DMARC record states
        try:
            det = fetch_domain_detail(d["id"])
        except urllib.error.HTTPError as e:
            print(f"  ? {name:35s} detail fetch failed: {e.code}")
            continue
        records = det.get("records", [])
        not_verified = [r for r in records if r.get("status") not in ("verified", None)]
        if not_verified:
            kinds = ",".join(r.get("type", "?") for r in not_verified)
            soft_warn.append((name, f"DNS records not verified: {kinds}"))
            print(f"  ! {name:35s} DNS records flagged: {kinds}")
        else:
            ok_count += 1
            print(f"  + {name}")

    print()
    print(f"summary: {ok_count} OK, {len(soft_warn)} warn, {len(bad)} bad")
    if bad or soft_warn:
        body_lines = [
            "Daily Resend domain-status check found issues.",
            "",
        ]
        if bad:
            body_lines.append("UNVERIFIED OR DEACTIVATED:")
            for name, why in bad:
                body_lines.append(f"  - {name}: {why}")
            body_lines.append("")
        if soft_warn:
            body_lines.append("DNS RECORD WARNINGS:")
            for name, why in soft_warn:
                body_lines.append(f"  - {name}: {why}")
            body_lines.append("")
        body_lines.append("Action: open the Resend dashboard "
                          "https://resend.com/domains and re-verify, OR check your "
                          "DNS provider (Hostinger) that DKIM/SPF/DMARC CNAMEs match "
                          "Resend's expected values.")
        send_alert(
            subject=f"{len(bad)} domain(s) unverified, {len(soft_warn)} DNS warning(s)",
            body_text="\n".join(body_lines),
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
