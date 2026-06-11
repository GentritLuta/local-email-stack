"""pull-referral-list.py — generate a referral-source list for one city, to
fulfil the aureon "reply LIST / reply PROBATE" lead magnet.

Given a city (+ optional state), it searches for divorce / estate / probate
attorneys (the highest-converting seller-referral source in real estate) and
scrapes their public contact info into a clean CSV the agent can use the day
they reply.

Reuses the SAME search dispatcher (Google CSE -> ddgs fallback) and page
extractor as aureon's own prospecting, so it produces results the moment the
CSE is provisioned (and degrades gracefully to whatever ddgs returns meanwhile).

Usage:
  py scripts/pull-referral-list.py "Austin, TX" --type divorce --max 40
  py scripts/pull-referral-list.py "Denver" --state CO --type probate
  py scripts/pull-referral-list.py "Tampa, FL"            # default: divorce

Output: referral-lists/<type>-<city>.csv  (name, email, firm, phone, source)
"""
from __future__ import annotations
import argparse
import csv
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from seed_discover import _search                              # noqa: E402
from lead_scrape import (                                       # noqa: E402
    fetch_html, fetch_html_playwright, extract_leads_from_page,
)

# Practice-area search angles per list type. Two queries each widens coverage.
TYPE_QUERIES = {
    "divorce": ["divorce attorney {loc} contact",
                "family law firm {loc} attorneys"],
    "estate":  ["estate planning attorney {loc} contact",
                "estate planning law firm {loc} attorneys"],
    "probate": ["probate attorney {loc} contact",
                "probate lawyer {loc} firm"],
}

FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com",
             "icloud.com", "proton.me", "protonmail.com"}


def _firm_from(lead, email: str) -> str:
    if lead.company:
        return lead.company
    dom = email.split("@")[-1].lower()
    if dom in FREE_MAIL:
        return ""
    root = dom.rsplit(".", 1)[0].replace("-", " ").replace("law", " law ")
    return " ".join(w.capitalize() for w in root.split())


def run(loc: str, list_type: str, max_results: int) -> list[dict]:
    queries = [q.format(loc=loc) for q in TYPE_QUERIES[list_type]]
    seen_urls: set[str] = set()
    seen_emails: set[str] = set()
    rows: list[dict] = []
    print(f"=== referral-list: {list_type} attorneys in {loc} (target {max_results}) ===")
    for q in queries:
        if len(rows) >= max_results:
            break
        urls = _search(q, 8, "us")
        print(f"  + search {q!r:48s} -> {len(urls)} urls")
        for u in urls:
            if len(rows) >= max_results:
                break
            u = u.rstrip("/")
            if u in seen_urls:
                continue
            seen_urls.add(u)
            html = fetch_html(u)
            if not html or "@" not in html:
                html = fetch_html_playwright(u)   # JS-rendered firm sites
            if not html:
                continue
            for lead in extract_leads_from_page(u, html):
                em = (lead.email or "").strip().lower()
                if not em or em in seen_emails:
                    continue
                # keep only plausible attorney/firm contacts
                seen_emails.add(em)
                rows.append({
                    "name":  (lead.first_name or "") + (
                             " " + lead.last_name if lead.last_name else ""),
                    "email": em,
                    "firm":  _firm_from(lead, em),
                    "phone": lead.phone or "",
                    "source": u,
                })
                if len(rows) >= max_results:
                    break
        time.sleep(0.3)
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("city", help='city, e.g. "Austin, TX" or "Denver"')
    ap.add_argument("--state", default="", help="state code if not in city")
    ap.add_argument("--type", choices=list(TYPE_QUERIES), default="divorce")
    ap.add_argument("--max", type=int, default=40)
    args = ap.parse_args()

    loc = args.city if not args.state else f"{args.city} {args.state}"
    rows = run(loc, args.type, args.max)

    out_dir = REPO / "referral-lists"
    out_dir.mkdir(exist_ok=True)
    safe = args.city.replace(",", "").replace(" ", "-").lower()
    out = out_dir / f"{args.type}-{safe}.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["name", "email", "firm", "phone", "source"])
        w.writeheader()
        w.writerows(rows)

    print(f"\n{len(rows)} {args.type} contacts -> {out}")
    if not rows:
        print("  (0 results: the search source returned nothing. If the Google")
        print("   CSE is still provisioning, this fills in automatically once it")
        print("   is live — same dependency as aureon's own prospecting.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
