"""enrichment_worker.py — backfill categorization columns on prospects.

Reads prospects where `enriched_categorization_at IS NULL`, for each row:
  1. Looks up audience size from the source platform (subscriber/follower count)
  2. Tags industry/vertical from bio + company keywords
  3. Detects geo from website TLD or bio location
  4. Computes composite quality_score 0-100

Writes back via PATCH, sets enriched_categorization_at. Idempotent — only
re-enriches when explicitly forced (--force) or when source platform changes.

CLI:
    py enrichment_worker.py run [--profile <slug>] [--limit N] [--force]
    py enrichment_worker.py stats

Quality score formula (rough; tunable):
    base = 30 (just having a verified email)
    + min(audience_size/10000 * 30, 30)   # capped at 30 pts for 10k+
    + 20 if industry_tags is not empty
    + 10 if geo is set
    + 10 if first_name + last_name both set (real person, not role mailbox)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path
from typing import Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from queue_lib import _SUPA_URL, _SUPA_KEY, _HEADERS  # noqa: E402
from youtube_scraper import load_api_keys, API_BASE  # noqa: E402


# ─── Vertical tagging (keyword-based) ──────────────────────────────────────
#
# Keywords are matched against (company OR title OR enriched_context.snippet
# OR bio). Multiple tags can apply to a single prospect. Order in the dict
# doesn't matter — we collect all matching tags.

INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "trading_crypto":  ["crypto", "bitcoin", "btc", "eth", "altcoin", "defi",
                        "trading", "trader", "tradingview", "ta ", "technical analysis",
                        "indicator", "signals", "scalp", "futures"],
    "trading_general": ["forex", "fx", "stocks", "options", "swing trade",
                        "wall street", "nasdaq"],
    "fitness":         ["fitness", "gym", "workout", "muscle", "bodybuilding",
                        "trainer", "yoga", "pilates", "calisthenics"],
    "fashion":         ["fashion", "style", "outfit", "model", "designer"],
    "beauty":          ["beauty", "makeup", "skincare", "cosmetic", "haircare"],
    "food":            ["recipe", "cooking", "chef", "foodie", "restaurant"],
    "real_estate":     ["realtor", "real estate", "broker", "agent", "property",
                        "listing", "mls"],
    "gaming":          ["gaming", "gamer", "twitch", "stream", "esports"],
    "tech_saas":       ["saas", "startup", "founder", "developer", "engineer",
                        "software", "tech"],
    "marketing":       ["marketing", "growth", "seo", "ppc", "ads", "agency"],
    "education":       ["course", "teach", "tutorial", "education", "school"],
    "finance_macro":   ["macro", "economy", "investor", "vc", "venture",
                        "portfolio", "wealth"],
}

# Geo from TLD (lowercase). country-code TLDs map cleanly; gTLDs left blank.
TLD_GEO: dict[str, str] = {
    "us":"US","uk":"GB","co.uk":"GB","de":"DE","fr":"FR","es":"ES","it":"IT",
    "nl":"NL","pl":"PL","ru":"RU","jp":"JP","kr":"KR","cn":"CN","au":"AU",
    "ca":"CA","ch":"CH","at":"AT","be":"BE","se":"SE","no":"NO","fi":"FI",
    "dk":"DK","cz":"CZ","ee":"EE","lv":"LV","lt":"LT","gr":"GR","pt":"PT",
    "in":"IN","sg":"SG","hk":"HK","tw":"TW","my":"MY","th":"TH","ph":"PH",
    "id":"ID","vn":"VN","tr":"TR","ae":"AE","sa":"SA","ng":"NG","za":"ZA",
    "mx":"MX","br":"BR","ar":"AR","cl":"CL","pe":"PE","ve":"VE","ie":"IE",
    "ro":"RO","hu":"HU","bg":"BG","sk":"SK","si":"SI","hr":"HR","ua":"UA",
}


def _domain_tld(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    m = re.search(r"https?://(?:www\.)?([a-z0-9.\-]+)", url, re.I)
    if not m:
        return None
    host = m.group(1).lower()
    # Try 2-segment first (co.uk), then 1
    parts = host.split(".")
    if len(parts) >= 3 and ".".join(parts[-2:]) in TLD_GEO:
        return ".".join(parts[-2:])
    if parts[-1] in TLD_GEO:
        return parts[-1]
    return None


def tag_industry(text_blob: str) -> list[str]:
    """Return all matching industry tags. Lowercase substring match."""
    blob = (text_blob or "").lower()
    out = set()
    for tag, kws in INDUSTRY_KEYWORDS.items():
        for kw in kws:
            if kw in blob:
                out.add(tag)
                break
    return sorted(out)


def quality_score(audience_size: Optional[int], tags: list[str],
                  geo: Optional[str], first_name: Optional[str],
                  last_name: Optional[str], verification_method: Optional[str]) -> int:
    score = 0
    if verification_method == "smtp_verified":
        score += 35
    else:
        score += 25  # mx_verified
    if audience_size:
        score += min(int(audience_size / 10_000 * 25), 25)
    if tags:
        score += 15
    if geo:
        score += 10
    if first_name and last_name:
        score += 10  # likely an individual, not a role mailbox
    return min(score, 100)


# ─── Per-source audience lookups ─────────────────────────────────────────

def _audience_youtube(api_key: str, source_url: str) -> Optional[int]:
    """source_url is `https://www.youtube.com/channel/UCxxx...`. Call
    channels.list?part=statistics to get subscriberCount."""
    m = re.search(r"/channel/(UC[A-Za-z0-9_\-]{22})", source_url or "")
    if not m:
        return None
    r = httpx.get(f"{API_BASE}/channels",
                  params={"part": "statistics", "id": m.group(1), "key": api_key},
                  timeout=15)
    if r.status_code != 200:
        return None
    items = r.json().get("items") or []
    if not items:
        return None
    sc = items[0].get("statistics", {}).get("subscriberCount")
    try:
        return int(sc) if sc is not None else None
    except (TypeError, ValueError):
        return None


# ─── Fetch + enrich loop ──────────────────────────────────────────────────

def fetch_unenriched(profile_slug: Optional[str], limit: int,
                     force: bool) -> list[dict]:
    """Read prospects without enriched_categorization_at."""
    flt = []
    if not force:
        flt.append("enriched_categorization_at=is.null")
    if profile_slug:
        flt.append(f"profile_slug=eq.{profile_slug}")
    # We need verified rows only (no point enriching invalid emails)
    flt.append("verified=eq.true")
    q = "&".join(flt) + f"&order=created_at.asc&limit={limit}"
    sel = "id,profile_slug,niche_slug,email,first_name,last_name,title,company,website,source_url,enriched_context,verification_method"
    r = httpx.get(f"{_SUPA_URL}/rest/v1/prospects?{q}&select={sel}",
                  headers=_HEADERS, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"fetch_unenriched {r.status_code}: {r.text[:200]}")
    return r.json() or []


def update_prospect(prospect_id: str, body: dict) -> None:
    r = httpx.patch(
        f"{_SUPA_URL}/rest/v1/prospects?id=eq.{prospect_id}",
        headers=_HEADERS, json=body, timeout=15,
    )
    if r.status_code not in (200, 204):
        raise RuntimeError(f"update {r.status_code}: {r.text[:200]}")


def enrich_one(row: dict, yt_key: Optional[str]) -> dict:
    """Compute the categorization fields for a single prospect row. Returns
    the patch body."""
    # Audience size: per-platform lookup
    audience = None
    src = (row.get("source_url") or "")
    if "youtube.com/channel/" in src and yt_key:
        audience = _audience_youtube(yt_key, src)

    # Industry tags: from company + title + snippet
    snippet = ((row.get("enriched_context") or {}).get("about_snippet")
               or (row.get("enriched_context") or {}).get("snippet") or "")
    blob = " ".join(filter(None, [row.get("company"), row.get("title"),
                                  snippet]))
    tags = tag_industry(blob)

    # Geo from website TLD
    geo = _domain_tld(row.get("website") or row.get("source_url"))
    geo_code = TLD_GEO.get(geo) if geo else None

    # Source platform detection
    sp = None
    if src:
        if "youtube.com" in src: sp = "youtube"
        elif "tradingview.com" in src: sp = "tradingview"
        elif "instagram.com" in src: sp = "instagram"
        elif "x.com" in src or "twitter.com" in src: sp = "twitter"
        elif "tiktok.com" in src: sp = "tiktok"
        elif "twitch.tv" in src: sp = "twitch"

    score = quality_score(audience, tags, geo_code,
                          row.get("first_name"), row.get("last_name"),
                          row.get("verification_method"))

    return {
        "source_platform": sp,
        "audience_size":   audience,
        "industry_tags":   tags or None,
        "geo":             geo_code,
        "quality_score":   score,
        "enriched_categorization_at": dt.datetime.utcnow().isoformat() + "Z",
    }


def run(profile_slug: Optional[str], limit: int, force: bool) -> int:
    yt_keys = load_api_keys()
    yt_key = yt_keys[0] if yt_keys else None
    rows = fetch_unenriched(profile_slug, limit, force)
    print(f"=== enrichment_worker ===")
    print(f"  profile = {profile_slug or '(all)'}")
    print(f"  rows    = {len(rows)}")
    print(f"  yt_key  = {'yes' if yt_key else 'no'}")
    print(f"  force   = {force}\n")

    summary = {"enriched": 0, "errors": 0,
               "with_audience": 0, "with_tags": 0, "with_geo": 0}
    for row in rows:
        try:
            body = enrich_one(row, yt_key)
            update_prospect(row["id"], body)
            summary["enriched"] += 1
            if body["audience_size"]:    summary["with_audience"] += 1
            if body["industry_tags"]:    summary["with_tags"] += 1
            if body["geo"]:              summary["with_geo"] += 1
            tags_str = ",".join(body["industry_tags"] or [])[:30]
            print(f"  [{body['quality_score']:3}/100] {row['email']:40} "
                  f"aud={body['audience_size'] or '-':>8} geo={body['geo'] or '-':3} "
                  f"tags=[{tags_str}]", flush=True)
        except Exception as e:
            summary["errors"] += 1
            print(f"  ! {row.get('email','?')}: {e}", flush=True)

    print("\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k:18} {v}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_r = sub.add_parser("run")
    p_r.add_argument("--profile", default=None)
    p_r.add_argument("--limit", type=int, default=500)
    p_r.add_argument("--force", action="store_true",
                     help="re-enrich rows even if enriched_categorization_at is set")

    args = ap.parse_args()
    if args.cmd == "run":
        return run(args.profile, args.limit, args.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
