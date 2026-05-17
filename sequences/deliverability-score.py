"""deliverability-score.py — preflight scorecard for a profile's sending domain.

Checks every infrastructure-side knob that affects inbox placement and
prints a 0–100 score with concrete next steps for whatever's missing.

Usage:
    py deliverability-score.py <profile_slug>
"""

from __future__ import annotations

import argparse
import socket
import sys
from dataclasses import dataclass
from typing import Optional

try:
    import dns.resolver
    HAVE_DNS = True
except ImportError:
    HAVE_DNS = False

from profile_lib import load_profile, current_warmup_day


# Each check is worth a fixed share of the 100-point score.
WEIGHTS = {
    "sender_domain_resolves": 5,
    "spf_present":            15,
    "spf_authorizes_resend":  15,
    "dkim_present":           20,
    "dmarc_present":          10,
    "dmarc_strict":            5,
    "mx_present":              5,
    "warmup_active":          10,
    "warmup_mature":          10,   # >= day 30
    "reputation_clean":        5,
}
MAX = sum(WEIGHTS.values())


@dataclass
class CheckResult:
    name: str
    weight: int
    earned: int
    detail: str
    fix: Optional[str] = None


def _resolve(name: str, rtype: str) -> list[str]:
    if not HAVE_DNS:
        return []
    try:
        ans = dns.resolver.resolve(name, rtype)
        if rtype == "TXT":
            return [b"".join(r.strings).decode("utf-8", "ignore") for r in ans]
        if rtype == "MX":
            return [f"{r.preference} {str(r.exchange).rstrip('.')}" for r in ans]
        if rtype == "A":
            return [str(r) for r in ans]
        return [str(r) for r in ans]
    except Exception:
        return []


def check_sender_domain_resolves(domain: str) -> CheckResult:
    a   = _resolve(domain, "A")
    mx  = _resolve(domain, "MX")
    if a or mx:
        return CheckResult("Sender domain resolves", WEIGHTS["sender_domain_resolves"], WEIGHTS["sender_domain_resolves"],
                           f"A={a or '(none)'}  MX={mx or '(none)'}")
    return CheckResult("Sender domain resolves", WEIGHTS["sender_domain_resolves"], 0,
                       "no A or MX record",
                       fix=f"Add an A record (placeholder is fine, can point to 127.0.0.1) or MX for {domain}")


def check_spf(domain: str) -> tuple[CheckResult, CheckResult]:
    txt = _resolve(domain, "TXT")
    spf = next((t for t in txt if t.startswith("v=spf1")), None)
    if not spf:
        return (
            CheckResult("SPF present", WEIGHTS["spf_present"], 0,
                        "no v=spf1 TXT record",
                        fix=f"Add TXT {domain} → \"v=spf1 include:amazonses.com ~all\" (Resend uses Amazon SES under the hood)"),
            CheckResult("SPF authorizes Resend", WEIGHTS["spf_authorizes_resend"], 0,
                        "n/a (no SPF)"),
        )
    earned_pres = WEIGHTS["spf_present"]
    authorizes = ("amazonses.com" in spf) or ("resend.com" in spf) or ("_spf.resend.com" in spf)
    return (
        CheckResult("SPF present", WEIGHTS["spf_present"], earned_pres, spf[:120]),
        CheckResult("SPF authorizes Resend", WEIGHTS["spf_authorizes_resend"],
                    WEIGHTS["spf_authorizes_resend"] if authorizes else 0,
                    "includes Resend (amazonses.com)" if authorizes else "SPF exists but doesn't authorize Resend",
                    fix=None if authorizes else f"Update SPF for {domain} to include amazonses.com"),
    )


def check_dkim(domain: str, selector: str) -> CheckResult:
    # Resend uses `resend._domainkey.<domain>` by default
    dkim_name = f"{selector}._domainkey.{domain}"
    txt = _resolve(dkim_name, "TXT")
    cname = _resolve(dkim_name, "CNAME")
    if txt and any("p=" in t for t in txt):
        return CheckResult("DKIM record present", WEIGHTS["dkim_present"], WEIGHTS["dkim_present"],
                           f"TXT at {dkim_name} contains a public key")
    if cname:
        return CheckResult("DKIM record present", WEIGHTS["dkim_present"], WEIGHTS["dkim_present"],
                           f"CNAME at {dkim_name} → {cname[0]}")
    return CheckResult("DKIM record present", WEIGHTS["dkim_present"], 0,
                       f"no record at {dkim_name}",
                       fix=f"Add Resend's DKIM record at {dkim_name} (from Resend dashboard → Domains)")


def check_dmarc(domain: str) -> tuple[CheckResult, CheckResult]:
    txt = _resolve(f"_dmarc.{domain}", "TXT")
    dmarc = next((t for t in txt if t.startswith("v=DMARC1")), None)
    if not dmarc:
        return (
            CheckResult("DMARC record present", WEIGHTS["dmarc_present"], 0,
                        "no _dmarc TXT record",
                        fix=f"Add TXT _dmarc.{domain} → \"v=DMARC1; p=none; rua=mailto:dmarc@{domain}; pct=100; adkim=s; aspf=s\"  (start with p=none for monitoring, promote to p=quarantine after 30 days)"),
            CheckResult("DMARC policy strict (quarantine/reject)", WEIGHTS["dmarc_strict"], 0, "n/a (no DMARC)"),
        )
    is_strict = "p=quarantine" in dmarc or "p=reject" in dmarc
    return (
        CheckResult("DMARC record present", WEIGHTS["dmarc_present"], WEIGHTS["dmarc_present"], dmarc[:120]),
        CheckResult("DMARC policy strict (quarantine/reject)", WEIGHTS["dmarc_strict"],
                    WEIGHTS["dmarc_strict"] if is_strict else 0,
                    "p=quarantine/reject" if is_strict else "p=none (monitoring only)",
                    fix=None if is_strict else "After 14–30 days of clean p=none reports, change to p=quarantine"),
    )


def check_mx(domain: str) -> CheckResult:
    mx = _resolve(domain, "MX")
    if mx:
        return CheckResult("MX (return path)", WEIGHTS["mx_present"], WEIGHTS["mx_present"], ", ".join(mx))
    return CheckResult("MX (return path)", WEIGHTS["mx_present"], 0,
                       "no MX record — bounces can't route back",
                       fix=f"Add MX for {domain} (Resend usually provides one like feedback-smtp.us-east-1.amazonses.com)")


def check_warmup(profile: dict) -> tuple[CheckResult, CheckResult]:
    w = profile.get("warmup", {})
    if not w.get("enabled"):
        return (
            CheckResult("Warmup active", WEIGHTS["warmup_active"], 0, "disabled",
                        fix=f"Run: py sequences\\warmup-scheduler.py start {profile['slug']}"),
            CheckResult("Warmup mature (≥30 days)", WEIGHTS["warmup_mature"], 0, "n/a"),
        )
    day = current_warmup_day(profile)
    active_score = WEIGHTS["warmup_active"]
    mature_score = WEIGHTS["warmup_mature"] if day >= 30 else 0
    detail_active = f"day {day} (started {w.get('started_at') or '?'})"
    detail_mature = f"day {day}" if day >= 30 else f"day {day} (need ≥30 for full credit)"
    fix_mature = None if day >= 30 else f"Let the scheduler tick daily until day 30; current_day advances on every successful tick"
    return (
        CheckResult("Warmup active", WEIGHTS["warmup_active"], active_score, detail_active),
        CheckResult("Warmup mature (≥30 days)", WEIGHTS["warmup_mature"], mature_score, detail_mature, fix_mature),
    )


def check_reputation(profile: dict) -> CheckResult:
    rep = profile.get("warmup", {}).get("reputation", {})
    th  = profile.get("warmup", {}).get("auto_pause_thresholds", {})
    clean = (rep.get("bounce_rate_7d", 0) <= th.get("bounce_rate", 0.05) and
             rep.get("complaint_rate_7d", 0) <= th.get("complaint_rate", 0.001))
    detail = (f"bounce {rep.get('bounce_rate_7d', 0)*100:.2f}%, complaint {rep.get('complaint_rate_7d', 0)*100:.3f}%, "
              f"delivered_7d {rep.get('delivered_7d', 0)}")
    return CheckResult("Reputation under thresholds", WEIGHTS["reputation_clean"],
                       WEIGHTS["reputation_clean"] if clean else 0, detail,
                       fix=None if clean else "Pause sends, investigate bounces/complaints, wait 7 days for rolling window to clear, restart at ramp day 1")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    args = ap.parse_args()
    profile = load_profile(args.slug)
    domain = (profile.get("relay", {}).get("from_domains") or [None])[0]
    selector = profile.get("relay", {}).get("dkim_selector") or "resend"
    if not domain:
        sys.exit("profile has no relay.from_domains")

    print(f"\n=== Deliverability scorecard: {domain} (profile: {profile['name']}) ===\n")
    checks: list[CheckResult] = []
    checks.append(check_sender_domain_resolves(domain))
    spf_pres, spf_auth = check_spf(domain)
    checks.append(spf_pres); checks.append(spf_auth)
    checks.append(check_dkim(domain, selector))
    dmarc_pres, dmarc_strict = check_dmarc(domain)
    checks.append(dmarc_pres); checks.append(dmarc_strict)
    checks.append(check_mx(domain))
    warm_active, warm_mature = check_warmup(profile)
    checks.append(warm_active); checks.append(warm_mature)
    checks.append(check_reputation(profile))

    # Render
    earned = sum(c.earned for c in checks)
    print(f"{'Check':<40} {'Earned/Max':<14} Detail")
    print("─" * 90)
    for c in checks:
        symbol = "✓" if c.earned == c.weight else ("·" if c.earned > 0 else "✗")
        print(f"{symbol} {c.name:<38} {c.earned}/{c.weight:<10}  {c.detail[:90]}")

    pct = (earned / MAX) * 100
    print("─" * 90)
    band = ("🚫 will spam"       if pct < 50  else
            "⚠ 60-75% inbox"      if pct < 75  else
            "✓ 80-90% inbox"      if pct < 90  else
            "✓✓ 95%+ inbox")
    print(f"\nScore: {earned}/{MAX} = {pct:.0f}%   →   {band}\n")

    todo = [c for c in checks if c.fix and c.earned < c.weight]
    if todo:
        print("Next steps to improve:")
        for i, c in enumerate(todo, 1):
            print(f"  {i}. [{c.weight - c.earned} pts] {c.name}")
            print(f"     → {c.fix}")
        print()
    else:
        print("✓ All checks pass. Maintain reputation by sending in business hours and respecting the snowball ramp.\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
