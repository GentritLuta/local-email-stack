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
import random
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
    # Classic role mailboxes
    "info", "contact", "hello", "sales", "admin", "support", "noreply",
    "no-reply", "office", "team", "marketing", "recruiting", "hr", "jobs",
    "press", "media", "billing", "accounts", "help", "service", "feedback",
    "abuse", "postmaster", "webmaster", "general", "inquiries", "enquiries",
    "careers", "legal", "privacy", "compliance", "security", "dpo",
    # CTA / commerce junk — scraped from "Get more"/"Upgrade"/"Free trial"
    # buttons & marketing mailtos, not real people. These drove the crypto
    # bounce spike (free@, upgrade@, quote@, more@ all hard-bounced).
    "free", "upgrade", "get", "try", "demo", "start", "join", "subscribe",
    "signup", "sign-up", "download", "buy", "order", "shop", "deal", "deals",
    "offer", "offers", "promo", "sale", "quote", "quotes", "pricing", "plans",
    "donate", "refer", "invite", "more",
    # Content / web junk
    "website", "web", "site", "ai", "app", "api", "blog", "news",
    "newsletter", "content", "social", "follow", "podcast",
    # Text-scrape false positives (pronouns from "email him at ...")
    "him", "her", "you", "your", "hey",
    # Crypto/biz role addresses
    "editor", "newsdesk", "newsroom", "tips", "pitch", "business", "bizdev",
    "partnerships", "sponsors", "sponsorships", "advertise", "advertising",
    "affiliate", "affiliates", "ambassador",
    # Non-mailbox business nouns scraped from bio/site text — confirmed dorian
    # bounces (out@, officer@, businesses@, customers@, career@, audit@ all hard-
    # bounced: real MX, no such mailbox). 2026-06-14.
    "out", "officer", "officers", "businesses", "customer", "customers",
    "audit", "audits", "career", "prospecting", "prospect", "outreach",
    # Social / CTA / text-scrape junk (button labels, footer prompts, etc.)
    "click", "view", "watch", "listen", "read", "learn", "find", "discover",
    "share", "follow", "like", "comment", "post", "today", "now", "here",
    "soon", "login", "register", "save", "search", "visit", "open", "close",
    "us", "we", "our", "ours",
    # Front-desk / general inboxes (incl. German) — no human name, but real
    # monitored business contacts (see ADMITTABLE_ROLE_LOCALS below).
    "kontakt", "hallo", "mail", "welcome", "willkommen", "reception", "empfang",
}


# Front-desk / general business inboxes a decision-maker (or their gatekeeper)
# actually reads. No human name, but VALID company-level cold-outreach targets:
# a "Hey {company} team," pitch to info@brokerage.com is legitimate B2B. This is
# a SUBSET of GENERIC_LOCAL_PARTS, broken out so a name-optional campaign can
# admit them while still rejecting automated / wrong-department / junk inboxes.
ADMITTABLE_ROLE_LOCALS = {
    "info", "contact", "kontakt", "hello", "hallo", "hey",
    "office", "team", "mail", "general", "enquiries", "inquiries",
    "welcome", "willkommen", "reception", "empfang",
}

# Decision-maker / title inboxes — EXCELLENT B2B cold-outreach targets (they
# reach the buyer), but they carry NO human name. Added to BOTH sets below so
# derive_first_name treats them as no-name (greet by "{company} team", never
# "Hi Owner,"/"Hi Ceo,") AND the gate admits them. Catches owner@/founder@/
# ceo@/broker@/agent@ which were leaking through as fake first names.
_DECISION_MAKER_LOCALS = {
    "owner", "founder", "cofounder", "co-founder", "ceo", "cto", "coo", "cfo",
    "president", "vp", "principal", "director", "partner", "gm", "manager",
    "broker", "realtor", "agent", "management", "leadership", "chief",
    "hq", "headquarters", "main", "frontdesk", "desk", "missioncontrol",
}
GENERIC_LOCAL_PARTS = GENERIC_LOCAL_PARTS | _DECISION_MAKER_LOCALS
ADMITTABLE_ROLE_LOCALS = ADMITTABLE_ROLE_LOCALS | _DECISION_MAKER_LOCALS

# Back-office / operational real-estate inboxes. Real mailboxes, but the WRONG
# contact for a growth-partnership pitch (they coordinate paperwork and closings,
# they do not buy services) AND they were deriving fake first names
# (escrow@ -> "Escrow", closing@ -> "Closing", listings@ -> "Listings"). Added
# to GENERIC only (no-name) and NOT to ADMITTABLE, so they fall into JUNK below
# and get rejected. Surfaced by the transactions@teamminik.com research.
_BACKOFFICE_LOCALS = {
    "transactions", "transaction", "escrow", "escrows", "closing", "closings",
    "paperwork", "processing", "processor", "coordinator", "tc", "files",
    "documents", "docs", "listings", "listing", "leasing", "rentals",
    "propertymanagement", "maintenance", "scheduling", "showings", "title",
}
GENERIC_LOCAL_PARTS = GENERIC_LOCAL_PARTS | _BACKOFFICE_LOCALS

# Locals to HARD-reject even in name-optional company-level mode: automated
# system boxes (noreply/postmaster), wrong-department inboxes (a partnership
# pitch to hr@/billing@/support@ is wasted), and CTA/scrape junk. Everything
# generic that is NOT a front-desk inbox.
JUNK_LOCAL_PARTS = GENERIC_LOCAL_PARTS - ADMITTABLE_ROLE_LOCALS


# Patterns that prove the address is malformed / scrape junk — these are
# ALWAYS invalid, regardless of MX. Tightened after the first batches
# revealed %20-prefixed URL-encoded addresses and a few file-extension
# artifacts slipping through the existing simplified RFC pattern.
_MALFORMED_RE = re.compile(
    r"%[0-9A-Fa-f]{2}"         # URL-encoded char (%20, %2E, ...)
    r"|\s"                     # any whitespace
    r"|\.\."                   # consecutive dots
    r"|\.(png|jpe?g|gif|svg|webp|pdf|html?|css|js|ico|bmp|tiff?)$",  # file ext
    re.IGNORECASE,
)


# Provider-specific local-part rules. These mailbox providers PUBLISH their
# username rules, so an address that violates them CANNOT exist and is rejected
# with ZERO network calls (no SMTP probe, no IP rate-limit risk). This is the
# permanent free layer that catches most dead big-provider addresses up front.
GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


def _provider_local_invalid(local: str, domain: str) -> str | None:
    """Return a reason string if `local` cannot be a real mailbox at `domain`
    per that provider's published username rules, else None.

    Gmail (support.google.com/mail/answer/9211434): 6-30 chars, only letters,
    digits and dots; no leading/trailing dot; no consecutive dots; the other
    specials (_ - + = etc.) are not allowed in the account name. (A '+tag' alias
    is delivered, so we tolerate a single '+'; everything before it must obey the
    rules.) Dots are ignored by Gmail, so they do not count toward length.
    """
    if domain in GMAIL_DOMAINS:
        base = local.split("+", 1)[0]          # strip +tag alias
        core = base.replace(".", "")           # dots are ignored by Gmail
        if not re.fullmatch(r"[a-z0-9]+", base.replace(".", "")):
            return "gmail_invalid_chars"
        if base.startswith(".") or base.endswith("."):
            return "gmail_edge_dot"
        if ".." in base:
            return "gmail_consecutive_dots"
        if len(core) < 6:
            return "gmail_too_short"
        if len(core) > 30:
            return "gmail_too_long"
    return None


def _is_malformed(email: str, local: str, domain: str) -> tuple[bool, str]:
    """Catch obvious junk patterns the simplified RFC regex lets through.
    Returns (is_malformed, reason). These get hard-rejected by verify()."""
    if _MALFORMED_RE.search(email):
        return True, "malformed_pattern"
    if email.count("@") != 1:
        return True, "multiple_or_missing_at"
    if local.startswith(("http", "www", "ftp", "mailto")):
        return True, "url_prefix_in_local"
    if len(local) < 2:
        return True, "local_too_short"
    if local.isdigit():
        return True, "all_digit_local"
    if local[0] in "._-+" or local[-1] in "._-+":
        return True, "edge_special_char_in_local"
    if len(domain) < 4 or "." not in domain:
        return True, "domain_too_short_or_no_dot"
    prov = _provider_local_invalid(local, domain)
    if prov:
        return True, prov
    return False, ""

# Placeholder / example domains that show up in tutorial copy-paste blocks on
# creator About pages ("contact me: your-email@domain.de"). These are NOT
# real recipients — verify() must hard-fail them before they reach send_log.
PLACEHOLDER_DOMAINS = {
    "domain.com", "domain.de", "example.com", "example.de", "example.org",
    "example.net", "yourdomain.com", "your-domain.com", "yourcompany.com",
    "beispiel.de", "firmenname.de", "test.com", "test.de", "localhost",
    "company.com", "company.de", "email.com", "mydomain.com",
}
PLACEHOLDER_LOCALS = {
    "your-email", "your.email", "youremail", "yourname", "your-name",
    "deine-email", "deine.email", "deinemail", "meine-email", "meine.email",
    "name", "user", "email", "test", "beispiel", "example",
    "firstname.lastname", "firstname", "lastname",
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


# Per-MX-host pacing. Gmail (and other big providers) rate-limit repeated RCPT
# probes from one IP within a short window. We keep a per-host last-probe clock and
# enforce a minimum gap so SUSTAINED verification stays under the throttle threshold
# indefinitely from a single IP. The earlier test-time timeouts were burst probing;
# at the real ~36/day send rate, paced probing keeps the IP healthy permanently.
_LAST_PROBE: dict[str, float] = {}
_MIN_HOST_GAP_S = 20.0   # at least 20s between probes to the same MX host


def _pace_host(mx_host: str) -> None:
    import time as _t
    key = mx_host.split(".", 1)[-1] if "." in mx_host else mx_host  # group by provider zone
    last = _LAST_PROBE.get(key, 0.0)
    wait = _MIN_HOST_GAP_S - (_t.time() - last)
    if wait > 0:
        _t.sleep(wait + random.random())   # jitter
    _LAST_PROBE[key] = _t.time()


def _smtp_probe_once(mx_host: str, target_email: str, helo_domain: str,
                     from_addr: str, timeout: int = 12) -> tuple[Optional[int], str]:
    """Return (rcpt_code, message). rcpt_code None if connection failed.
    One attempt, no retry. Paced per MX-host to avoid IP rate-limiting."""
    _pace_host(mx_host)
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


def _smtp_probe(mx_host: str, target_email: str, helo_domain: str,
                from_addr: str, timeout: int = 12, retries: int = 2) -> tuple[Optional[int], str]:
    """SMTP RCPT probe with retry+backoff on transient failures. Big mail hosts
    (Gmail especially) rate-limit repeated RCPT probes from one IP and answer with
    a timeout or a 4xx; that is NOT a signal the mailbox is bad. We retry with
    exponential backoff + jitter (the same approach paid verifiers use) so a
    rate-limit does not get mistaken for an invalid address.

    Returns the FIRST definitive code (250/251 accept, 550/551/553/554 reject).
    If every attempt is transient (connect failure or 4xx), returns the last
    transient result so the caller classifies it as 'unknown', never as valid."""
    last: tuple[Optional[int], str] = (None, "no attempt")
    for attempt in range(retries + 1):
        code, msg = _smtp_probe_once(mx_host, target_email, helo_domain, from_addr, timeout)
        # Definitive accept or reject -> return immediately.
        if code is not None and (code in (250, 251) or 500 <= code < 560):
            return code, msg
        # Transient (None connect-fail, or 4xx greylist/rate-limit): back off and retry.
        last = (code, msg)
        if attempt < retries:
            time.sleep((2 ** attempt) + random.random() * 1.5)  # 1-2.5s, then 2-3.5s
    return last


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

    # Strict junk-pattern rejection (catches scrape artifacts the RFC pattern
    # tolerates: %20-prefix, double-dot, .png suffix, single-char local, etc.)
    mal, mal_why = _is_malformed(email, local, domain)
    if mal:
        return VerificationResult(email=email, verified=False, method="malformed",
                                  error=mal_why)

    is_generic = local in GENERIC_LOCAL_PARTS

    # Hard-reject JUNK local-parts (automated/wrong-department/scrape-noise that
    # is never a real human mailbox) for EVERY scraper path. lead_scrape already
    # pre-filters these, but the creator scrapers (youtube/social) did not, which
    # is how out@/officer@/website@/businesses@/support@ reached dorian's pool and
    # hard-bounced. Front-desk ADMITTABLE locals (info@/team@/hello@) are NOT junk
    # and still pass — the per-brand requires_first_name gate decides those.
    if local in JUNK_LOCAL_PARTS:
        return VerificationResult(email=email, verified=False, method="junk_local",
                                  is_generic=is_generic,
                                  error=f"{local}@ is a junk/role local-part, not a real mailbox")

    if domain in DISPOSABLE_DOMAINS:
        return VerificationResult(email=email, verified=False, method="disposable",
                                  is_generic=is_generic,
                                  error=f"{domain} is on the disposable-domain blocklist")

    # Placeholder pattern (your-email@domain.de, name@example.com, etc.)
    # These show up in creator About-page tutorials. Hard-fail before MX
    # so they never reach send_log.
    if domain in PLACEHOLDER_DOMAINS or local in PLACEHOLDER_LOCALS:
        return VerificationResult(email=email, verified=False, method="placeholder",
                                  is_generic=is_generic,
                                  error=f"{email} matches placeholder pattern (domain/local)")

    mx = _mx_hosts(domain)
    if not mx:
        return VerificationResult(email=email, verified=False, method="no_mx",
                                  is_generic=is_generic,
                                  error=f"{domain} has no MX records")

    if not do_smtp_probe:
        return VerificationResult(email=email, verified=True, method="mx_verified",
                                  mx_hosts=mx, is_generic=is_generic)

    rcpt_code, rcpt_msg = _smtp_probe(mx[0], email, helo_domain, from_addr)

    if rcpt_code in (250, 251):
        # Mailbox accepted. Now distinguish a real mailbox from a catch-all/accept-all
        # domain (accepts every RCPT, then may async-bounce). A catch-all cannot be
        # verified at SMTP time by anyone, paid or free, so we mark it not-verified
        # with a distinct method rather than trusting it.
        catchall = False
        if do_catchall_probe:
            random_local = f"verify-probe-{uuid.uuid4().hex[:10]}"
            ca_code, _ = _smtp_probe(mx[0], f"{random_local}@{domain}", helo_domain, from_addr)
            catchall = ca_code in (250, 251)
        if catchall:
            return VerificationResult(email=email, verified=False, method="catch_all",
                                      mx_hosts=mx, catchall=True, is_generic=is_generic,
                                      error="domain accepts all RCPT (accept-all); mailbox unprovable")
        return VerificationResult(email=email, verified=True, method="smtp_verified",
                                  mx_hosts=mx, catchall=False, is_generic=is_generic)

    if rcpt_code in (550, 551, 553, 554):
        return VerificationResult(email=email, verified=False, method="smtp_rejected",
                                  mx_hosts=mx, is_generic=is_generic,
                                  error=f"RCPT {rcpt_code}: {rcpt_msg.strip()}")

    # Everything else is UNKNOWN: a connect failure (our IP got rate-limited, or a
    # transient port issue, rcpt_code is None) or a 4xx (greylisting/throttle) that
    # survived all retries. We must NOT drop the lead on uncertainty, or a throttled
    # probe would discard perfectly valid addresses and shrink the pool. So we keep
    # it send-eligible (verified=True) but tag method 'smtp_unknown' so the paced
    # re-verify pass (reverify-unknowns.py) can later resolve it and flip it to
    # verified=False ONLY on a definitive 550. The dead-mailbox wins come from the
    # provider format rules (zero-network, above) and definitive 550 smtp_rejected,
    # both of which already mark verified=False. This is the build-up, no-compromise
    # design: certainty drops a lead, uncertainty never does.
    detail = (f"smtp_unknown: connect failed ({rcpt_msg})" if rcpt_code is None
              else f"smtp_unknown: soft code {rcpt_code} ({rcpt_msg.strip()})")
    return VerificationResult(email=email, verified=True, method="smtp_unknown",
                              mx_hosts=mx, is_generic=is_generic, error=detail)


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
