"""auto_source_atal.py — daily autonomous lead sourcing for atalsolidrocks.

Pipeline (all cron-safe, no Claude/web-API needed):
  1. Generate clean sector x city queries for the Krankenstand ICP
     (ambulante Pflege, Pflegeheim, Spedition/Logistik, Produktion/Fertigung).
  2. Multi-backend web search (Bing/Brave/Google/Mojeek via ddgs) -> result domains.
  3. Drop directory/aggregator/social domains; dedup against the master list.
  4. Append genuinely-new company domains to niches/atal_domains.txt.
  5. Hand the new domains to impressum_scrape.py, which only KEEPS pages that
     have a real contact email (+ ideally a Geschäftsführer name). That email/GF
     gate self-cleans any search noise: a junk page has no Impressum -> rejected.

Idempotent. Safe to schedule daily. Sources only; never sends.

Usage:
    py sequences/auto_source_atal.py                 # full pass
    py sequences/auto_source_atal.py --max-cities 4  # smaller pass
    py sequences/auto_source_atal.py --dry           # discover only, no scrape/write
"""
from __future__ import annotations
import argparse, subprocess, sys, time
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from seed_discover import _search_ddg  # multi-backend search (Bing/Brave/Google/Mojeek)

PY = sys.executable
DOMAINS_FILE = REPO / "niches" / "atal_domains.txt"

SECTOR_QUERIES = [
    "ambulanter Pflegedienst {city} GmbH",
    "Pflegeheim Seniorenheim Betreiber {city}",
    "Spedition Logistik {city} GmbH",
    "Produktion Fertigung Betrieb {city} GmbH",
]
CITIES = ["Berlin", "München", "Hamburg", "Köln", "Frankfurt", "Stuttgart",
          "Düsseldorf", "Leipzig", "Dortmund", "Essen", "Bremen", "Hannover",
          "Nürnberg", "Wien", "Zürich"]

# Directories / aggregators / social / generic — never treat as a company.
SKIP_HOSTS = (
    "gelbeseiten", "11880", "dasoertliche", "dastelefonbuch", "kompass",
    "wlw.de", "wikipedia", "linkedin", "facebook", "instagram", "xing",
    "indeed", "stepstone", "kununu", "google.", "youtube", "bing.", "yelp",
    "pflege.de", "pflegedb", "wegweiser-pflege", "pflegestufe", "caritas",
    "diakonie", "awo.org", "drk.de", "jameda", "meinestadt", "branchenbuch",
    "firmenwissen", "northdata", "unternehmensregister", "handelsregister",
    "die-deutsche-wirtschaft", "marktundmittelstand", "vdma", "amazon.",
    "apple.", "microsoft", "heise", "t-online", "web.de", "gmx",
    # content / forums / lexica / portals that clutter search results
    "reddit", "zhihu", "yahoo", "quora", "gutefrage", "studyflix", "chip.de",
    "focus.de", "bwl-lexikon", "wirtschaftswissen", "sensorstechforum",
    "produktion.de", "altenheime.de", "wohnen-im-alter", "werkenntdenbesten",
    "aok.", "berlin.de", "wien.gv.at", "stadt-", "pflegenoten", "medwing",
    "stellenanzeigen", "wikiwand", "tiktok", "pinterest",
)
# Only treat these TLDs as plausible DACH company domains.
OK_TLDS = (".de", ".at", ".ch", ".com", ".io", ".net", ".eu")


def host_of(url: str) -> str | None:
    try:
        h = urlparse(url if url.startswith("http") else "https://" + url).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return None


def existing_domains() -> set[str]:
    out = set()
    if DOMAINS_FILE.exists():
        for ln in DOMAINS_FILE.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                out.add(ln.lower())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-cities", type=int, default=len(CITIES))
    ap.add_argument("--per-query", type=int, default=8)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    have = existing_domains()
    found: set[str] = set()
    cities = CITIES[:args.max_cities]
    print(f"=== auto_source_atal: {len(SECTOR_QUERIES)}x{len(cities)} queries ===")
    for city in cities:
        for tmpl in SECTOR_QUERIES:
            q = tmpl.format(city=city)
            urls = _search_ddg(q, max_results=args.per_query)
            for u in urls:
                h = host_of(u)
                if not h or "." not in h:
                    continue
                if not h.endswith(OK_TLDS):
                    continue
                if any(s in h for s in SKIP_HOSTS):
                    continue
                if h in have or h in found:
                    continue
                found.add(h)
            time.sleep(0.3)
    print(f"discovered {len(found)} new candidate domains (after filtering)")
    if not found:
        print("nothing new; done.")
        return 0
    if args.dry:
        for h in sorted(found):
            print("  +", h)
        return 0

    # Append new domains to the master list
    with open(DOMAINS_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n# auto_source_atal {time.strftime('%Y-%m-%d %H:%M')}\n")
        for h in sorted(found):
            f.write(h + "\n")
    print(f"appended {len(found)} domains to {DOMAINS_FILE.name}")

    # Scrape ONLY the new domains this run (write them to a temp file)
    tmp = REPO / "out" / "_atal_new_domains.txt"
    tmp.write_text("\n".join(sorted(found)), encoding="utf-8")
    print("running impressum_scrape on new domains...")
    r = subprocess.run([PY, str(REPO / "sequences" / "impressum_scrape.py"),
                        "atalsolidrocks", str(tmp)], cwd=str(REPO))
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
