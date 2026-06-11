"""prospect_timezone.py - resolve a prospect's local timezone for
per-recipient send-window enforcement (8 AM-5 PM local, weekdays only).

The lookup is intentionally small and explicit. Adding a real city
database would be more accurate but adds an external dependency. The
current table covers every city we've actually scraped, plus the
common US metros for future Aureon seeds.

Resolution order:
  1. prospect['timezone']         - explicit override
  2. CITY_TZ[prospect.city]       - city lookup, case + diacritic insensitive
  3. TLD_TZ[email-tld]            - .ch/.de/.at default
  4. profile.send_window.default_timezone
  5. "UTC" if profile has nothing

Returns an IANA tz name (str). Never raises.
"""
from __future__ import annotations
import unicodedata
from typing import Optional


def _fold(s: str) -> str:
    """Case-fold + strip diacritics so 'Bern', 'BERN', 'Gümligen' all match."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.strip().lower()


# Cities we've actually seen in prospect data, plus common US metros for
# future Aureon brokerage discovery. State-level inference is tricky
# (Indianapolis is mostly Eastern but some Indiana counties are Central);
# we pick the dominant timezone for each city.
CITY_TZ: dict[str, str] = {
    # Switzerland (F2)
    "bern":          "Europe/Zurich",
    "burgdorf":      "Europe/Zurich",
    "langenthal":    "Europe/Zurich",
    "ostermundigen": "Europe/Zurich",
    "ittigen":       "Europe/Zurich",
    "gumligen":      "Europe/Zurich",
    "worb":          "Europe/Zurich",
    "thun":          "Europe/Zurich",
    "spiez":         "Europe/Zurich",
    "utzenstorf":    "Europe/Zurich",
    "zurich":        "Europe/Zurich",
    "basel":         "Europe/Zurich",
    "geneva":        "Europe/Zurich",
    "genf":          "Europe/Zurich",
    "luzern":        "Europe/Zurich",
    "lucerne":       "Europe/Zurich",
    "winterthur":    "Europe/Zurich",
    "biel":          "Europe/Zurich",
    "lausanne":      "Europe/Zurich",

    # US (Aureon)
    "indianapolis":  "America/Indiana/Indianapolis",
    "carmel":        "America/Indiana/Indianapolis",
    "fishers":       "America/Indiana/Indianapolis",
    "noblesville":   "America/Indiana/Indianapolis",
    "greenwood":     "America/Indiana/Indianapolis",
    "westfield":     "America/Indiana/Indianapolis",
    "zionsville":    "America/Indiana/Indianapolis",
    # Texas (Central)
    "houston":       "America/Chicago",
    "dallas":        "America/Chicago",
    "austin":        "America/Chicago",
    "san antonio":   "America/Chicago",
    "fort worth":    "America/Chicago",
    "el paso":       "America/Denver",   # West-of-Pecos slice in Mountain
    # Florida (Eastern)
    "miami":         "America/New_York",
    "orlando":       "America/New_York",
    "tampa":         "America/New_York",
    "jacksonville":  "America/New_York",
    "fort lauderdale":"America/New_York",
    # NY/East Coast
    "new york":      "America/New_York",
    "brooklyn":      "America/New_York",
    "boston":        "America/New_York",
    "philadelphia":  "America/New_York",
    "washington":    "America/New_York",
    "atlanta":       "America/New_York",
    "charlotte":     "America/New_York",
    "raleigh":       "America/New_York",
    "nashville":     "America/Chicago",
    "memphis":       "America/Chicago",
    # Midwest (Central)
    "chicago":       "America/Chicago",
    "minneapolis":   "America/Chicago",
    "st. louis":     "America/Chicago",
    "st louis":      "America/Chicago",
    "kansas city":   "America/Chicago",
    "milwaukee":     "America/Chicago",
    "des moines":    "America/Chicago",
    "omaha":         "America/Chicago",
    "cleveland":     "America/New_York",
    "columbus":      "America/New_York",
    "cincinnati":    "America/New_York",
    "detroit":       "America/New_York",
    "pittsburgh":    "America/New_York",
    # Mountain
    "denver":        "America/Denver",
    "salt lake city":"America/Denver",
    "boise":         "America/Boise",
    "boulder":       "America/Denver",
    "colorado springs":"America/Denver",
    # Arizona (no DST)
    "phoenix":       "America/Phoenix",
    "tucson":        "America/Phoenix",
    "scottsdale":    "America/Phoenix",
    "mesa":          "America/Phoenix",
    # Pacific
    "los angeles":   "America/Los_Angeles",
    "san diego":     "America/Los_Angeles",
    "san francisco": "America/Los_Angeles",
    "san jose":      "America/Los_Angeles",
    "oakland":       "America/Los_Angeles",
    "seattle":       "America/Los_Angeles",
    "portland":      "America/Los_Angeles",
    "las vegas":     "America/Los_Angeles",
    "sacramento":    "America/Los_Angeles",
    "honolulu":      "Pacific/Honolulu",
    # Canada
    "toronto":       "America/Toronto",
    "vancouver":     "America/Vancouver",
    "montreal":      "America/Toronto",

    # DACH / EU defaults
    "berlin":        "Europe/Berlin",
    "munich":        "Europe/Berlin",
    "munchen":       "Europe/Berlin",
    "hamburg":       "Europe/Berlin",
    "frankfurt":     "Europe/Berlin",
    "cologne":       "Europe/Berlin",
    "stuttgart":     "Europe/Berlin",
    "vienna":        "Europe/Vienna",
    "wien":          "Europe/Vienna",
    "amsterdam":     "Europe/Amsterdam",
    "rotterdam":     "Europe/Amsterdam",
    "london":        "Europe/London",
    "paris":         "Europe/Paris",
}

# TLD fallbacks. .com/.io/.net don't tell us much, but country TLDs do.
TLD_TZ: dict[str, str] = {
    "ch": "Europe/Zurich",
    "de": "Europe/Berlin",
    "at": "Europe/Vienna",
    "nl": "Europe/Amsterdam",
    "uk": "Europe/London",
    "co.uk": "Europe/London",
    "fr": "Europe/Paris",
    "it": "Europe/Rome",
    "es": "Europe/Madrid",
    "ca": "America/Toronto",     # most Canadian businesses in Eastern/Central
    "au": "Australia/Sydney",
    "nz": "Pacific/Auckland",
    "jp": "Asia/Tokyo",
    "sg": "Asia/Singapore",
}


def resolve_timezone(prospect: dict, profile_config: dict) -> str:
    """Return an IANA tz name for this prospect. Never raises."""
    # 1. Explicit override
    if prospect.get("timezone"):
        return prospect["timezone"]

    # 2. City lookup (case + diacritic insensitive)
    city = prospect.get("city") or ""
    if city:
        f = _fold(city)
        if f in CITY_TZ: return CITY_TZ[f]
        # Try a simpler form: "Bern (BE)" -> "bern"
        base = f.split(",")[0].split("(")[0].strip()
        if base in CITY_TZ: return CITY_TZ[base]

    # 3. Email TLD
    email = (prospect.get("email") or "").lower()
    if "@" in email:
        domain = email.split("@")[-1]
        # Try multi-segment TLDs first (.co.uk) then 1-segment
        parts = domain.split(".")
        for i in range(len(parts) - 1):
            tld = ".".join(parts[i + 1:])
            if tld in TLD_TZ: return TLD_TZ[tld]

    # 4. Profile default
    win = (profile_config or {}).get("send_window") or {}
    if win.get("default_timezone"):
        return win["default_timezone"]

    # 5. Last resort
    return "UTC"
