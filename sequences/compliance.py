# -*- coding: utf-8 -*-
"""compliance.py — detect when a website forbids unsolicited marketing / outreach
email, so the pipeline can SKIP that prospect instead of cold-emailing them.

Two real cases this protects against:
  1. EN sites with "no unsolicited email / no soliciting / we do not accept
     marketing" notices.
  2. DE Impressum pages with the standard anti-advertising objection, e.g.
     "Der Nutzung der im Impressum veröffentlichten Kontaktdaten zur Übersendung
     von nicht ausdrücklich angeforderter Werbung wird hiermit widersprochen."
     Emailing those addresses anyway is a UWG violation in Germany.

API:
  forbids_outreach(text) -> (bool, matched_phrase | None)

The patterns are deliberately specific (prohibition language + an email/contact/
advertising object) so a page that merely sells "marketing services" or mentions
"email" does not trip. Run this file directly for a self-test:
  py sequences/compliance.py
"""
from __future__ import annotations
import re

# Each entry: (compiled regex, short label). Order does not matter; first hit wins.
# re.I + re.S so matches survive line breaks in the rendered page text.
_PATTERNS = [
    # ── English ──────────────────────────────────────────────────────────────
    (re.compile(r"no\s+unsolicited\s+(?:commercial\s+)?(?:e-?mails?|messages?|contact|advertis|solicit)", re.I | re.S), "en:no-unsolicited"),
    (re.compile(r"\bno\s+solicit(?:ing|ation)s?\b", re.I), "en:no-soliciting"),
    (re.compile(r"do\s+not\s+(?:send|wish to receive|want to receive|accept)\b.{0,40}?(?:marketing|promotional|unsolicited|sales|solicit)", re.I | re.S), "en:do-not-send-marketing"),
    (re.compile(r"we\s+do\s+not\s+accept\b.{0,40}?(?:unsolicited|marketing|sales|promotional|solicit)", re.I | re.S), "en:not-accept-marketing"),
    (re.compile(r"unsolicited\s+(?:commercial\s+)?e-?mail.{0,40}?(?:not\s+(?:permitted|accepted|tolerated)|prohibited|will\s+be|is\s+forbidden)", re.I | re.S), "en:unsolicited-prohibited"),
    (re.compile(r"\bno\s+(?:cold|marketing|sales|spam)\s+(?:e-?mails?|outreach|pitches?|solicitations?|calls?)\b", re.I), "en:no-cold-email"),
    (re.compile(r"please\s+do\s+not\s+(?:contact|e-?mail|solicit)\b.{0,40}?(?:offer|service|market|sales|solicit)", re.I | re.S), "en:please-do-not-contact-vendors"),
    (re.compile(r"not\s+interested\s+in\s+(?:any\s+)?(?:marketing|solicitation|sales\s+pitch)", re.I | re.S), "en:not-interested-marketing"),
    # ── German ───────────────────────────────────────────────────────────────
    (re.compile(r"nicht\s+ausdrücklich\s+angeforderter?\s+werbung", re.I | re.S), "de:impressum-anti-werbung"),
    (re.compile(r"widerspr\w+.{0,60}?(?:werbung|werbe-?mails?|werbezwecke|werbe-?e-?mails?)", re.I | re.S), "de:widerspruch-werbung"),
    (re.compile(r"der\s+nutzung\b.{0,160}?(?:kontaktdaten|impressum).{0,160}?werb", re.I | re.S), "de:nutzung-kontaktdaten-werbung"),
    (re.compile(r"werbe-?(?:e-?)?mails?.{0,20}?(?:unerwünscht|nicht\s+erwünscht|untersagt|verboten)", re.I | re.S), "de:werbemails-unerwuenscht"),
    (re.compile(r"keine\s+(?:unaufgeforderte[nr]?|unverlangte[nr]?)\b.{0,30}?(?:werbung|e-?mails?|zusendung|kontaktaufnahme)", re.I | re.S), "de:keine-unaufgeforderte"),
    (re.compile(r"\bunverlangte[nr]?\s+(?:zusendung|werbung|e-?mails?)", re.I), "de:unverlangte-zusendung"),
    (re.compile(r"keine\s+werbung\b", re.I), "de:keine-werbung"),
]

# Hard cap so a giant page does not make the scan expensive; the notices we care
# about live in footers / contact / Impressum text well within this.
_MAX_SCAN = 200_000


def forbids_outreach(text: str | None) -> tuple[bool, str | None]:
    """Return (True, label) if the text contains a notice forbidding unsolicited
    marketing / outreach email, else (False, None)."""
    if not text:
        return (False, None)
    hay = text[:_MAX_SCAN]
    for rx, label in _PATTERNS:
        if rx.search(hay):
            return (True, label)
    return (False, None)


def _selftest() -> int:
    POS = [
        # German Impressum anti-advertising clause (extremely common)
        "Der Nutzung der im Rahmen der Impressumspflicht veröffentlichten Kontaktdaten "
        "zur Übersendung von nicht ausdrücklich angeforderter Werbung und Informationsmaterialien "
        "wird hiermit widersprochen.",
        "Werbe-E-Mails sind unerwünscht und werden als Spam gewertet.",
        "Keine Werbung bitte.",
        "We do not accept unsolicited marketing emails or sales solicitations.",
        "NO SOLICITING. Please do not contact us to offer services or marketing.",
        "Unsolicited commercial email is not permitted and will be reported.",
        "No cold emails or sales pitches, thank you.",
    ]
    NEG = [
        "We are a full-service digital marketing agency. Email us at hello@acme.com.",
        "Contact our sales team for a quote. We send a weekly newsletter.",
        "Meet our agents. Call or email any of them directly to buy or sell your home.",
        "Impressum: Musterfirma GmbH, Musterstrasse 1, Geschäftsführer Max Mustermann.",
        "Reply REVIEW and we send you a free architecture review. No call attached.",
    ]
    ok = True
    print("POSITIVE (should all detect):")
    for t in POS:
        hit, label = forbids_outreach(t)
        print(f"  {'OK ' if hit else 'MISS'} [{label}] {t[:64]}...")
        ok = ok and hit
    print("\nNEGATIVE (should all pass = no detection):")
    for t in NEG:
        hit, label = forbids_outreach(t)
        print(f"  {'OK ' if not hit else 'FALSE+'} [{label}] {t[:64]}...")
        ok = ok and not hit
    print("\nRESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
