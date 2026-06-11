# -*- coding: utf-8 -*-
"""diraya-smb-discover.py — DOWNMARKET Diraya lead source (test + harvester).

The YC path mails stealth startups that publish founder emails at ~1-2 percent.
This path goes downmarket to ESTABLISHED small/mid software companies that put
staff emails on their "our team / about / contact" pages at far higher rates,
and that genuinely fit Diraya's "we build your AI feature" offer. These leads
feed the de-jargoned diraya-smb sequence, not the technical diraya-default one.

Pipeline (all $0, no port 25):
  1. CSE-search for SMB software companies with team pages (seed_discover._search).
  2. Quality gate: homepage must read like a real software company (SOFTWARE_RX),
     not a directory / review site / big brand / marketplace (BLOCK + NONCOMPANY).
  3. Scrape home/about/team/contact for PUBLISHED on-domain emails.
  4. Keep name-like local parts (drop role/junk), derive first name, MX-verify.
  5. Output a worksheet CSV; with --import, load into the diraya pool tagged
     niche=diraya_smb so routing can send them the downmarket copy.

  py scripts/diraya-smb-discover.py --max-queries 6            # small yield TEST
  py scripts/diraya-smb-discover.py --max-queries 15 --import  # harvest + import
"""
from __future__ import annotations
import argparse, csv, re, sys, urllib.request, subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
import lead_verify as lv                                    # noqa
from name_derive import derive_first_name, is_free_or_isp_domain  # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123 Safari/537.36"
OUT = REPO / "out" / "diraya_smb_emails.csv"
PAGES = ["", "about", "team", "about-us", "our-team", "company", "contact"]
EMAIL_RX = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')

# never treat these as an SMB software company (directories, review sites, big brands)
BLOCK = {"google.com", "facebook.com", "twitter.com", "x.com", "linkedin.com", "youtube.com",
         "instagram.com", "github.com", "medium.com", "crunchbase.com", "wellfound.com",
         "angel.co", "producthunt.com", "apple.com", "microsoft.com", "amazon.com", "notion.so",
         "substack.com", "wikipedia.org", "forbes.com", "techcrunch.com", "bloomberg.com",
         "reddit.com", "discord.com", "slack.com", "g2.com", "capterra.com", "getapp.com",
         "clutch.co", "trustpilot.com", "glassdoor.com", "indeed.com", "shopify.com",
         "wordpress.com", "wix.com", "squarespace.com", "godaddy.com", "hubspot.com",
         "businessnewsdaily.com", "investopedia.com", "gartner.com", "softwareadvice.com",
         "goodfirms.co", "designrush.com", "upwork.com", "fiverr.com", "toptal.com",
         "builtin.com", "themanifest.com", "sortlist.com"}
GOOD_TLD = re.compile(r"\.(com|io|co|app|software|tech|dev|ai|us|net)$")
SOFTWARE_RX = re.compile(
    r"\b(software|saas|platform|application|app\b|api|sdk|developers?|engineering|"
    r"product|technology|cloud|automation|integration|dashboard|analytics|"
    r"crm|erp|workflow|solutions?)\b", re.I)
# pages that are listicles / directories / review hubs, not a single company
NONCOMPANY_RX = re.compile(
    r"\b(top \d+|best \d+|\d+ best|listicle|directory|compare|reviews of|"
    r"vendor list|leaderboard|alternatives to|vs\.)\b", re.I)
ROLE = {"info", "contact", "hello", "sales", "admin", "support", "office", "team", "marketing",
        "press", "jobs", "careers", "hr", "legal", "privacy", "billing", "help", "security",
        "noreply", "no-reply", "media", "partnerships", "partner", "general", "inquiries",
        "newsletter", "events", "demo", "feedback", "service", "accounts", "account"}

QUERIES = [
    "software company our team contact email",
    "saas company about us leadership team",
    "custom software development company meet the team",
    "B2B software company our team",
    "software product company leadership contact",
    "app development company our team email",
    "software company Texas our team",
    "software company Florida meet the team",
    "software company Colorado leadership contact",
    "vertical saas company about us team",
    "logistics software company our team",
    "healthcare software company leadership team",
    "fintech software company about us team",
    "data analytics software company our team",
    "workflow automation software company team contact",
]


def dom_of(u: str) -> str:
    try:
        h = urlparse(u if u.startswith("http") else "https://" + u).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def root(d: str) -> str:
    return d[4:] if d.startswith("www.") else d


def good_company(dom: str) -> bool:
    return bool(dom) and dom not in BLOCK and bool(GOOD_TLD.search(dom)) \
        and not dom.endswith((".gov", ".edu", ".org")) and dom.count(".") <= 2 and len(dom) <= 40


def fetch(url: str) -> str:
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                                      timeout=10).read().decode("utf-8", "replace")
    except Exception:
        return ""


def looks_software_co(dom: str) -> bool:
    """Gate: the homepage reads like a real software COMPANY, not a directory/brand."""
    html = fetch("https://" + dom)
    if not html:
        return False
    low = html[:30000].lower()
    if NONCOMPANY_RX.search(low[:6000]):
        return False
    # needs software signal AND a sign of being an actual company site (team/about/contact nav)
    return bool(SOFTWARE_RX.search(low)) and bool(re.search(r"\b(about|team|company|contact)\b", low))


def staff_emails(dom: str) -> list[dict]:
    """Scrape team/about/contact pages; return name-like, on-domain, MX-valid staff emails."""
    found, base = set(), f"https://{dom}".rstrip("/")
    for pg in PAGES:
        html = fetch(f"{base}/{pg}" if pg else base)
        if not html:
            continue
        for e in EMAIL_RX.findall(html):
            e = e.lower().strip(".")
            ed = e.split("@")[-1]
            if root(ed) == root(dom) or root(ed).endswith("." + root(dom)):
                found.add(e)
        if len(found) >= 12:
            break
    out = []
    for e in found:
        local = e.split("@")[0]
        if local in ROLE or local in lv.JUNK_LOCAL_PARTS:
            continue
        first = derive_first_name(e)
        if not first or len(first) < 2:
            continue                                        # only keep personal, name-bearing inboxes
        if not lv.verify(e, do_smtp_probe=False).verified:  # MX-only, no port 25
            continue
        out.append({"email": e, "first_name": first.title(), "domain": dom})
    return out


def discover(max_queries: int, per_query: int, workers: int) -> tuple[list[dict], dict]:
    import seed_discover as sd
    cand: set[str] = set()
    for q in QUERIES[:max_queries]:
        try:
            for u in sd._search(q, per_query, "us"):
                d = dom_of(u)
                if good_company(d):
                    cand.add(d)
        except Exception as e:
            print(f"  search failed ({q[:30]}): {e}")
    cand = sorted(cand)
    print(f"  {len(cand)} candidate domains from {min(max_queries, len(QUERIES))} queries; gating homepages...")
    gated = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(looks_software_co, d): d for d in cand}
        for f in as_completed(futs):
            try:
                if f.result():
                    gated.append(futs[f])
            except Exception:
                pass
    print(f"  {len(gated)} passed the software-company gate; scraping team pages for staff emails...")
    leads = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(staff_emails, d): d for d in gated}
        for f in as_completed(futs):
            try:
                leads.extend(f.result())
            except Exception:
                pass
    stats = {"candidates": len(cand), "gated": len(gated), "leads": len(leads)}
    return leads, stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-queries", type=int, default=8)
    ap.add_argument("--per-query", type=int, default=10)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--import", dest="do_import", action="store_true")
    a = ap.parse_args()

    print("discovering downmarket SMB software companies with published staff emails...")
    leads, stats = discover(a.max_queries, a.per_query, a.workers)
    # dedupe by email
    seen, uniq = set(), []
    for l in leads:
        if l["email"] in seen:
            continue
        seen.add(l["email"]); uniq.append(l)
    print(f"\n=== stats: {stats}  unique leads: {len(uniq)}")
    for l in uniq[:25]:
        print(f"  + {l['email']:<38} {l['first_name']:<14} {l['domain']}")
    if len(uniq) > 25:
        print(f"  ... +{len(uniq)-25} more")

    cols = ["email", "first_name", "last_name", "company", "title", "website", "city"]
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        for l in uniq:
            w.writerow({"email": l["email"], "first_name": l["first_name"], "last_name": "",
                        "company": "", "title": "", "website": "https://" + l["domain"], "city": ""})
    print(f"wrote {a.out}")

    if a.do_import and uniq:
        print("importing into diraya pool (niche=diraya_smb) ...")
        r = subprocess.run(["py", "scripts/import-prospects-csv.py", "diraya", a.out, "--niche", "diraya_smb"],
                           cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace")
        print((r.stdout or "")[-600:]); print((r.stderr or "")[-300:])
    return 0


if __name__ == "__main__":
    sys.exit(main())
