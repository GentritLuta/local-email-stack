# -*- coding: utf-8 -*-
"""Free, port-25-free verification: scrape each YC AI-startup's OWN site for a
published founder email (mailto:/contact/team). Published == real (no guessing,
no bounce risk). Input = the LinkedIn worksheet (domain + founder names). MX-verify
only (we can't SMTP). Output: real emails matched to founders -> Diraya-ready.
Test mode: caps to the freshest N domains to gauge yield before scaling."""
import re, sys, csv, argparse, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
REPO = Path(r"C:\Users\bernh\local-email-stack")
sys.path.insert(0, str(REPO / "sequences"))
import lead_verify as lv  # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
EMAIL_RX = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
PAGES = ["", "about", "about-us", "team", "company", "contact", "contact-us", "founders"]

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
            # keep only emails on the company's OWN domain (root match)
            if root(ed) == root(domain) or root(ed).endswith("." + root(domain)):
                found.add(e)
        if len(found) >= 8:
            break
    return found

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=150, help="freshest N domains to scan")
    ap.add_argument("--workers", type=int, default=16)
    ap.add_argument("--in", dest="inp", default=str(REPO / "out" / "diraya_linkedin_targets.csv"))
    ap.add_argument("--out", default=str(REPO / "out" / "diraya_site_emails.csv"))
    args = ap.parse_args()

    rows = list(csv.DictReader(open(args.inp, encoding="utf-8")))
    by_dom = defaultdict(list)
    for r in rows:
        if r.get("domain"):
            by_dom[r["domain"]].append(r)
    domains = list(by_dom.keys())[:args.limit]   # CSV already sorted newest-first
    print(f"scanning {len(domains)} freshest domains for published emails ...")

    hits, scanned = [], 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(emails_on_site, d): d for d in domains}
        for fut in as_completed(futs):
            scanned += 1
            dom = futs[fut]
            if scanned % 40 == 0:
                print(f"  scanned {scanned}/{len(domains)}  raw-hits={len(hits)}")
            for email in fut.result():
                local = email.split("@")[0]
                if local in lv.JUNK_LOCAL_PARTS:        # drop noreply/support/billing/etc
                    continue
                # match to a founder by name
                who = None
                for f in by_dom[dom]:
                    fn, ln = f.get("first","").lower(), f.get("last","").lower()
                    if (fn and fn in local) or (ln and len(ln) > 2 and ln in local):
                        who = f; break
                hits.append({"email": email, "domain": dom, "matched": bool(who),
                             "founder": (who or by_dom[dom][0]),
                             "is_role": local in lv.ADMITTABLE_ROLE_LOCALS})

    # MX-verify + dedupe
    seen, verified = set(), []
    for h in hits:
        if h["email"] in seen: continue
        seen.add(h["email"])
        r = lv.verify(h["email"], do_smtp_probe=False)   # MX-only (no port 25)
        if r.verified:
            verified.append(h)

    named = [h for h in verified if h["matched"]]
    print(f"\n=== site-scrape yield ===")
    print(f"  domains scanned : {len(domains)}")
    print(f"  real emails (MX-verified, on-domain, non-junk): {len(verified)}")
    print(f"  matched to a named founder                    : {len(named)}")
    print(f"  role/company inboxes (info@/founders@/...)     : {len(verified)-len(named)}")
    print("\n  sample named:")
    for h in named[:15]:
        f = h["founder"]
        print(f"    {h['email']:<34} {f.get('full_name','')[:20]:<20} {f.get('company','')[:22]:<22} {f.get('batch','')}")

    cols = ["email","first_name","last_name","company","title","website","city"]
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        for h in named:
            f = h["founder"]
            w.writerow({"email": h["email"], "first_name": (f.get("full_name") or "").split()[0] if f.get("full_name") else f.get("first","").title(),
                        "last_name": f.get("last","").title(), "company": f.get("company",""),
                        "title": f.get("title",""), "website": f.get("website",""), "city": f.get("city","")})
    print(f"\n  named founders -> {args.out}  ({len(named)} rows, Diraya-import-ready)")

if __name__ == "__main__":
    main()
