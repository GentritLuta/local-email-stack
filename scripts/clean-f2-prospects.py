"""Scrub F2 prospect list.

The lead_scrape regex picked up Sentry tracking URLs and version
strings as if they were email addresses (e.g. dd0a55cc...@sentry.io,
rspack@1.6.6). Mark those unverified so the strict gate ignores them,
then backfill first_name from local-part on the legitimate ones.

Run:
    py scripts/clean-f2-prospects.py
"""
from __future__ import annotations
import json, re, sys, urllib.request, urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV  = REPO / "sequences" / "supabase.env"

env = {}
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H_R = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
H_W = {**H_R, "Content-Type": "application/json", "Prefer": "return=minimal"}

# Sentry beacons + arbitrary version strings = NOT emails. Quarantine.
JUNK_DOMAIN_RE = re.compile(
    r"^(sentry\.io|sentry[\w.-]*\.wixpress\.com|\d+(\.\d+)+|.*\.png|.*\.jpg)$",
    re.I,
)
GENERIC_LOCAL = {
    "info", "admin", "team", "contact", "office", "hello",
    "hi", "support", "help", "kontakt", "sales", "service",
    "press", "media", "immo", "verwaltung", "buchhaltung",
    "vermieten", "vermietung", "verkauf", "rechnung", "noreply",
    "no-reply", "abuse", "postmaster", "webmaster",
}
BRAND_SUFFIXES = (
    "immo", "verwaltung", "immobilien", "liegenschaften",
    "treuhand", "gmbh", "ag", "team", "group",
)
# Bern-canton Liegenschaftsverwaltungen → city map. The F2 variant template
# requires {city} so without this F2 prospects are unsendable.
DOMAIN_CITY = {
    "jordi-liegenschaften.ch":   "Bern",
    "be.regimo.ch":              "Bern",
    "leu.swiss":                 "Bern",
    "resonus-immobilien.ch":     "Bern",
    "bestag.ch":                 "Bern",
    "fischer-immo.ch":           "Burgdorf",
    "halter.ch":                 "Bern",
    "livit.ch":                  "Bern",
    "wincasa.ch":                "Bern",
    "pom.ch":                    "Bern",
    "berniva.ch":                "Bern",
    "swissrent.ch":              "Bern",
}
# Domain → company display name for the F2 variant body's {company} merge.
DOMAIN_COMPANY = {
    "jordi-liegenschaften.ch":   "Jordi Liegenschaften",
    "be.regimo.ch":              "Regimo Bern",
    "leu.swiss":                 "LEU Immobilien",
    "resonus-immobilien.ch":     "Resonus Immobilien",
    "bestag.ch":                 "Bestag",
    "gewerbetreuhandag.ch":      "Gewerbetreuhand AG Bern",
}


def is_junk_domain(email: str) -> bool:
    domain = email.split("@")[-1].lower()
    return bool(JUNK_DOMAIN_RE.match(domain))


def derive_city(email: str) -> str | None:
    domain = email.split("@")[-1].lower()
    return DOMAIN_CITY.get(domain)


def derive_company(email: str) -> str | None:
    domain = email.split("@")[-1].lower()
    return DOMAIN_COMPANY.get(domain)


# Generic company name from the email domain when it's not in DOMAIN_COMPANY.
# Lets auto-discovered firms (new categories / cities) get a {company} merge
# value without a hand-maintained map. "architektur-meier.ch" -> "Architektur
# Meier";  "be.regimo.ch" -> "Regimo".
_CO_UPPER = {"ag", "gmbh", "sa", "kg", "ig", "llc"}

def derive_company_generic(email: str) -> str | None:
    domain = email.split("@")[-1].lower().strip()
    if not domain or "." not in domain:
        return None
    labels = [l for l in domain.split(".") if l not in ("www",)]
    sld = labels[-2] if len(labels) >= 2 else labels[0]
    words = [w for w in re.split(r"[-_]", sld) if w]
    if not words:
        return None
    name = " ".join(w.upper() if w in _CO_UPPER else w.capitalize() for w in words)
    return name if 2 <= len(name) <= 40 else None


# High-precision Swiss-German city extraction. Rather than a PLZ regex (which
# false-matches copyright years etc.), scan the firm's Impressum/Kontakt page
# for a known Deutschschweiz town. F2's {city} merge then works for any
# auto-discovered lead whose site exposes an address (Swiss Impressum is
# legally mandated, so most do).
DACH_CITIES = [
    "Zürich", "Winterthur", "Uster", "Dübendorf", "Bern", "Biel", "Thun",
    "Köniz", "Burgdorf", "Langenthal", "Basel", "Liestal", "Luzern", "Zug",
    "Baar", "Aarau", "Baden", "Wettingen", "Olten", "Solothurn", "Grenchen",
    "St. Gallen", "Gossau", "Wil", "Chur", "Frauenfeld", "Schaffhausen",
    "Rapperswil", "Wetzikon", "Kloten", "Bülach", "Dietikon", "Schlieren",
    "Emmen", "Kriens", "Zofingen", "Spiez", "Ostermundigen", "Ittigen",
    "Gümligen", "Worb", "Münsingen", "Utzenstorf", "Herzogenbuchsee",
]
_CITY_PATTERNS = [(c, re.compile(r"\b" + re.escape(c) + r"\b", re.I)) for c in DACH_CITIES]
_city_cache: dict[str, str | None] = {}

def fetch_city_from_site(website: str | None) -> str | None:
    if not website:
        return None
    from urllib.parse import urlparse
    host = urlparse(website).netloc or website
    if host in _city_cache:
        return _city_cache[host]
    result = None
    base = website.rstrip("/")
    for path in ("/impressum", "/kontakt", "/contact", ""):
        try:
            req = urllib.request.Request(
                base + path, headers={"User-Agent": "Mozilla/5.0 F2LeadBot/1.0"})
            html = urllib.request.urlopen(req, timeout=8).read().decode("utf-8", "replace")
        except Exception:
            continue
        for canon, pat in _CITY_PATTERNS:
            if pat.search(html):
                result = canon
                break
        if result:
            break
    _city_cache[host] = result
    return result


def derive_first_name(email: str, company: str | None = None) -> str | None:
    local = email.split("@")[0].lower()
    if local in GENERIC_LOCAL: return None
    first = re.split(r"[.\-_+]", local)[0]
    first = re.sub(r"\d+", "", first)
    if len(first) < 2 or len(first) > 12: return None
    if first in GENERIC_LOCAL: return None
    if len(first) <= 9:
        for g in GENERIC_LOCAL:
            if len(g) >= 4 and g in first and g != first:
                return None
    for suffix in BRAND_SUFFIXES:
        if first.endswith(suffix) and len(first) > len(suffix) + 1:
            return None
    if not re.search(r"[aeiouäöü]", first[:4]):
        return None
    # Discard hex-like blobs (>=16 chars no vowels) — likely tracking ids
    if len(first) >= 16 and not re.search(r"[aeiouAEIOU]", first):
        return None
    # Reject when first is a prefix of any company-word UNLESS first also
    # appears in the email domain (the person's own brand).
    if company:
        domain = email.split("@")[-1].lower()
        domain_root = domain.rsplit(".", 1)[0]
        first_in_domain = first in domain_root
        for word in re.split(r"\W+", company.lower()):
            if word and len(word) >= 3 and first.startswith(word) and not first_in_domain:
                return None
    # No-separator + >9 chars almost always means firstname+lastname concatenated.
    if not re.search(r"[.\-_+]", local) and len(first) > 9:
        return None
    return first.capitalize()


def main() -> int:
    # Default to the property profile; pass a slug to clean another profile
    # that uses the same Swiss-firm derivation (e.g. f2-bau).
    profile_slug = sys.argv[1] if len(sys.argv) > 1 else "f2-malergipser"
    print(f"cleaning profile: {profile_slug}")
    req = urllib.request.Request(
        f"{URL}/rest/v1/prospects?profile_slug=eq.{profile_slug}&select=id,email,first_name,company,city,website,verified&limit=500",
        headers=H_R,
    )
    rows = json.loads(urllib.request.urlopen(req).read())

    n_quarantined = n_fn_patched = n_co_patched = n_city_patched = 0
    for r in rows:
        email = r["email"]
        if is_junk_domain(email):
            # Mark unverified + unsubscribed so the strict gate and enqueue
            # both ignore it. Keep the row for audit history.
            patch = {"verified": False, "unsubscribed": True,
                     "verification_method": "auto_quarantine_junk_domain"}
            req = urllib.request.Request(
                f"{URL}/rest/v1/prospects?id=eq.{r['id']}",
                method="PATCH", data=json.dumps(patch).encode(),
                headers=H_W,
            )
            urllib.request.urlopen(req)
            n_quarantined += 1
            print(f"  Q {email}")
            continue
        patch = {}
        if not r.get("company"):
            co = derive_company(email) or derive_company_generic(email)
            if co:
                patch["company"] = co
        if not r.get("first_name"):
            fn = derive_first_name(email, r.get("company") or patch.get("company"))
            if fn:
                patch["first_name"] = fn
        if not r.get("city"):
            ci = derive_city(email) or fetch_city_from_site(r.get("website"))
            if ci:
                patch["city"] = ci
        if patch:
            req = urllib.request.Request(
                f"{URL}/rest/v1/prospects?id=eq.{r['id']}",
                method="PATCH",
                data=json.dumps(patch).encode(),
                headers=H_W,
            )
            urllib.request.urlopen(req)
            if "first_name" in patch: n_fn_patched += 1
            if "company" in patch:    n_co_patched += 1
            if "city" in patch:       n_city_patched += 1
            print(f"  + {email:50s} -> {patch}")
    print()
    print(f"quarantined junk domains: {n_quarantined}")
    print(f"first_name patched      : {n_fn_patched}")
    print(f"company patched         : {n_co_patched}")
    print(f"city patched            : {n_city_patched}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
