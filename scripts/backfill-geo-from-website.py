"""backfill-geo-from-website.py — geo backfill for Aureon prospects with no
city (and/or no state). Fetches the lead's OWN website and extracts the office
CITY + state from a real address (the precise "City, ST ZIP" pattern). Only
writes when an address is actually found - never guesses. Pinning the city lets
the referral-list fulfiller match a state-only lead to the right metro.

Usage:
  py scripts/backfill-geo-from-website.py --dry   # fetch + show, write nothing
  py scripts/backfill-geo-from-website.py         # apply
"""
import argparse
import concurrent.futures as cf
import json
import re
import ssl
import sys
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PROFILE = "aureon"
WORKERS = 10
TIMEOUT = 8

US = {"AL","AK","AZ","AR","CA","CO","CT","DE","DC","FL","GA","HI","ID","IL","IN",
      "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV","NH",
      "NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN","TX","UT",
      "VT","VA","WA","WV","WI","WY"}
# ", City, ST ZIP" — REQUIRE a leading comma so the city is a real comma-
# delimited field. Without it the regex grabs the STREET when the city is
# omitted ("123 Fox Hollow Bv, TX 78xxx" -> "Fox Hollow Bv"). The leading comma
# + street-suffix reject below kills those false positives.
_PLACE = re.compile(r",\s*([A-Za-z][A-Za-z.'\- ]{1,28}),\s*([A-Z]{2})\s+\d{5}(?:-\d{4})?\b")
_BADCITY = {"suite", "ste", "floor", "fl", "unit", "apt", "building", "bldg",
            "road", "street", "st", "ave", "avenue", "blvd", "bv", "drive", "dr",
            "lane", "ln", "court", "ct", "way", "place", "pl", "pkwy", "parkway",
            "highway", "hwy", "expy", "fwy", "box", "po box", "p o box", "circle",
            "cir", "trail", "trl", "terrace", "ter", "loop", "pike", "plaza", "plz", "row"}
_CTX = ssl._create_unverified_context()

env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
URL = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"
KEY = env.get("SUPABASE_ANON_KEY") or env.get("SUPABASE_KEY")
HDR = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def sget(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(URL + path, headers=HDR), timeout=90).read())


def spatch(path, body):
    r = urllib.request.Request(URL + path, data=json.dumps(body).encode(), method="PATCH",
                               headers={**HDR, "Content-Type": "application/json", "Prefer": "return=minimal"})
    urllib.request.urlopen(r, timeout=60).read()


def fetch(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
            return r.read(400_000).decode("utf-8", "ignore")
    except Exception:
        return ""


def place_from(html):
    """Return (city, state) from the most common 'City, ST ZIP' on the page."""
    if not html:
        return "", ""
    votes = Counter()
    for m in _PLACE.finditer(html):
        city = re.sub(r"\s+", " ", m.group(1)).strip(" .-").strip()
        st = m.group(2).upper()
        if st not in US or len(city) < 3:
            continue
        words = city.lower().split()
        if not words or len(words) > 3:          # real cities are 1-3 words
            continue
        if city.lower() in _BADCITY or words[-1] in _BADCITY or words[0] in _BADCITY:
            continue
        if any(ch.isdigit() for ch in city):
            continue
        votes[(city.title(), st)] += 1
    return votes.most_common(1)[0][0] if votes else ("", "")


def site_urls(website, source_url):
    base = (website or source_url or "").strip()
    if not base:
        return []
    if not base.startswith("http"):
        base = "https://" + base
    p = urllib.parse.urlparse(base)
    root = f"{p.scheme}://{p.netloc}"
    return [root + path for path in ("", "/contact", "/contact-us", "/about", "/about-us")]


def resolve_one(row):
    for u in site_urls(row.get("website"), row.get("source_url"))[:5]:
        city, st = place_from(fetch(u))
        if city:
            return row, city, st
    return row, "", ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = []
    for off in range(0, 20000, 1000):
        b = sget(f"prospects?profile_slug=eq.{PROFILE}&city=is.null&select=id,website,source_url,state&limit=1000&offset={off}")
        rows += b
        if len(b) < 1000:
            break
    cand = [r for r in rows if (r.get("website") or r.get("source_url"))]
    if args.limit:
        cand = cand[:args.limit]
    print(f"aureon with no city: {len(rows)} | with a website to try: {len(cand)}")

    updates = []   # (id, patch)
    by_city = Counter(); by_state = Counter()
    with cf.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for i, (row, city, st) in enumerate(ex.map(resolve_one, cand), 1):
            if city:
                patch = {"city": city}
                if st and not (row.get("state") or "").strip():
                    patch["state"] = st
                updates.append((row["id"], patch))
                by_city[f"{city}, {st}"] += 1; by_state[st] += 1
            if i % 25 == 0:
                print(f"  ...{i}/{len(cand)} processed, {len(updates)} cities found")
    print(f"\nresolved a CITY for {len(updates)}/{len(cand)}")
    print("top states:", dict(by_state.most_common(10)))
    print("top cities:")
    for c, n in by_city.most_common(20):
        print(f"   {n:3}  {c}")

    if args.dry:
        print("\n[dry] nothing written."); return 0
    for pid, patch in updates:
        spatch(f"prospects?id=eq.{pid}", patch)
    print(f"\nwrote city on {len(updates)} prospects.")
    after = sget(f"prospects?profile_slug=eq.{PROFILE}&city=not.is.null&select=id")
    print(f"verify: city now present on {len(after)} aureon prospects")
    return 0


if __name__ == "__main__":
    sys.exit(main())
