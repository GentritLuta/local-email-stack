# -*- coding: utf-8 -*-
"""diraya-site-scrape.py — FREE, port-25-free Diraya lead source.

Diraya's ICP (early-stage AI founders) is NOT cold-scrapeable for emails and
guess+verify needs port 25 (blocked on every box we have). So instead we harvest
the founder emails the YC AI-startups ALREADY PUBLISH on their own sites
(mailto: / contact / team pages), MX-verify them, match to founder names, and
import the named ones into the diraya pool. Published == real == ~zero bounce.

Input = the YC worksheet from yc-guess-verify.py --no-verify (domain + founders).
This is the schedulable engine behind diraya's lead pool.

Usage:
  py scripts/diraya-site-scrape.py --limit 1382 --import        # full harvest + import
  py scripts/diraya-site-scrape.py --limit 250                  # scrape only -> CSV
"""
import re, sys, csv, argparse, subprocess, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
import lead_verify as lv  # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
EMAIL_RX = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
PAGES = ["", "about", "team", "contact", "company"]   # highest-yield pages

def get(url):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=9).read().decode("utf-8", "replace")
    except Exception:
        return ""

def root(dom):
    return dom[4:] if dom.startswith("www.") else dom

def emails_on_site(domain):
    found = set()
    base = f"https://{domain}".rstrip("/")
    for pg in PAGES:
        html = get(f"{base}/{pg}" if pg else base)
        if not html:
            continue
        for e in EMAIL_RX.findall(html):
            e = e.lower().strip(".")
            ed = e.split("@")[-1]
            if root(ed) == root(domain) or root(ed).endswith("." + root(domain)):
                found.add(e)
        if len(found) >= 8:
            break
    return found

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=2000, help="freshest N domains to scan")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--in", dest="inp", default=str(REPO / "out" / "diraya_linkedin_targets.csv"))
    ap.add_argument("--out", default=str(REPO / "out" / "diraya_site_emails.csv"))
    ap.add_argument("--import", dest="do_import", action="store_true",
                    help="after writing the CSV, import named founders into the diraya pool")
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.inp, encoding="utf-8")))
    by_dom = defaultdict(list)
    for r in rows:
        if r.get("domain"):
            by_dom[r["domain"]].append(r)
    domains = list(by_dom.keys())[:args.limit]
    print(f"scanning {len(domains)} domains for published founder emails ...")

    # Per-batch wall-clock budget so a few hung sockets can never stall the whole
    # run (the old unbounded as_completed + fut.result() was the cause of multi-hour
    # hangs — one slow-drip domain blocked forever and the end-of-run import never
    # fired). Stragglers past the budget are abandoned; we keep every hit found so far.
    import concurrent.futures as _cf
    BATCH_TIMEOUT = int(__import__("os").environ.get("HARVEST_BATCH_TIMEOUT", "420"))
    hits, scanned = [], 0
    # NOTE: not using `with` — ThreadPoolExecutor.__exit__ does shutdown(wait=True),
    # which would block on hung worker threads. We shut down non-blocking instead.
    ex = ThreadPoolExecutor(max_workers=args.workers)
    futs = {ex.submit(emails_on_site, d): d for d in domains}
    try:
        for fut in as_completed(futs, timeout=BATCH_TIMEOUT):
            scanned += 1
            dom = futs[fut]
            if scanned % 100 == 0:
                print(f"  scanned {scanned}/{len(domains)}  raw-hits={len(hits)}")
            try:
                emails = fut.result(timeout=1)
            except Exception:
                continue   # this domain timed out / errored — skip it
            for email in emails:
                local = email.split("@")[0]
                if local in lv.JUNK_LOCAL_PARTS:
                    continue
                who = None
                for f in by_dom[dom]:
                    fn, ln = f.get("first", "").lower(), f.get("last", "").lower()
                    if (fn and fn in local) or (ln and len(ln) > 2 and ln in local):
                        who = f; break
                hits.append({"email": email, "domain": dom, "matched": bool(who),
                             "founder": (who or by_dom[dom][0])})
    except _cf.TimeoutError:
        print(f"  batch budget {BATCH_TIMEOUT}s hit — abandoning "
              f"{len(futs)-scanned} slow domains, keeping {len(hits)} hits")
    # Non-blocking shutdown: cancel queued work, do NOT wait on running threads
    # (a hung socket thread would otherwise block process exit).
    ex.shutdown(wait=False, cancel_futures=True)

    seen, named = set(), []
    for h in hits:
        if h["email"] in seen or not h["matched"]:
            continue
        seen.add(h["email"])
        if lv.verify(h["email"], do_smtp_probe=False).verified:   # MX-only (no port 25)
            named.append(h)

    cols = ["email", "first_name", "last_name", "company", "title", "website", "city"]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        for h in named:
            f = h["founder"]
            w.writerow({"email": h["email"],
                        "first_name": (f.get("full_name") or "").split()[0] if f.get("full_name") else f.get("first", "").title(),
                        "last_name": f.get("last", "").title(), "company": f.get("company", ""),
                        "title": f.get("title", ""), "website": f.get("website", ""), "city": f.get("city", "")})
    print(f"\n=== {len(named)} named founders (MX-verified, published) -> {args.out}")

    if args.do_import and named:
        print("importing into diraya pool ...")
        r = subprocess.run(["py", "scripts/import-prospects-csv.py", "diraya", args.out, "--niche", "yc_ai"],
                           cwd=str(REPO), capture_output=True, text=True, encoding="utf-8", errors="replace")
        print((r.stdout or "")[-600:]); print((r.stderr or "")[-300:])

if __name__ == "__main__":
    main()
