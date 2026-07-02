# -*- coding: utf-8 -*-
"""source-seller-leads.py — given a US zip code, produce a list of LIKELY-TO-LIST
seller prospects for the done-for-you seller-outreach engine, using FREE public
data only (no paid API).

This is the data core of the seller-outreach follow-through (see
docs/SELLER_OUTREACH_PLAN.md). When an agent replies with their zip, this module
sources likely sellers in that zip so the engine can run outreach on the agent's
behalf and book a listing appointment.

HONESTY FIRST (this is a trust product): free public data has patchy coverage and
NO skip-trace, so seller CONTACT info is often missing. This module NEVER
fabricates an owner, address, or contact. It returns what it can verify and
clearly reports coverage + gaps. A property with no public contact is returned
as a "signal only" lead (address + why it is likely to list) — useful to the
agent (they can door-knock / mail) even without a phone.

FREE SOURCES (pluggable providers; each returns [] gracefully on miss):
  1. probate / estate  — public probate notices + the curated estate-attorney
     lists we already maintain (referral-lists/) as a referral-source signal.
  2. pre-foreclosure   — public Notice of Default / Lis Pendens / Trustee Sale
     listings that counties or aggregators publish openly on the web.
  3. expired / FSBO    — publicly-posted for-sale-by-owner / expired-style listings.
Each provider uses the stack's existing multi-backend web search
(sequences/seed_discover.py::_search) so it inherits the working free engines
(Startpage/Mojeek/Bing/DDG) — no new keys.

PAID slot (DISABLED): a BatchData provider stub is included but OFF. Set
SELLER_LEADS_PROVIDER=batchdata + BATCHDATA_API_KEY in hostinger.env to enable
later for full find+score+skip-trace coverage. Until then it is never called.

USAGE:
    py scripts/source-seller-leads.py 46220                 # print likely sellers for a zip
    py scripts/source-seller-leads.py 46220 --limit 25 --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Reuse the working multi-backend free search from seed_discover.
try:
    from seed_discover import _search as web_search  # type: ignore
except Exception:
    web_search = None


def _load_env() -> dict:
    env = {}
    p = REPO / "sequences" / "hostinger.env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = _load_env()
PROVIDER = ENV.get("SELLER_LEADS_PROVIDER", "free").strip().lower()

# A lead is a dict with these keys; missing fields are "" not faked.
#   address, owner_name, signal, source, contact_email, contact_phone, confidence
SIGNAL_QUERIES = {
    "probate":        '{zip} probate estate sale home "for sale" OR notice',
    "pre_foreclosure":'{zip} pre-foreclosure OR "notice of default" OR "lis pendens" home',
    "expired_fsbo":   '{zip} "for sale by owner" OR fsbo home',
}

_ADDR_RX = re.compile(r"\b\d{1,6}\s+[A-Z][A-Za-z0-9.\- ]{2,40}\b"
                      r"(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|"
                      r"Blvd|Way|Pl|Place|Ter|Terrace|Cir|Circle)\b", re.I)


# ── FREE source: Craigslist for-sale-by-owner (real, often-contactable sellers) ──
# FSBO sellers self-publish: they WANT to sell and usually put a phone in the post.
# Craigslist renders results server-side (no JS wall), so a plain GET + parse works.
# Map a zip's 3-digit prefix to a craigslist region; extend _CL_SUBS for new metros.
_CL_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}
_CL_SUBS = {
    # Indiana (current agent metros)
    "460": "indianapolis", "461": "indianapolis", "462": "indianapolis",
    "463": "nwindiana", "464": "nwindiana", "465": "southbend", "466": "southbend",
    "467": "fortwayne", "468": "fortwayne", "469": "kokomo", "470": "cincinnati",
    "471": "cincinnati", "472": "bloomington", "473": "muncie", "474": "bloomington",
    "476": "evansville", "477": "evansville", "478": "terrehaute", "479": "tippecanoe",
    # major US metros (extend as needed)
    "100": "newyork", "101": "newyork", "102": "newyork", "104": "newyork", "112": "newyork",
    "021": "boston", "022": "boston", "024": "boston", "190": "philadelphia", "191": "philadelphia",
    "200": "washingtondc", "201": "washingtondc", "202": "washingtondc", "220": "washingtondc",
    "300": "atlanta", "301": "atlanta", "303": "atlanta", "331": "miami", "332": "miami", "333": "miami",
    "327": "orlando", "328": "orlando", "335": "tampa", "336": "tampa", "280": "charlotte",
    "370": "nashville", "371": "nashville", "372": "nashville", "432": "columbus", "441": "cleveland",
    "481": "detroit", "482": "detroit", "483": "detroit", "553": "minneapolis", "554": "minneapolis",
    "606": "chicago", "607": "chicago", "630": "stlouis", "631": "stlouis", "641": "kansascity",
    "750": "dallas", "751": "dallas", "752": "dallas", "770": "houston", "772": "houston",
    "773": "houston", "782": "sanantonio", "786": "austin", "787": "austin",
    "800": "denver", "801": "denver", "802": "denver", "850": "phoenix", "852": "phoenix",
    "889": "lasvegas", "890": "lasvegas", "891": "lasvegas", "900": "losangeles", "902": "losangeles",
    "904": "losangeles", "906": "losangeles", "919": "sandiego", "920": "sandiego", "921": "sandiego",
    "940": "sfbay", "941": "sfbay", "945": "sfbay", "950": "sfbay", "956": "sacramento",
    "970": "portland", "971": "portland", "980": "seattle", "981": "seattle", "982": "seattle",
}
_CL_DETAIL_RX = re.compile(r"https?://[\w.-]+\.craigslist\.org/reo/d/[\w-]+/\d+\.html")
_CL_MAPADDR_RX = re.compile(r"mapaddress[^>]*>\s*([^<]+?)\s*<", re.I)
_CL_TITLE_RX = re.compile(r"<title>(.*?)</title>", re.S | re.I)
_CL_BODY_RX = re.compile(r'id="postingbody"[^>]*>(.*?)</section>', re.S | re.I)
# FSBO posters write phones every which way: (317) 555-1234, 317-555-1234,
# 317.555.1234, 317 555 1234, and bare 3175551234. Separators optional; word
# boundaries keep it from matching inside a longer number (parcel id / mls).
_PHONE_RX = re.compile(r"(?<!\d)\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)")
_STREET_RX = re.compile(
    r"\d{2,6}\s+[A-Z][A-Za-z0-9.\s]{2,40}?\b"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Ln|Lane|Ct|Court|Blvd|Way|Pl|Place|Cir|Circle|Ter|Terrace|Pkwy)\b")
# Buyers/wholesalers troll the FSBO category ("we buy houses"). They are not
# sellers to hand an agent, so drop any listing whose title reads like a buyer.
_CL_NOISE_RX = re.compile(
    r"\b(we buy|cash for|cah for|cash offer|sell (?:your|my) (?:house|home)|buy (?:houses|homes|your)|"
    r"any condition|we pay cash|fast cash|ugly hous|investor|wholesale|sell (?:fast|quick)|"
    r"quick (?:cash|sale)|need to sell|wanting to sell|"
    r"for[\s-]?rent|rental|for[\s-]?lease|sublet|roommate|room for rent|apartment|commercial)\b", re.I)


def _http_get(url: str, timeout: int = 20) -> str:
    with urllib.request.urlopen(urllib.request.Request(url, headers=_CL_UA), timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def _craigslist_fsbo(zip_code: str, limit: int) -> tuple[list[dict], list[str]]:
    """Scrape Craigslist 'real estate - by owner' near the zip. Each listing's
    detail page yields the address (when the seller mapped it) and a phone (when
    they posted one). Returns (leads, notes)."""
    sub = _CL_SUBS.get(zip_code[:3])
    if not sub:
        return [], [f"craigslist: zip prefix {zip_code[:3]} not mapped to a CL region (extend _CL_SUBS)"]
    search = f"https://{sub}.craigslist.org/search/reo?postal={zip_code}&search_distance=25"
    try:
        page = _http_get(search)
    except Exception as e:
        return [], [f"craigslist search failed for {sub}: {str(e)[:100]}"]
    urls: list[str] = []
    for u in _CL_DETAIL_RX.findall(page):
        if f"//{sub}.craigslist.org/" not in u:
            continue  # nearby-region result — keep it local to the agent's metro
        if _CL_NOISE_RX.search(u):
            continue  # rental / lease / investor slug in the URL itself
        if u not in urls:
            urls.append(u)
    if not urls:
        return [], [f"craigslist: 0 FSBO listings near {zip_code} ({sub})"]
    leads: list[dict] = []
    seen_addr: set[str] = set()
    for u in urls:
        if len(leads) >= limit:
            break
        try:
            d = _http_get(u)
        except Exception:
            continue
        mt = _CL_TITLE_RX.search(d)
        title = re.sub(r"\s+", " ", mt.group(1)).split(" - ")[0].strip() if mt else ""
        if not title or _CL_NOISE_RX.search(title):
            continue  # investor / "we buy houses" ad, not a for-sale-by-owner seller
        ma = _CL_MAPADDR_RX.search(d)
        addr = ma.group(1).strip() if ma else ""
        if not addr:
            ms = _STREET_RX.search(title)
            addr = ms.group(0).strip() if ms else ""
        addr = addr.replace("&amp;", "&").replace("&#39;", "'").replace("&#x27;", "'")
        if addr and not re.search(r"\d", addr):
            addr = ""  # neighborhood / cross-street, not a real street address — drop it
        mb = _CL_BODY_RX.search(d)
        body = re.sub(r"<[^>]+>", " ", mb.group(1)) if mb else ""
        mp = _PHONE_RX.search(body)
        phone = mp.group(0).strip() if mp else ""
        if not (addr or phone):
            continue  # nothing actionable for the agent
        akey = re.sub(r"[^a-z0-9]", "", re.sub(r"\bnear\b.*", "", addr.lower())) or u
        if akey in seen_addr:
            continue  # same property posted multiple times (normalized address match)
        seen_addr.add(akey)
        leads.append({
            "address": addr,
            "owner_name": "",
            "signal": "fsbo",
            "source": u,                       # the listing IS the contact path (CL relays messages)
            "contact_email": "",
            "contact_phone": phone,
            "confidence": "phone" if phone else "via_listing",
            "needs_research": not phone,
        })
    return leads, [f"craigslist FSBO ({sub}): {len(urls)} listings, parsed {len(leads)}, "
                   f"{sum(1 for l in leads if l['contact_phone'])} with phone"]


# ── FREE source #2: county ASSESSOR parcels (the absentee-owner signal) ───────
# This is the SAME county assessor data ATTOM/CoreLogic license and resell, pulled
# free from each county's public ArcGIS REST endpoint. The absentee-owner flag
# (owner mailing state != the property's state) is the #1 motivated-seller signal.
# Output is direct-mail-ready: property address + owner name + owner mailing
# address + assessed value. Field names differ per county, so each county is one
# config entry: drop in its REST layer URL + the field-name map to add it.
COUNTY_PARCELS = {
    "marion": {  # Indianapolis (confirmed: real owner+mailing+value data)
        "url": "https://gis.indy.gov/server/rest/services/MapIndy/MapIndyProperty/MapServer/10",
        "zip": "ZIPCODE", "owner": "FULLOWNERNAME", "ostate": "OWNERSTATE", "ocity": "OWNERCITY",
        "omail": "OWNERADDRESS", "ozip": "OWNERZIP", "stname": "FULL_STNAME", "stno": "STNUMBER",
        "city": "CITY", "pstate": "STATE", "val": "ASSESSORYEAR_TOTALAV",
        "klass": "PROPERTY_CLASS", "res": "RESIDENTIAL",
    },
    "delaware": {  # Muncie / Yorktown 47383
        "url": "https://services.arcgis.com/VyRjdyMziYNF5Bwe/arcgis/rest/services/ParcelWebpublish/FeatureServer/0",
        "zip": "Zip", "owner": "OwnerName", "ostate": "OwnerState", "ocity": "OwnerCity",
        "omail": "OwnerAddress", "ozip": "OwnerZip", "stname": "StreetAddress", "stno": None,
        "city": "City", "pstate": "State", "val": None,
        "klass": None, "res": None,
    },
    "hamilton": {  # Noblesville / Fishers / Carmel (confirmed reachable from the VPS 2026-07-02)
        "url": "https://gis1.hamiltoncounty.in.gov/arcgis/rest/services/HamCoParcelsPublic/FeatureServer/0",
        "zip": "LOCZIP", "owner": "OWNNAME", "ostate": "OWNSTATE", "ocity": "OWNCITY",
        "omail": "OWNADDRESS", "ozip": "OWNZIP", "stname": "LOCADDRESS", "stno": None,
        "city": "LOCCITY", "pstate": None, "val": None,  # no property-state field -> resolves to IN from the zip
        "klass": "PROPCLASS", "res": None,
    },
}
# Indiana zip -> county. 3-digit prefix first, exact-zip overrides where a prefix spans counties.
# These are the hand-mapped seeds; for any OTHER zip we auto-resolve via _zip_to_county
# (zippopotam + Census geocoder) and auto-discover the parcel layer (_discover_county_layer).
_ZIP_COUNTY_PFX = {"460": "marion", "461": "marion", "462": "marion"}
_ZIP_COUNTY_EXACT = {"47383": "delaware", "47302": "delaware", "47303": "delaware", "47304": "delaware", "47305": "delaware",
    # Hamilton county (overrides the 460/461-> marion prefix seed for these): Noblesville 46060/62/64,
    # Fishers 46037/38, Carmel 46032/33, Westfield 46074, Cicero 46034.
    "46060": "hamilton", "46062": "hamilton", "46064": "hamilton", "46037": "hamilton", "46038": "hamilton",
    "46032": "hamilton", "46033": "hamilton", "46074": "hamilton", "46034": "hamilton"}

# Persistent self-building registry: discovered county -> {url + field map} entries are
# cached here so each county's ArcGIS layer is discovered ONCE, then reused every run.
_CACHE_PATH = REPO / "referral-lists" / "county_parcels.json"
_ZIPCNTY_CACHE_PATH = REPO / "referral-lists" / "zip_county.json"


def _load_cache(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cache(path: Path, data: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    except Exception:
        pass  # cache is an optimization; a write failure must never break sourcing


# Merge any cached discovered counties into COUNTY_PARCELS at import (hand-mapped wins).
for _ck, _cv in _load_cache(_CACHE_PATH).items():
    COUNTY_PARCELS.setdefault(_ck, _cv)


def _zip_to_county(zip_code: str):
    """Resolve a US zip -> (county_key, state_abbr) using FREE keyless services:
    zippopotam (zip -> place + lat/lon + state) then the Census geocoder
    (lat/lon -> county name). Cached to zip_county.json. Returns (None, None) on miss."""
    cache = _load_cache(_ZIPCNTY_CACHE_PATH)
    if zip_code in cache:
        c = cache[zip_code]
        return c.get("county"), c.get("state")
    try:
        zp = json.loads(urllib.request.urlopen(
            urllib.request.Request("https://api.zippopotam.us/us/" + zip_code, headers=_CL_UA), timeout=20
        ).read().decode("utf-8", "replace"))
        place = (zp.get("places") or [{}])[0]
        lat, lon = place.get("latitude"), place.get("longitude")
        state = place.get("state abbreviation") or ""
        if not (lat and lon):
            return None, None
        geo = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://geocoding.geo.census.gov/geocoder/geographies/coordinates?x=%s&y=%s"
            "&benchmark=Public_AR_Current&vintage=Current_Current&layers=Counties&format=json" % (lon, lat),
            headers=_CL_UA), timeout=25).read().decode("utf-8", "replace"))
        counties = geo.get("result", {}).get("geographies", {}).get("Counties", [])
        if not counties:
            return None, None
        # "Marion County" -> "marion" (the registry key convention)
        county = re.sub(r"\s+county$", "", counties[0].get("BASENAME") or counties[0].get("NAME") or "", flags=re.I)
        county = re.sub(r"[^a-z0-9]+", "", county.lower())
        if not county:
            return None, None
        cache[zip_code] = {"county": county, "state": state}
        _save_cache(_ZIPCNTY_CACHE_PATH, cache)
        return county, state
    except Exception:
        return None, None


# Owner-field heuristic: a parcel layer is "owner-bearing" if it has a name-like field
# AND (a mailing-address or owner-location field). Property location fields let us filter by zip.
_F_OWNER = re.compile(r"^(full?owner|owner.?name|ownername|owner|deeded?owner|taxpayer|grantee)$", re.I)
_F_OWNER_LOOSE = re.compile(r"owner.*name|name.*owner|taxpayer|grantee", re.I)
# Combined "City ST ZIP" packed fields, detected FIRST so a plain state/zip matcher never
# steals them. A field whose name contains city AND state AND zip is a combined field.
_F_OCSZ = re.compile(r"owner.*city.*state.*zip|owner.*csz|owner_city_st|ownercitystatezip", re.I)
_F_PCSZ = re.compile(r"(prop|parcel|situs|site).*city.*state.*zip|prop.*csz|property_city_st", re.I)
# Plain single-purpose fields. Negative lookahead keeps them from matching a combined CSZ field.
_F_OSTATE = re.compile(r"^(?!.*zip)(?=.*(owner|mail)).*state", re.I)
_F_OMAIL = re.compile(r"owner.*(street|addr)|mail.*(street|addr)", re.I)
_F_OCITY = re.compile(r"^(?!.*zip)(?=.*(owner|mail)).*city", re.I)
_F_OZIP = re.compile(r"^(?!.*(city|state)).*(owner|mail).*zip|(owner|mail).*zip(code)?$", re.I)
_F_PZIP = re.compile(r"^(?!.*(owner|mail))(?!.*(city|state)).*zip", re.I)  # property zip, not owner's, not combined
_F_PSTNAME = re.compile(r"(parcel|situs|site|prop).*street|full.?st(name)?|situs|site.?addr|prop.*addr|^street$", re.I)
_F_PSTNO = re.compile(r"(parcel|situs|site|prop).*(address)?(number|no)|st(reet)?.?(no|num)|^stno$|house.?num", re.I)
_F_PCITY = re.compile(r"^(?!.*(owner|mail))(?!.*zip).*(parcel|situs|site|prop).*city|^city$", re.I)
_F_PSTATE = re.compile(r"^(?!.*(owner|mail))(?!.*zip).*(parcel|situs|site|prop).*state|^state$", re.I)
_F_VAL = re.compile(r"tot.*assess|assess.*tot|total.*val|av$|assessed", re.I)

# Context-enrichment fields (free, already in the assessor data, currently unused). Each maps a
# human label -> a regex; _context_fields auto-detects whichever the county layer happens to expose,
# so this generalises across counties without per-county config. These tell the agent WHY a parcel
# is a good listing target (long ownership + low basis = high equity = motivated to sell).
_CTX_FIELDS = [
    ("last sale",   re.compile(r"(latest|last).?sale.?(price|amt|amount)|saleprice|saleamt", re.I)),
    ("sale date",   re.compile(r"(latest|last).?sale.?date|saledate|deed.?date|transfer.?date", re.I)),
    ("sqft",        re.compile(r"(est|calc|living|finished|total)?.?sq.?(ft|feet)|squarefeet|gla$", re.I)),
    ("year built",  re.compile(r"year.?built|yr.?built|yearblt|actualyearbuilt|^yearbuilt$", re.I)),
    ("beds",        re.compile(r"(num.*)?bed(room)?s?$|bedrm", re.I)),
    ("baths",       re.compile(r"(num.*)?(full)?bath(room)?s?$|bathrm", re.I)),
    ("acreage",     re.compile(r"^(legal|total|calc(ulated)?|gis)?.?acre(age|s)?$", re.I)),
    ("land value",  re.compile(r"^land.?val(ue)?$|landvalue|landassess", re.I)),
    ("improvement", re.compile(r"^improv(e|ement)?.?val(ue)?$|improvval|totimprov|bldg.?val", re.I)),
    ("homestead",   re.compile(r"^hom(e)?stead$|homstead|owner.?occ(upied)?", re.I)),
    ("use class",   re.compile(r"prop.*class.?desc|propertyclassdesc|class.?desc|landuse.?desc", re.I)),
]


def _pick(fields, *patterns):
    """First field name matching any pattern (in order), else None."""
    for pat in patterns:
        for f in fields:
            if pat.search(f):
                return f
    return None


def _context_fields(fields: list) -> dict:
    """Auto-detect which free context fields (last sale, sqft, year built, equity, homestead,
    use class) this county layer exposes. Returns {label: field_name}. Generalises across
    counties so enrichment needs no per-county config."""
    out = {}
    for label, pat in _CTX_FIELDS:
        f = _pick(fields, pat)
        if f and f not in out.values():
            out[label] = f
    return out


def _fmt_context(a: dict, ctx: dict) -> str:
    """Render the detected context fields for one parcel into a compact agent-readable string,
    e.g. 'built 1998 | 2,140 sqft | last sold $182,000 (2003) | homestead: N'. Skips blanks."""
    parts = []
    for label, fld in ctx.items():
        v = a.get(fld)
        if v in (None, "", " "):
            continue
        sv = str(v).strip()
        if label in ("last sale", "land value", "improvement"):
            try:
                sv = "$%s" % format(int(float(sv)), ",")
            except Exception:
                pass
            parts.append("%s %s" % (label, sv))
        elif label == "sale date":
            # ArcGIS epoch-ms dates -> year; else leave as-is.
            try:
                yr = 1970 + int(int(sv) / 31557600000)
                sv = str(yr) if 1900 < yr < 2100 else sv
            except Exception:
                pass
            parts.append("sold %s" % sv)
        elif label == "homestead":
            parts.append("homestead: %s" % sv[:1].upper())
        elif label == "sqft":
            try:
                sv = format(int(float(sv)), ",")
            except Exception:
                pass
            parts.append("%s sqft" % sv)
        elif label == "year built":
            parts.append("built %s" % sv)
        else:
            parts.append("%s %s" % (label, sv))
    return " | ".join(parts)


def _probe_layer_fields(layer_url: str):
    """Fetch a Feature Service layer's field list. Returns [] on any failure."""
    try:
        d = json.loads(urllib.request.urlopen(urllib.request.Request(
            layer_url.rstrip("/") + "?f=json", headers=_CL_UA), timeout=25).read().decode("utf-8", "replace"))
        return [f.get("name") for f in d.get("fields", []) if f.get("name")]
    except Exception:
        return []


def _build_field_map(layer_url: str, fields: list):
    """Given a layer's fields, build a COUNTY_PARCELS-style config if it is owner-bearing
    and zip-filterable. Supports both separate-field and combined "City ST ZIP" layouts.
    Returns the config dict or None if the layer can't be used."""
    owner = _pick(fields, _F_OWNER) or _pick(fields, _F_OWNER_LOOSE)
    if not owner:
        return None
    # Combined packed fields first, so the plain zip/state matchers below can't grab them.
    ocsz = _pick(fields, _F_OCSZ)
    pcsz = _pick(fields, _F_PCSZ)
    pzip = _pick(fields, _F_PZIP)
    ostate = _pick(fields, _F_OSTATE)
    # Need a way to filter by zip: either a property-zip field, or a combined property CSZ field.
    if not pzip and not pcsz:
        return None
    # Need an absentee signal: either a separate owner-state field, or a combined owner CSZ field.
    if not ostate and not ocsz:
        return None
    stname = _pick(fields, _F_PSTNAME)
    if not stname and not pcsz:
        return None
    cfg = {
        "url": layer_url.rstrip("/"),
        "owner": owner,
        "ostate": ostate, "ocity": _pick(fields, _F_OCITY), "omail": _pick(fields, _F_OMAIL),
        "ozip": _pick(fields, _F_OZIP), "ocsz": ocsz,
        "zip": pzip, "stname": stname, "stno": _pick(fields, _F_PSTNO),
        "city": _pick(fields, _F_PCITY), "pstate": _pick(fields, _F_PSTATE), "pcsz": pcsz,
        "val": _pick(fields, _F_VAL), "klass": None, "res": None,
        "ctx": _context_fields(fields),  # free enrichment fields this layer exposes
        "_discovered": True,
    }
    return cfg


def _layer_covers_zip(cfg: dict, zip_code: str, state: str) -> bool:
    """Empirical accept-test: query the candidate layer for THIS zip and require it returns
    at least one parcel. This rejects same-name wrong-state counties (e.g. Monroe NY when we
    want Monroe IN) far more reliably than schema guessing. Also confirms the field map works."""
    import urllib.parse as _up
    try:
        if cfg.get("pcsz"):
            where = "%s LIKE '%%%s%%'" % (cfg["pcsz"], zip_code)
        elif cfg.get("zip"):
            where = "%s='%s'" % (cfg["zip"], zip_code)
        else:
            return False
        url = (cfg["url"] + "/query?where=" + _up.quote(where)
               + "&outFields=" + _up.quote(",".join(f for f in [cfg.get("pcsz"), cfg.get("pstate")] if f) or "*")
               + "&resultRecordCount=1&returnGeometry=false&f=json")
        data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=_CL_UA), timeout=30)
                          .read().decode("utf-8", "replace"))
        feats = data.get("features", [])
        if not feats:
            return False
        # If the layer exposes a property-state, make sure it matches the resolved state.
        a = feats[0].get("attributes", {})
        if cfg.get("pstate") and a.get(cfg["pstate"]):
            return str(a[cfg["pstate"]]).strip().upper()[:2] == (state or "").upper()[:2]
        if cfg.get("pcsz") and a.get(cfg["pcsz"]) and state:
            return state.upper() in str(a[cfg["pcsz"]]).upper()
        return True  # zip matched and no state field to contradict it
    except Exception:
        return False


# US state abbreviation -> full name (county parcel layers index far better on the full name).
_STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri",
    "MT": "Montana", "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont",
    "VA": "Virginia", "WA": "Washington", "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def _arcgis_service_bases(query: str, num: int = 20):
    """Search ArcGIS Online; return ordered, de-duplicated Feature Service base URLs."""
    bases, seen = [], set()
    try:
        res = json.loads(urllib.request.urlopen(urllib.request.Request(
            "https://www.arcgis.com/sharing/rest/search?q=" + urllib.request.quote(query)
            + "&f=json&num=%d" % num, headers=_CL_UA), timeout=25).read().decode("utf-8", "replace"))
        for item in res.get("results", []):
            if item.get("type") != "Feature Service":
                continue
            base = (item.get("url") or "").rstrip("/")
            if base.lower().startswith("http") and base not in seen:
                seen.add(base)
                bases.append(base)
    except Exception:
        pass
    return bases


def _discover_county_layer(county: str, state: str, zip_code: str = ""):
    """Auto-discover a county's owner-bearing parcel ArcGIS layer via ArcGIS Online search.
    Tries several query phrasings (county-name layers index inconsistently), probes each
    Feature Service's layers with the owner-field heuristic, then EMPIRICALLY confirms the
    layer returns parcels for the target zip+state before accepting. Caches the hit (or a
    confirmed None == no_rest). Returns the config dict or None."""
    cache = _load_cache(_CACHE_PATH)
    if county in cache:
        return cache[county] if cache[county] else None  # cached None == known no_rest
    cname = county.capitalize()
    state_full = _STATE_NAMES.get((state or "").upper(), state)
    queries = [
        "%s County %s parcels" % (cname, state_full),
        "%s %s parcel owner" % (cname, state_full),
        "%s County %s parcel" % (cname, state_full),
    ]
    found, tried = None, set()
    try:
        bases = []
        for q in queries:
            for b in _arcgis_service_bases(q):
                if b not in tried:
                    bases.append(b)
        for base in bases:
            if found:
                break
            if base in tried:
                continue
            tried.add(base)
            # A Feature Service hosts numbered layers; the owner-bearing parcel layer is
            # usually 0 but can be deeper — probe 0..6 and let the zip-probe be the gate.
            for li in range(0, 7):
                flds = _probe_layer_fields("%s/%d" % (base, li))
                if not flds:
                    continue
                cfg = _build_field_map("%s/%d" % (base, li), flds)
                if cfg and (not zip_code or _layer_covers_zip(cfg, zip_code, state)):
                    found = cfg
                    break
    except Exception:
        found = None
    cache[county] = found  # cache the hit, OR cache None to record a confirmed no_rest miss
    _save_cache(_CACHE_PATH, cache)
    return found


def _county_for_zip(zip_code: str):
    """Resolve zip -> county (authoritatively, via the geocoder) and ensure the county's
    parcel layer is registered: hand-mapped configs win, else auto-discover. Returns a
    COUNTY_PARCELS key or None.

    NOTE: we DON'T trust the 3-digit-prefix seeds to name the county (a prefix like 460xx
    spans Marion AND Hamilton/Carmel), only as a last resort if the geocoder is unreachable."""
    county, state = _zip_to_county(zip_code)
    if county:
        if county in COUNTY_PARCELS:
            return county  # hand-mapped (marion/delaware) or already-discovered + cached
        cfg = _discover_county_layer(county, state, zip_code)
        if cfg:
            COUNTY_PARCELS[county] = cfg
            return county
        return None  # no public REST layer for this county -> caller falls back to FSBO
    # Geocoder miss: fall back to the hand-mapped exact-zip / prefix seeds.
    return _ZIP_COUNTY_EXACT.get(zip_code) or _ZIP_COUNTY_PFX.get(zip_code[:3])


# Businesses/LLCs have no personal people-search record — no skip-trace link for them.
_BIZ_RX = re.compile(r"\b(LLC|L\.?L\.?C|INC|CORP|CORPORATION|TRUST|LP|L\.?P|COMPANY|BANK|HOLDINGS|"
                     r"PROPERTIES|ENTERPRISES|PARTNERS|FUND|VENTURES|ASSOCIATION|REVOCABLE|LIVING TRUST)\b", re.I)


def _skiptrace_link(owner: str, city: str, state: str) -> str:
    """A pre-filled people-search URL a HUMAN opens to read the phone. We do NOT
    scrape or query it here, we just build the link; the operator clicks it."""
    if not owner or _BIZ_RX.search(owner):
        return ""
    if "," in owner:
        last, rest = owner.split(",", 1)
        first = rest.strip().split(" ")[0] if rest.strip() else ""
    else:
        parts = owner.split()
        first, last = (parts[0], parts[-1]) if len(parts) >= 2 else ("", owner)
    first = re.sub(r"[^A-Za-z]", "", first).lower()
    last = re.sub(r"[^A-Za-z]", "", last).lower()
    if not first or not last:
        return ""
    loc = re.sub(r"[^a-z0-9]+", "-", ("%s-%s" % (city, state)).lower()).strip("-")
    return "https://www.fastpeoplesearch.com/name/%s-%s_%s" % (first, last, loc)


def _county_assessor(zip_code: str, limit: int) -> tuple[list[dict], list[str]]:
    """Query the county parcel ArcGIS layer for ABSENTEE owners (owner mailing
    state != the property state) in this zip. Real motivated sellers, free,
    direct-mail-ready. Supports both separate-field layouts (Marion/Delaware) and
    combined "City ST ZIP" layouts (Monroe-style, discovered counties)."""
    import urllib.parse as _up
    cnty = _county_for_zip(zip_code)
    cfg = COUNTY_PARCELS.get(cnty) if cnty else None
    if not cfg:
        return [], ["county assessor: zip %s — no public parcel REST layer (county not mapped / no_rest)" % zip_code]
    # Property state for the absentee comparison: from the zip->county cache (auto-resolved
    # zips), else the hand-mapped Indiana seeds default to IN.
    _zc = _load_cache(_ZIPCNTY_CACHE_PATH).get(zip_code) or {}
    pstate = (_zc.get("state") or "IN").upper()
    combined = bool(cfg.get("pcsz"))             # property zip lives inside a combined "City ST ZIP" field
    owner_combined = bool(cfg.get("ocsz"))       # owner state lives inside a combined owner "City ST ZIP" field
    # Context fields: cached on discovered cfgs; detect on the fly for hand-mapped ones.
    ctx = cfg.get("ctx")
    if ctx is None:
        ctx = _context_fields(_probe_layer_fields(cfg["url"]))
        cfg["ctx"] = ctx  # memoise for the rest of this process
    out = [f for f in [cfg.get("owner"), cfg.get("ostate"), cfg.get("ocity"), cfg.get("omail"),
                       cfg.get("ozip"), cfg.get("ocsz"), cfg.get("stname"), cfg.get("stno"),
                       cfg.get("city"), cfg.get("pstate"), cfg.get("zip"), cfg.get("pcsz"), cfg.get("val")]
           + list(ctx.values()) if f]

    # WHERE: filter to the zip (separate field == exact, combined field == LIKE).
    if combined:
        where = "%s LIKE '%%%s%%'" % (cfg["pcsz"], zip_code)
    else:
        where = "%s='%s'" % (cfg["zip"], zip_code)
    # Absentee filter only when owner state is a separate queryable field; combined owner
    # CSZ is filtered in Python below (can't reliably LIKE a state out of a packed string).
    if cfg.get("ostate") and not owner_combined:
        where += " AND %s NOT IN ('%s','')" % (cfg["ostate"], pstate)
    if cfg.get("res") and cfg.get("klass"):
        where += " AND %s='%s'" % (cfg["klass"], cfg["res"])
    # When the absentee filter runs in SQL (separate owner-state field), a small fetch is
    # enough. When it runs in Python (combined owner CSZ), we must pull a LARGE batch or the
    # in-state majority truncates the absentee owners out before we ever see them.
    fetch = max(limit * 3, 30) if (cfg.get("ostate") and not owner_combined) else 2000
    url = (cfg["url"] + "/query?where=" + _up.quote(where) + "&outFields=" + _up.quote(",".join(out))
           + "&resultRecordCount=%d&returnGeometry=false&f=json" % fetch)
    try:
        data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=_CL_UA), timeout=35).read().decode("utf-8", "replace"))
    except Exception as e:
        return [], ["county assessor (%s) query failed: %s" % (cnty, str(e)[:110])]

    def s(a, key):
        v = a.get(cfg[key]) if cfg.get(key) else None
        return str(v).strip() if v not in (None, "") else ""

    def _split_csz(val):
        """'Carmel IN 46032' / 'CARMEL, IN, 46032' -> (city, state, zip)."""
        m = re.search(r"^(.*?)[,\s]+([A-Z]{2})[,\s]+(\d{5})", (val or "").strip(), re.I)
        if m:
            return m.group(1).strip(" ,"), m.group(2).upper(), m.group(3)
        return (val or "").strip(), "", ""

    leads = []
    for feat in data.get("features", []):
        if len(leads) >= limit:
            break
        a = feat.get("attributes", {})
        owner = s(a, "owner")
        # Property location (separate fields or split from the combined property CSZ).
        if combined:
            p_city, p_state, p_zip = _split_csz(s(a, "pcsz"))
            prop = s(a, "stname")
        else:
            p_city, p_state, p_zip = s(a, "city"), s(a, "pstate"), s(a, "zip")
            prop = " ".join(x for x in [s(a, "stno"), s(a, "stname")] if x).strip()
        if combined and p_zip and p_zip != zip_code:
            continue  # LIKE can over-match (zip as a substring elsewhere) — enforce exact zip
        prop_full = ", ".join(x for x in [prop, p_city, ("%s %s" % (p_state or pstate, p_zip)).strip()] if x).strip(", ")
        if not prop or not owner:
            continue
        # Owner mailing (separate fields or split from the combined owner CSZ).
        if owner_combined:
            o_city, o_state, o_zip = _split_csz(s(a, "ocsz"))
            o_mail = s(a, "omail")
        else:
            o_city, o_state, o_zip = s(a, "ocity"), s(a, "ostate"), s(a, "ozip")
            o_mail = s(a, "omail")
        # Combined-owner absentee filter (done here since it couldn't be a SQL WHERE).
        if owner_combined and o_state and o_state.upper() in (pstate.upper(), ""):
            continue
        # Quality filter: drop parcels that aren't sellable homes — government/exempt land and
        # raw/vacant lots (improvement value 0 == no building). These are noise to a listing agent.
        use_class = (s(a, "klass") or (a.get(ctx.get("use class")) if ctx.get("use class") else "") or "")
        uc = str(use_class)
        # Drop non-sellable / non-residential parcels: exempt/government land, vacant lots, and
        # commercial/utility/agricultural classes. Keep dwellings, condos, residential, mobile homes.
        if re.search(r"\bexempt\b|government|municipal|federal|\bstate of\b|vacant|right.?of.?way|"
                     r"common area|utility|water (distribution|company)|sewer|pipeline|railroad|"
                     r"\bcommercial\b|industrial|warehouse|agricultur|farm|\bcrop\b|timber|mineral|"
                     r"church|cemetery|school|\bpark\b|conservation", uc, re.I) and not \
           re.search(r"dwell|residential|condo|apartment|mobile|manufactured home|1 family|2 family|"
                     r"single.?family|duplex|townhouse|res\b", uc, re.I):
            continue
        if _BIZ_RX.search(owner) and re.search(r"united states|department|county of|city of|township|school|church|cemetery", owner, re.I):
            continue
        # Clear non-residential owners (utilities, agribusiness, railroads, telecom, municipal)
        # are never home-sellers and only pollute a direct-mail run — drop even without a corp suffix.
        if re.search(r"\b(power|electric|energy co|utilit|telephone|telecom|cellular|pipeline|"
                     r"railroad|railway|gas (co|company|service)|water (co|company|works|district)|"
                     r"ag solutions|agri[\s-]|farms? (inc|llc)|petroleum|oil (co|company)|"
                     r"sanitar|municipal|authority)\b", owner, re.I):
            continue
        if ctx.get("improvement"):
            iv = a.get(ctx["improvement"])
            try:
                if iv is not None and float(iv) <= 0:
                    continue  # raw land, no structure to list
            except Exception:
                pass
        mail = ", ".join(x for x in [o_mail, o_city, ("%s %s" % (o_state, o_zip)).strip()] if x).strip(", ")
        src = ("Owner mailing: " + mail) if mail else ""
        if cfg.get("val") and a.get(cfg["val"]):
            try:
                src += (" | AV $%s" % format(int(a[cfg["val"]]), ",")) if src else ("AV $%s" % format(int(a[cfg["val"]]), ","))
            except Exception:
                pass
        st_link = _skiptrace_link(owner, o_city, o_state)
        if st_link:
            src += (" | phone: " + st_link) if src else ("phone: " + st_link)
        # Free enrichment: property context (sale history, sqft, year, equity, homestead) that
        # the assessor layer already carries — tells the agent WHY this is a listing target.
        context = _fmt_context(a, ctx)
        # Out-of-state absentee owners (owner state != property state) are the hardest to
        # self-manage and the most motivated to sell — the strongest FREE intent signal the
        # bare assessor record carries. Rank them ahead of in-state absentees for direct mail.
        out_of_state = bool(o_state and pstate and o_state.strip().upper()[:2] != pstate.strip().upper()[:2])
        leads.append({
            "address": prop_full, "owner_name": owner, "signal": "absentee owner",
            "source": src, "contact_email": "", "contact_phone": "",
            "context": context,
            "intent": "out-of-state owner" if out_of_state else "in-state absentee",
            "intent_score": 2 if out_of_state else 1,
            "confidence": "owner_mailing", "needs_research": True,
        })
    leads.sort(key=lambda l: l.get("intent_score", 0), reverse=True)  # highest intent leads the run
    oos = sum(1 for l in leads if l.get("intent_score") == 2)
    return leads, ["county assessor (%s): %d absentee-owner parcels in %s (%d out-of-state)"
                   % (cnty, len(leads), zip_code, oos)]


def lookup_address(address: str, zip_code: str = "") -> dict:
    """Look up ONE specific property by street address in the county assessor layer and
    return its real public data for a home-value report: assessed value, last sale,
    sqft, equity context. FREE county data, the same source ATTOM/Zillow license. Returns
    {found, address, assessed_value, context, county, note}. Never fabricates: found=False
    when the county isn't mapped or the parcel isn't located.

    Powers the consented home-value funnel (build-home-value-funnel.py): a homeowner opts in
    with their address, this turns it into a real number to send back."""
    import urllib.parse as _up
    address = (address or "").strip()
    # Pull a 5-digit zip out of the address if not passed separately.
    if not re.fullmatch(r"\d{5}", zip_code or ""):
        mz = re.search(r"\b(\d{5})\b", address)
        zip_code = mz.group(1) if mz else ""
    if not zip_code:
        return {"found": False, "address": address, "note": "no zip in address"}
    cnty = _county_for_zip(zip_code)
    cfg = COUNTY_PARCELS.get(cnty) if cnty else None
    if not cfg:
        return {"found": False, "address": address, "note": "county not mapped for %s" % zip_code}
    ctx = cfg.get("ctx")
    if ctx is None:
        ctx = _context_fields(_probe_layer_fields(cfg["url"]))
        cfg["ctx"] = ctx
    # Extract the street NAME token(s) from the address (drop the leading house number + trailing city/zip).
    m = re.match(r"\s*(\d{1,6})\s+(.+)", address)
    if not m:
        return {"found": False, "address": address, "note": "could not parse a street number"}
    stno = m.group(1)
    rest = m.group(2)
    # street name = first 1-2 words after the number, uppercased, stripped of unit/city tails.
    sn = re.sub(r"[,#].*$", "", rest).strip()
    sn_token = re.sub(r"[^A-Za-z0-9 ].*$", "", sn).strip().split()
    street_like = " ".join(sn_token[:3]).upper() if sn_token else ""
    if not street_like:
        return {"found": False, "address": address, "note": "could not parse a street name"}
    combined = bool(cfg.get("pcsz"))
    out = [f for f in [cfg.get("owner"), cfg.get("stname"), cfg.get("stno"), cfg.get("city"),
                       cfg.get("pstate"), cfg.get("zip"), cfg.get("pcsz"), cfg.get("val")]
           + list(ctx.values()) if f]
    if combined:
        where = "%s LIKE '%%%s%%' AND %s LIKE '%%%s%%'" % (cfg["pcsz"], zip_code, cfg["stname"], street_like.split()[0])
    else:
        where = "%s='%s' AND %s LIKE '%%%s%%'" % (cfg["zip"], zip_code, cfg["stname"], street_like.split()[0])
        if cfg.get("stno"):
            where += " AND %s='%s'" % (cfg["stno"], stno)
    url = (cfg["url"] + "/query?where=" + _up.quote(where) + "&outFields=" + _up.quote(",".join(out))
           + "&resultRecordCount=5&returnGeometry=false&f=json")
    try:
        data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=_CL_UA), timeout=30).read().decode("utf-8", "replace"))
    except Exception as e:
        return {"found": False, "address": address, "note": "county query failed: %s" % str(e)[:90]}
    feats = data.get("features", [])
    if not feats:
        return {"found": False, "address": address, "county": cnty,
                "note": "no matching parcel in %s county records" % cnty}

    def s(a, key):
        v = a.get(cfg[key]) if cfg.get(key) else None
        return str(v).strip() if v not in (None, "") else ""

    a = feats[0].get("attributes", {})
    av = a.get(cfg["val"]) if cfg.get("val") else None
    try:
        av_str = "$%s" % format(int(float(av)), ",") if av not in (None, "", 0) else ""
    except Exception:
        av_str = ""
    prop = " ".join(x for x in [s(a, "stno"), s(a, "stname")] if x).strip() or address
    return {
        "found": True,
        "address": prop,
        "owner_name": s(a, "owner"),
        "assessed_value": av_str,
        "context": _fmt_context(a, ctx),
        "county": cnty,
        "note": "county assessor public record",
    }


def comps_for_zip(zip_code: str, max_comps: int = 400) -> dict:
    """Pull REAL recent arms-length sales in the zip from the county layer and derive a
    robust local median price-per-sqft + an assessed-to-sale ratio. This is the accurate
    basis for a value estimate (real transactions), not a guessed multiplier. Filters out
    $1 family transfers, land-only, and outliers. Returns
    {n, median_ppsf, ppsf_lo, ppsf_hi, assess_to_sale, recent}."""
    import urllib.parse as _up, statistics
    cnty = _county_for_zip(zip_code)
    cfg = COUNTY_PARCELS.get(cnty) if cnty else None
    if not cfg:
        return {"n": 0, "note": "county not mapped"}
    ctx = cfg.get("ctx")
    if ctx is None:
        ctx = _context_fields(_probe_layer_fields(cfg["url"])); cfg["ctx"] = ctx
    sp = ctx.get("last sale"); sf = ctx.get("sqft"); val = cfg.get("val")
    sd = ctx.get("sale date")
    if not (sp and sf):
        return {"n": 0, "note": "county layer has no sale price + sqft"}
    out = [f for f in [sp, sf, val, sd, cfg.get("stname"), cfg.get("pcsz") or cfg.get("zip")] if f]
    where = (cfg["pcsz"] + " LIKE '%%%s%%'" % zip_code) if cfg.get("pcsz") else (cfg["zip"] + "='%s'" % zip_code)
    where += " AND %s > 30000" % sp  # drop $1 intra-family transfers / nominal deeds
    url = (cfg["url"] + "/query?where=" + _up.quote(where) + "&outFields=" + _up.quote(",".join(out))
           + "&resultRecordCount=%d&returnGeometry=false&f=json" % max_comps)
    try:
        data = json.loads(urllib.request.urlopen(urllib.request.Request(url, headers=_CL_UA), timeout=35).read().decode("utf-8", "replace"))
    except Exception as e:
        return {"n": 0, "note": "comps query failed: %s" % str(e)[:80]}
    ppsf, ratios, sales = [], [], []
    pstreet = ctx.get("use class") and None  # placeholder; we read street from stname/pcsz below
    for f in data.get("features", []):
        a = f.get("attributes", {})
        try:
            price = float(a.get(sp) or 0); area = float(a.get(sf) or 0)
            if price > 30000 and area > 300:
                r = price / area
                if 20 < r < 1500:  # plausible residential $/sqft band; drop land/outliers
                    ppsf.append(r)
                    if val and a.get(val):
                        av = float(a[val])
                        if av > 10000:
                            ratios.append(av / price)
                    # capture a sample sale for the comps list (street + price + sqft + year sold)
                    st = (a.get(cfg.get("stname")) or "").strip() if cfg.get("stname") else ""
                    yr = ""
                    if sd and a.get(sd):
                        try:
                            yr = str(1970 + int(int(a[sd]) / 31557600000))
                        except Exception:
                            yr = str(a.get(sd))[:4]
                    sales.append({"street": st, "price": int(price), "sqft": int(area), "year": yr,
                                  "ppsf": round(r)})
        except Exception:
            continue
    if len(ppsf) < 5:
        return {"n": len(ppsf), "note": "too few comps for a reliable median"}
    ppsf.sort()
    n = len(ppsf)
    # Pick a handful of representative comps near the median for the report's "recent sales" list.
    med = statistics.median(ppsf)
    sales_named = [s for s in sales if s["street"]]
    sales_named.sort(key=lambda s: abs(s["ppsf"] - med))
    return {
        "n": n,
        "median_ppsf": round(med, 2),
        "ppsf_lo": round(ppsf[int(n * 0.25)], 2),
        "ppsf_hi": round(ppsf[int(n * 0.75)], 2),
        "assess_to_sale": round(statistics.median(ratios), 3) if len(ratios) >= 5 else None,
        "recent": sales_named[:5],
        "county": cnty,
    }


def value_estimate(address: str, zip_code: str = "", details: dict | None = None) -> dict:
    """Accurate-as-free-data-allows home value estimate. Combines the parcel's own record
    (lookup_address) with a REAL local comps median ($/sqft from actual recent sales,
    comps_for_zip). `details` carries any homeowner-provided facts from the capture form
    (sqft/beds/baths/year/type/condition) — homeowner sqft is preferred for the estimate when
    given, since it pins the property down better than a possibly-stale county record. Returns
    the parcel data plus market_low/mid/high + method + comp count. Never an appraisal; labelled."""
    details = details or {}
    base = lookup_address(address, zip_code)
    if not base.get("found"):
        # Even without a county parcel match, if the homeowner gave sqft we can still estimate
        # from local comps — so don't bail; carry their details forward.
        base = {"found": False, "address": address, "note": base.get("note", "")}
    zc = zip_code or ""
    if not re.fullmatch(r"\d{5}", zc or ""):
        mz = re.search(r"\b(\d{5})\b", address)
        zc = mz.group(1) if mz else ""
    comps = comps_for_zip(zc) if zc else {"n": 0}
    base["comps"] = comps
    base["owner_details"] = {k: v for k, v in details.items() if v}
    # Square footage: prefer the homeowner's own number, else the parcel context.
    sqft = None
    try:
        ds = str(details.get("sqft") or "").replace(",", "")
        if ds.isdigit() and int(ds) > 200:
            sqft = int(ds)
    except Exception:
        sqft = None
    if not sqft:
        m = re.search(r"([\d,]+)\s*sqft", base.get("context", ""), re.I)
        if m:
            try:
                sqft = int(m.group(1).replace(",", ""))
            except Exception:
                sqft = None
    av = None
    m = re.search(r"[\d,]+", base.get("assessed_value", "") or "")
    if m:
        try:
            av = int(m.group(0).replace(",", ""))
        except Exception:
            av = None
    estimates = []
    method = []
    # 1) comps-based: living sqft x local median $/sqft (the accurate, transaction-based signal).
    if sqft and comps.get("median_ppsf"):
        estimates.append(sqft * comps["median_ppsf"])
        method.append("%d recent local sales at a median $%.0f/sq ft x %s sq ft"
                      % (comps["n"], comps["median_ppsf"], format(sqft, ",")))
    # 2) assessed-value-adjusted: assessed / local assessment-to-sale ratio (real, not a guess).
    if av and comps.get("assess_to_sale"):
        estimates.append(av / comps["assess_to_sale"])
        method.append("county assessed value adjusted by the local assessment-to-sale ratio (%.0f%%)"
                      % (comps["assess_to_sale"] * 100))
    elif av and not estimates:
        # last resort only if we have nothing better — clearly the weakest signal.
        estimates.append(av * 1.15)
        method.append("county assessed value with a general market adjustment (limited comp data)")
    if estimates:
        mid = sum(estimates) / len(estimates)
        spread = 0.08 if len(estimates) > 1 else 0.14  # tighter band when two methods agree
        base["market_mid"] = int(mid)
        base["market_low"] = int(mid * (1 - spread))
        base["market_high"] = int(mid * (1 + spread))
        base["estimate_method"] = method
        base["estimate_confidence"] = ("higher" if len(estimates) > 1 and comps.get("n", 0) >= 30
                                        else "moderate" if estimates else "low")
        # If the parcel wasn't matched but the homeowner's own sqft + local comps gave us a
        # real estimate, treat the report as found so it shows the range (clearly comp-based).
        if not base.get("found") and sqft and comps.get("median_ppsf"):
            base["found"] = True
            if not base.get("address"):
                base["address"] = address
        # Net proceeds: market value minus typical selling costs (~7.5%: commission + closing).
        base["net_low"] = int(base["market_low"] * 0.925)
        base["net_high"] = int(base["market_high"] * 0.925)
        # Equity vs. the last recorded sale price (a real, owned-since basis when present).
        m2 = re.search(r"last sale\s+\$?([\d,]+)", base.get("context", ""), re.I)
        if m2:
            try:
                basis = int(m2.group(1).replace(",", ""))
                if basis > 10000:
                    base["basis"] = basis
                    base["equity_gain"] = int(mid) - basis  # appreciation since purchase
            except Exception:
                pass
    return base


def _free_provider(zip_code: str, limit: int) -> tuple[list[dict], list[str]]:
    """FREE motivated-seller sourcing. PRIMARY = county assessor absentee owners
    (the real ATTOM-grade signal, direct-mail-ready). Supplement with Craigslist
    FSBO (active self-listed sellers) up to the limit."""
    leads, notes = _county_assessor(zip_code, limit)
    if len(leads) < limit:
        fsbo, fnotes = _craigslist_fsbo(zip_code, limit - len(leads))
        leads = leads + fsbo
        notes += fnotes
    if not leads:
        notes.append("no free leads (county not mapped + no current FSBO)")
    notes.append("FREE-SOURCE NOTE: absentee owners are direct-mail-ready (property + owner + "
                 "mailing + assessed value, free county assessor data, the same source ATTOM "
                 "resells). FSBO are active self-listed sellers. Add a county to COUNTY_PARCELS to expand.")
    return leads[:limit], notes


def _bd_post(path: str, key: str, body: dict) -> dict:
    """POST to the BatchData API and return parsed JSON (raises on transport error)."""
    req = urllib.request.Request(
        "https://api.batchdata.com" + path,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.loads(r.read())


def _bd_first(d, *names):
    """First non-empty value among the given keys of a dict (tolerant parsing)."""
    if not isinstance(d, dict):
        return None
    for n in names:
        v = d.get(n)
        if v not in (None, "", [], {}):
            return v
    return None


def _batchdata_provider(zip_code: str, limit: int) -> tuple[list[dict], list[str]]:
    """Paid provider: BatchData Property Search (motivated-seller quick-lists) with
    inline Skip Trace (owner phone/email). Enabled by SELLER_LEADS_PROVIDER=batchdata
    + BATCHDATA_API_KEY in hostinger.env.

    NOT live-tested (no key on this machine). Implemented to BatchData's documented
    v1 endpoints with tolerant parsing. When you add the key, verify the request
    `searchCriteria`/`quickLists` names and the response field names against your
    BatchData plan's docs and adjust the two marked spots if they differ."""
    key = ENV.get("BATCHDATA_API_KEY", "").strip()
    if not key:
        return [], ["batchdata selected but BATCHDATA_API_KEY not set — skipping"]
    # --- VERIFY-AGAINST-DOCS #1: request shape (quickLists + zip + inline skip-trace).
    search_body = {
        "searchCriteria": {
            "query": zip_code,
            "quickLists": ["preforeclosure", "high-equity", "vacant",
                           "absentee-owner", "tax-default"],
        },
        "options": {"skip": 0, "take": max(1, min(limit, 50)), "skipTrace": True},
    }
    try:
        data = _bd_post("/api/v1/property/search", key, search_body)
    except urllib.error.HTTPError as e:
        return [], [f"batchdata property/search HTTP {e.code}: {e.read().decode()[:160]} "
                    "(verify endpoint + key + request schema vs BatchData docs)"]
    except Exception as e:
        return [], [f"batchdata property/search failed: {str(e)[:140]}"]
    # --- VERIFY-AGAINST-DOCS #2: response shape (property array + field names).
    results = data.get("results") if isinstance(data.get("results"), dict) else {}
    props = _bd_first(data, "properties") or _bd_first(results, "properties") or _bd_first(data, "data") or []
    if not isinstance(props, list):
        return [], [f"batchdata: unexpected response shape (no property list); keys={list(data)[:8]}"]
    leads: list[dict] = []
    for p in props[:limit]:
        if not isinstance(p, dict):
            continue
        a = p.get("address") if isinstance(p.get("address"), dict) else {}
        street = _bd_first(a, "street", "line1", "address") or (_bd_first(p, "address") if not a else "") or ""
        city = _bd_first(a, "city") or ""
        st = _bd_first(a, "state") or ""
        pz = _bd_first(a, "zip", "zipCode") or zip_code
        full_addr = ", ".join(x for x in [street, city, f"{st} {pz}".strip()] if x).strip(", ")
        owner = p.get("owner") if isinstance(p.get("owner"), dict) else {}
        owner_name = (_bd_first(owner, "fullName", "name")
                      or " ".join(x for x in [_bd_first(owner, "firstName") or "",
                                              _bd_first(owner, "lastName") or ""] if x).strip())
        phones = p.get("phoneNumbers") or owner.get("phoneNumbers") or []
        emails = p.get("emails") or owner.get("emails") or []
        phone = ""
        if isinstance(phones, list) and phones:
            phone = (_bd_first(phones[0], "number", "phone") if isinstance(phones[0], dict) else str(phones[0])) or ""
        email = ""
        if isinstance(emails, list) and emails:
            email = (_bd_first(emails[0], "email", "address") if isinstance(emails[0], dict) else str(emails[0])) or ""
        ql = p.get("quickLists") or p.get("quickList") or []
        signal = (ql[0] if isinstance(ql, list) and ql else ql if isinstance(ql, str) and ql else "motivated_seller")
        leads.append({
            "address": full_addr,
            "owner_name": owner_name or "",
            "signal": str(signal),
            "source": "batchdata",
            "contact_email": email,
            "contact_phone": phone,
            "confidence": "verified" if (phone or email) else "address_found",
            "needs_research": not (phone or email),
        })
    notes = [f"batchdata: {len(props)} properties, mapped {len(leads)} leads, "
             f"{sum(1 for l in leads if l['contact_phone'] or l['contact_email'])} with contact"]
    return leads, notes


def source_seller_leads(zip_code: str, limit: int = 25) -> dict:
    """Public entry. Returns {zip, provider, count, coverage, notes, leads}."""
    zip_code = (zip_code or "").strip()
    if not re.fullmatch(r"\d{5}", zip_code):
        return {"zip": zip_code, "error": "not a 5-digit US zip", "leads": []}
    if PROVIDER == "batchdata":
        leads, notes = _batchdata_provider(zip_code, limit)
        if not leads:  # graceful fallback to free if paid yields nothing/off
            fleads, fnotes = _free_provider(zip_code, limit)
            leads, notes = fleads, notes + fnotes
    else:
        leads, notes = _free_provider(zip_code, limit)
    with_contact = sum(1 for l in leads if l.get("contact_email") or l.get("contact_phone"))
    coverage = ("good" if with_contact >= max(1, limit // 2)
                else "thin" if leads else "none")
    return {
        "zip": zip_code,
        "provider": PROVIDER,
        "count": len(leads),
        "with_contact": with_contact,
        "coverage": coverage,
        "notes": notes,
        "leads": leads,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("zip")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = source_seller_leads(a.zip, a.limit)
    if a.json:
        print(json.dumps(res, indent=2))
        return 0
    print(f"=== seller leads for zip {res['zip']} (provider={res['provider']}) ===")
    if res.get("error"):
        print("  error:", res["error"]); return 1
    print(f"  found {res['count']}  |  with contact {res['with_contact']}  |  coverage {res['coverage']}")
    for n in res["notes"]:
        print("  -", n)
    print()
    for i, l in enumerate(res["leads"], 1):
        print(f"  {i:2}. [{l['signal']:15}] {l['address'] or '(address needs research)'}")
        print(f"      source: {l['source'][:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
