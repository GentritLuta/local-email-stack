# -*- coding: utf-8 -*-
"""Probe 3: the robust, Algolia-free path. (1) Does /companies HTML server-render
/companies/{slug} links? (2) Does a company page expose founders + website in
embedded JSON? (3) Is there a sitemap enumerating all company URLs?"""
import re, json, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=25).read().decode("utf-8","replace")

# (1) directory links
html = get("https://www.ycombinator.com/companies")
slugs = sorted(set(re.findall(r'/companies/([a-z0-9][a-z0-9\-]+)(?:["/?])', html)))
slugs = [s for s in slugs if s not in ("founders","industry","location")]
print("(1) /companies/{slug} links in directory HTML:", len(slugs), "->", slugs[:8])

# (2) a company page — try a few well-known YC cos, dump where founders+website live
for slug in (slugs[:1] or []) + ["airbnb","stripe","retool"]:
    try:
        p = get(f"https://www.ycombinator.com/companies/{slug}")
    except Exception as e:
        print(f"(2) {slug}: fetch err {e}"); continue
    has_nd = 'id="__NEXT_DATA__"' in p
    nd = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', p, re.S)
    info = {}
    if nd:
        try:
            d = json.loads(nd.group(1))
            blob = json.dumps(d)
            pp = d.get("props",{}).get("pageProps",{})
            # find a 'company' object
            comp = pp.get("company") or {}
            info["pageProps_keys"] = list(pp.keys())
            info["company_keys"] = sorted(comp.keys())[:30]
            info["website"] = comp.get("website")
            fnd = comp.get("founders") or comp.get("team") or []
            info["founders"] = [(f.get("full_name") or f.get("name"), f.get("title")) for f in fnd][:6] if isinstance(fnd,list) else fnd
        except Exception as e:
            info["nd_err"] = str(e)[:80]
    print(f"(2) {slug}: NEXT_DATA={has_nd}  website={info.get('website')}  founders={info.get('founders')}")
    if info.get("company_keys"): print("      company_keys:", info["company_keys"])
    if info.get("pageProps_keys"): print("      pageProps_keys:", info["pageProps_keys"])
    if slug in slugs[:1] or info.get("founders"): break

# (3) sitemap
for sm in ("https://www.ycombinator.com/sitemap.xml","https://www.ycombinator.com/companies/sitemap.xml"):
    try:
        x = get(sm)
        locs = re.findall(r'<loc>([^<]+)</loc>', x)
        comp_locs = [l for l in locs if "/companies/" in l]
        print(f"(3) {sm}: {len(locs)} locs, {len(comp_locs)} company locs; sub-sitemaps:",
              [l for l in locs if l.endswith('.xml')][:5])
    except Exception as e:
        print(f"(3) {sm}: {e}")
