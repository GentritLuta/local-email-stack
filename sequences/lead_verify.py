"""lead_verify.py — free email verification: syntax + disposable + MX + SMTP probe.

Importable module (no CLI surface needed by callers, but `py lead_verify.py addr`
works for ad-hoc checks). Designed to never raise: every path returns a
VerificationResult so callers can decide what to do with low-confidence rows.

Verification ladder (best signal wins):
  1. syntax check (RFC 5322 simplified) — `invalid_syntax` if it fails
  2. disposable-domain blocklist — `disposable` if hit
  3. DNS MX lookup — `no_mx` if domain has no MX records
  4. SMTP probe: HELO + MAIL FROM + RCPT TO + QUIT (no DATA, never sends)
       - 250 on RCPT → `smtp_verified`           (highest confidence)
       - 550/551/553 → `smtp_rejected`           (mailbox does not exist)
       - timeout / port 25 blocked / soft fail → `smtp_failed` AND we fall back
         to `mx_verified` (medium confidence — domain takes mail, mailbox unknown)
  5. catch-all heuristic: probe a random local-part. If accepted, mark catchall=true
     so the caller can apply extra caution.

Residential ISPs often block outbound port 25 — in that case we settle for
`mx_verified` and the operator gets clean MX-only verification, which still
filters out dead domains and typos.
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import smtplib
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import dns.resolver
import dns.exception

# ─── Disposable-domain blocklist (free, hand-curated) ──────────────────────
# Not exhaustive but covers the common cases. Lowercased.
DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "10minutemail.com", "guerrillamail.com",
    "throwawaymail.com", "yopmail.com", "fakeinbox.com", "trashmail.com",
    "sharklasers.com", "getairmail.com", "dispostable.com", "maildrop.cc",
    "mintemail.com", "mohmal.com", "spamgourmet.com", "tempr.email",
    "tempinbox.com", "throwam.com", "instantmail.fr", "spambog.com",
    "anonymbox.com", "boun.cr", "burnermail.io", "deadaddress.com",
    "discardmail.com", "emailondeck.com", "filzmail.com", "harakirimail.com",
    "incognitomail.org", "letthemeatspam.com", "loadby.us", "mailcatch.com",
    "mailexpire.com", "mailforspam.com", "mailguard.me", "mailhazard.com",
    "mailmoat.com", "mailnesia.com", "mailtrash.net", "no-spam.ws",
    "objectmail.com", "owlpic.com", "pookmail.com", "sneakemail.com",
    "spam.la", "spambox.us", "spamfree.eu", "spamhole.com", "spaminator.de",
    "spamspot.com", "speed.1s.fr", "tagyourself.com", "teleworm.us",
    "thisisnotmyrealemail.com", "tilien.com", "tmail.ws", "tradermail.info",
    "trbvm.com", "tyldd.com", "uggsrock.com", "wegwerfmail.de", "willhackforfood.biz",
    "wuzup.net", "xemaps.com", "yopmail.fr", "zippymail.in",
}

# Role-based local parts that we don't want for personalized outreach
# (campaigns target individuals, not generic inboxes).
GENERIC_LOCAL_PARTS = {
    "info", "contact", "hello", "sales", "admin", "support", "noreply",
    "no-reply", "office", "team", "marketing", "recruiting", "hr", "jobs",
    "press", "media", "billing", "accounts", "help", "service", "feedback",
    "abuse", "postmaster", "webmaster", "general", "inquiries", "enquiries",
}

# RFC-5322-lite: allows the practical 99% of real addresses without being strict.
EMAIL_RX = re.compile(
    r"^(?P<local>[A-Za-z0-9._%+\-]+)"
    r"@"
    r"(?P<domain>[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)*"
    r"\.[A-Za-z]{2,63})$"
)

# Resolver used for MX lookups. Short timeout so a stuck DNS doesn't block scrape.
_RESOLVER = dns.resolver.Resolver()
_RESOLVER.timeout = 3
_RESOLVER.lifetime = 6


@dataclass
class VerificationResult:
    email: str
    verified: bool                          # True only when we have positive signal
    method: str                             # see ladder above
    mx_hosts: list[str] = field(default_factory=list)
    catchall: bool = False                  # True when the domain accepts any RCPT
    error: Optional[str] = None
    is_generic: bool = False                # local part in GENERIC_LOCAL_PARTS
    checked_at: float = field(default_factory=lambda: time.time())


def _parse(email: str) -> tuple[Optional[str], Optional[str]]:
    m = EMAIL_RX.match(email.strip())
    if not m:
        return None, None
    return m.group("local").lower(), m.group("domain").lower()


def _mx_hosts(domain: str) -> list[str]:
    try:
        answers = _RESOLVER.resolve(domain, "MX")
        # Order by priority ascending
        sorted_mx = sorted(answers, key=lambda r: r.preference)
        return [str(r.exchange).rstrip(".") for r in sorted_mx]
    except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN,
            dns.resolver.NoNameservers, dns.exception.Timeout):
        return []


def _smtp_probe(mx_host: str, target_email: str, helo_domain: str,
                from_addr: str, timeout: int = 8) -> tuple[Optional[int], str]:
    """Return (rcpt_code, message). rcpt_code None if connection failed."""
    try:
        with smtplib.SMTP(mx_host, 25, timeout=timeout) as s:
            s.ehlo(helo_domain)
            try:
                s.starttls()
                s.ehlo(helo_domain)
            except Exception:
                pass  # plenty of MX hosts don't speak STARTTLS for 25
            code, _ = s.mail(from_addr)
            if code >= 400:
                return code, f"MAIL FROM rejected with {code}"
            code, msg = s.rcpt(target_email)
            try: s.quit()
            except Exception: pass
            return code, (msg.decode("utf-8", errors="ignore") if isinstance(msg, bytes) else str(msg))
    except (socket.timeout, OSError, smtplib.SMTPException) as e:
        return None, f"{type(e).__name__}: {e}"


def verify(email: str, *,
           from_addr: str = "verify@aureonglobal.de",
           helo_domain: str = "aureonglobal.de",
           do_smtp_probe: bool = True,
           do_catchall_probe: bool = True) -> VerificationResult:
    """Single-shot verification. Always returns a result; never raises."""
    local, domain = _parse(email)
    if not local or not domain:
        return VerificationResult(email=email, verified=False, method="invalid_syntax",
                                  error="failed RFC-5322 simplified pattern")

    is_generic = local in GENERIC_LOCAL_PARTS

    if domain in DISPOSABLE_DOMAINS:
        return VerificationResult(email=email, verified=False, method="disposable",
                                  is_generic=is_generic,
                                  error=f"{domain} is on the disposable-domain blocklist")

    mx = _mx_hosts(domain)
    if not mx:
        return VerificationResult(email=email, verified=False, method="no_mx",
                                  is_generic=is_generic,
                                  error=f"{domain} has no MX records")

    if not do_smtp_probe:
        return VerificationResult(email=email, verified=True, method="mx_verified",
                                  mx_hosts=mx, is_generic=is_generic)

    rcpt_code, rcpt_msg = _smtp_probe(mx[0], email, helo_domain, from_addr)
    if rcpt_code is None:
        # Couldn't connect (port 25 blocked, etc). Fall back to MX-only verification.
        return VerificationResult(email=email, verified=True, method="mx_verified",
                                  mx_hosts=mx, is_generic=is_generic,
                                  error=f"smtp_probe_failed: {rcpt_msg}")

    if rcpt_code in (250, 251):
        catchall = False
        if do_catchall_probe:
            random_local = f"verify-probe-{uuid.uuid4().hex[:10]}"
            ca_code, _ = _smtp_probe(mx[0], f"{random_local}@{domain}", helo_domain, from_addr)
            catchall = ca_code in (250, 251)
        return VerificationResult(email=email, verified=True, method="smtp_verified",
                                  mx_hosts=mx, catchall=catchall, is_generic=is_generic)

    if rcpt_code in (550, 551, 553, 554):
        return VerificationResult(email=email, verified=False, method="smtp_rejected",
                                  mx_hosts=mx, is_generic=is_generic,
                                  error=f"RCPT {rcpt_code}: {rcpt_msg.strip()}")

    # Greylisting (450/451/452) and other soft fails — treat as MX-verified, unknown mailbox.
    return VerificationResult(email=email, verified=True, method="mx_verified",
                              mx_hosts=mx, is_generic=is_generic,
                              error=f"soft_smtp_code_{rcpt_code}: {rcpt_msg.strip()}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("email")
    ap.add_argument("--no-smtp", action="store_true", help="skip SMTP probe (MX-only)")
    ap.add_argument("--no-catchall", action="store_true", help="skip catch-all probe")
    args = ap.parse_args()
    r = verify(args.email,
               do_smtp_probe=not args.no_smtp,
               do_catchall_probe=not args.no_catchall)
    print(json.dumps(asdict(r), indent=2))
    return 0 if r.verified else 1


if __name__ == "__main__":
    sys.exit(main())
