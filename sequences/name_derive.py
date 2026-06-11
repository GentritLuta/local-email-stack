"""name_derive.py — authoritative first_name + company derivation from email.

Single source of truth for turning a raw scraped email into a high-quality,
personalizable lead. Used at TWO points:

  1. lead_scrape.py  — at scrape time, BEFORE upsert. If neither a real
     first_name nor a company can be derived, the lead is rejected and never
     enters the pool (quality gate). This is what keeps the verified pool
     ~100% enrollable instead of ~50% nameless junk.

  2. scripts/backfill-*.py — as a safety-net backfill over existing rows
     (now a near no-op, since the scraper no longer inserts nameless leads).

Design: HIGH PRECISION over recall. A wrong first_name ("Hi Webteam,") is
worse than no lead, so every heuristic errs toward returning None. Real names
lost here are recovered cheaply by scraping more seeds; a bad name burns a
send and the recipient's goodwill.

Role-word rejection reuses lead_verify.GENERIC_LOCAL_PARTS (the hardened
~120-entry set) so there is ONE definition of "not a human name" across the
whole pipeline.
"""
from __future__ import annotations
import re
from pathlib import Path
import sys

# Reuse the hardened role/CTA/junk local-part set from lead_verify so role-word
# rejection never diverges between verification and name derivation.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lead_verify import GENERIC_LOCAL_PARTS  # noqa: E402

FREE_MAIL = {
    "gmail.com", "yahoo.com", "ymail.com", "rocketmail.com", "outlook.com",
    "hotmail.com", "aol.com", "icloud.com", "me.com", "mac.com", "web.de",
    "gmx.de", "gmx.net", "gmx.com", "proton.me", "protonmail.com", "live.com",
    "msn.com", "mail.com", "yandex.com", "yandex.ru", "zoho.com",
    # US ISP / cable mailboxes — a personal inbox, never the firm's domain.
    # (audit caught comcast.net -> "Comcast", triad.rr.com -> "Triad.rr" as fake
    # company names on real agents whose true brokerage was on the source page.)
    "comcast.net", "comcast.com", "verizon.net", "att.net", "sbcglobal.net",
    "bellsouth.net", "cox.net", "charter.net", "spectrum.net", "earthlink.net",
    "juno.com", "optonline.net", "windstream.net", "frontier.com",
    "frontiernet.net", "centurylink.net", "roadrunner.com", "twc.com", "ptd.net",
}

# ISP domains that use geographic subdomains (triad.rr.com, nc.rr.com, ...).
ISP_SUFFIXES = (".rr.com",)

# Junk / placeholder / registrar-parked domains — never derive, never enroll.
JUNK_DOMAINS = {"example.com", "example.de", "example.org", "4x.png", "0.0.3",
                "domain.com", "test.com", "localhost", "godaddy.com",
                "secureserver.net", "wixsite.com", "weebly.com", "mysite.com",
                "parkingcrew.net", "sentry.io", "wordpress.com"}


def is_free_or_isp_domain(domain: str) -> bool:
    """True for free-mail, ISP, and junk/parked domains — a domain that is NOT a
    real company website and must never become a {company} or website field."""
    d = (domain or "").lower()
    return d in FREE_MAIL or d in JUNK_DOMAINS or any(d.endswith(s) for s in ISP_SUFFIXES)

# Suffix tokens that mark a local-part as a concatenated BRAND, not a name.
# Union of the real-estate + crypto/creator lists the two backfills evolved.
BRAND_SUFFIXES = (
    # real-estate
    "realty", "realestate", "realtor", "realtors", "homes", "group",
    "estate", "estates", "properties", "property", "broker", "brokers",
    "sells", "sellshomes", "agency", "agent", "agents", "rentals",
    "leasing", "pros", "collective", "mgmt", "management", "family",
    "groupllc",
    # crypto / creator
    "media", "marketing", "studios", "labs", "channel", "official",
    "trader", "trading", "crypto", "alpha", "signals", "academy",
    "research", "insights", "capital", "ventures",
    # generic corp
    "llc", "inc", "team",
)

# Known multi-word brand splits (real-estate + crypto) so we don't ship
# "Whitestagrealty" as a company name.
KNOWN_BRAND_SPLITS = {
    # real-estate
    "whitestagrealty": "WhiteStag Realty",
    "talktotucker":    "Talk to Tucker",
    "c21scheetz":      "C21 Scheetz",
    "indyhomepros":    "Indy Home Pros",
    "atpropertiesind": "@properties Indianapolis",
    "encoresir":       "Encore Sotheby's International Realty",
    "truebloodre":     "Trueblood Real Estate",
    "hoosier-realtors":"Hoosier Realtors",
    "ferrispropertygroup": "Ferris Property Group",
    "1percentlists":   "1 Percent Lists",
    "listwithlew":     "List With Lew",
    "ninaklemm":       "Nina Klemm",
    "katinawhalen":    "Katina Whalen",
    "danathompson":    "Dana Thompson",
    "propertypogo":    "Property Pogo",
    "exprealty":       "eXp Realty",
    "kw":              "Keller Williams",
    "compass":         "Compass",
    "eveloteam":       "Evelo Team",
    "thekeygroupohio": "The Key Group Ohio",
    "homes4humans":    "Homes 4 Humans",
    "rresohio":        "RRE Ohio",
    # crypto / creator
    "decrypt":         "Decrypt",
    "decryptmedia":    "Decrypt",
    "edolab":          "EdoLab",
    "bybit-tr":        "Bybit",
    "quantum-algo":    "Quantum Algo",
    "boswaves":        "BosWaves",
    "bigbeluga":       "BigBeluga",
    "consensys":       "ConsenSys",
    "cointelegraph":   "Cointelegraph",
    "candelacharts":   "Candela Charts",
    "cryptoslate":     "CryptoSlate",
    "peterlbrandt":    "Peter L Brandt",
    "tokeninsight":    "TokenInsight",
    "coindesk":        "CoinDesk",
    "uptrick":         "Uptrick",
    "rug":             "Rug.fm",
    "coinbureau":      "Coin Bureau",
}

# Infix words to split on when a no-separator domain is one concatenated string.
# "thekeygroupohio" → split on "group" → "the key group ohio".
COMPANY_INFIX_WORDS = (
    "group", "homes", "realty", "estate", "estates", "properties",
    "team", "media", "labs", "studios", "agency", "realtors",
)
TWO_WORD_INFIXES = (
    ("realestate", "real estate"),
    ("realtygroup", "realty group"),
    ("homesgroup", "homes group"),
    ("homesteam", "homes team"),
)


def derive_company(email: str) -> str | None:
    """Company name from the email domain. None for free-mail / ISP / junk."""
    domain = email.split("@")[-1].lower()
    if is_free_or_isp_domain(domain):
        return None
    root = domain.rsplit(".", 1)[0]
    if root in KNOWN_BRAND_SPLITS:
        return KNOWN_BRAND_SPLITS[root]
    cleaned = root.replace("-", " ").replace("_", " ")
    # Two-word compound infixes first (longer match wins).
    if " " not in cleaned:
        for needle, replacement in TWO_WORD_INFIXES:
            if needle in cleaned and len(cleaned) > len(needle) + 2:
                cleaned = cleaned.replace(needle, " " + replacement + " ", 1).strip()
                cleaned = re.sub(r"\s+", " ", cleaned)
                break
    # Single-word infix split.
    if " " not in cleaned:
        for word in sorted(COMPANY_INFIX_WORDS, key=len, reverse=True):
            if word in cleaned and len(cleaned) > len(word) + 2:
                idx = cleaned.index(word)
                cleaned = (cleaned[:idx] + " " + word + " " + cleaned[idx+len(word):]).strip()
                cleaned = re.sub(r"\s+", " ", cleaned)
                break
    if cleaned.startswith("the") and not cleaned.startswith("the "):
        cleaned = "the " + cleaned[3:]
    return " ".join(w.capitalize() for w in cleaned.split())


# Valid name-initial consonant clusters (EN + DE). A no-separator local-part
# whose first two letters are BOTH consonants and NOT one of these is almost
# always first-initial+lastname (jlitten, jsmith, mgarcia, bsmith) — not a
# real given name. Kept generous so legit names (Sven, Florian, Chris, Stefan,
# Franz, Klaus, Vladimir, Greta) survive.
_VOWELS = set("aeiou")
_VALID_CC_ONSETS = {
    "bl", "br", "ch", "cl", "cr", "dr", "dw", "fl", "fr", "gl", "gn", "gr",
    "kl", "kn", "kr", "ph", "pl", "pr", "ps", "pf", "qu", "sc", "sh", "sk",
    "sl", "sm", "sn", "sp", "st", "sv", "sw", "th", "tr", "ts", "tw", "vl",
    "vr", "wh", "wr", "zw",
    # 3-char (checked on first[:3])
    "chr", "phr", "sch", "scr", "shr", "sph", "spl", "spr", "str", "thr",
}


def _is_initial_plus_last(first: str) -> bool:
    """True when a no-separator token looks like first-initial+lastname
    (consonant cluster onset that isn't a real name onset). 'jlitten' -> True,
    'sven'/'chris'/'bradley' -> False (valid onsets), 'maggie' -> False (vowel
    second char)."""
    if len(first) < 2:
        return False
    c1, c2 = first[0], first[1]
    if c1 in _VOWELS or c2 in _VOWELS or c2 == "y":
        return False  # consonant+vowel start = normal name (ma-, jo-, ty-, ly-)
    if first[:3] in _VALID_CC_ONSETS or first[:2] in _VALID_CC_ONSETS:
        return False  # real cluster: chris, sven, florian, stefan, vladimir
    return True       # implausible onset: jl, js, mg, bs, jc, ... = initial+last


def derive_first_name(email: str, company: str | None = None) -> str | None:
    """A confident human first name from the email local-part, or None.

    Conservative by design: returns None for first-initial+last (jsmith),
    concatenated full names (stevenschell), brand handles (whitestagrealty),
    role mailboxes (info/sales/today), and anything failing a basic
    human-name sanity check (length, vowel-near-start)."""
    domain = email.split("@")[-1].lower()
    if domain in JUNK_DOMAINS:
        return None
    local = email.split("@")[0].lower()
    if local in GENERIC_LOCAL_PARTS:
        return None
    first = re.split(r"[.\-_+]", local)[0]
    first = re.sub(r"\d+", "", first)
    if len(first) < 2 or len(first) > 12:
        return None
    if first in GENERIC_LOCAL_PARTS:
        return None
    # Reject if a generic dept word is *embedded* in a short local-part
    # (catches "nhello", "minfo", "xadmin" — typos / role-aliased boxes).
    if len(first) <= 9:
        for g in GENERIC_LOCAL_PARTS:
            if len(g) >= 4 and g in first and g != first:
                return None
    # Reject concatenated brand patterns ending in a brand suffix.
    for suffix in BRAND_SUFFIXES:
        if first.endswith(suffix) and len(first) > len(suffix) + 1:
            return None
    # Sanity: human first names have a vowel near the start.
    if not re.search(r"[aeiou]", first[:4]):
        return None
    # Reject when `first` is a prefix of a company-name word UNLESS it also
    # appears in the domain (then it's the person's own brand, e.g.
    # mason@masonversluis.com).
    if company:
        domain_root = domain.rsplit(".", 1)[0]
        first_in_domain = first in domain_root
        for word in re.split(r"\W+", company.lower()):
            if word and len(word) >= 3 and first.startswith(word) and not first_in_domain:
                return None
    # No-separator local-part needs extra scrutiny — it's one token, so we
    # can't trust a split.
    if not re.search(r"[.\-_+]", local):
        # >9 chars ≈ firstname+lastname concatenated ("Stevenschell").
        if len(first) > 9:
            return None
        # first-initial+lastname ("jlitten", "jsmith", "mgarcia") — implausible
        # consonant onset. Never greet someone "Hi Jlitten,".
        if _is_initial_plus_last(first):
            return None
    return first.capitalize()
