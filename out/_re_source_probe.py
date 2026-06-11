# -*- coding: utf-8 -*-
"""Probe: which US real-estate sources expose a CLEAN structured enumeration of
brokerage/agent pages (a YC-sitemap analog) we can harvest published emails from?
Check sitemaps + directory structure of franchise locators + indie directories."""
import re, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
def get(url, n=4000):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15).read().decode("utf-8","replace")
    except Exception as e:
        return f"__ERR__ {type(e).__name__} {str(e)[:60]}"

CANDIDATES = {
    "century21 offices":   "https://www.century21.com/sitemap.xml",
    "remax offices":       "https://www.remax.com/sitemap.xml",
    "exp realty":          "https://exprealty.com/sitemap.xml",
    "coldwellbanker":      "https://www.coldwellbanker.com/sitemap.xml",
    "kw":                  "https://www.kw.com/sitemap.xml",
    "fastexpert":          "https://www.fastexpert.com/sitemap.xml",
    "clever discount":     "https://listwithclever.com/sitemap.xml",
}
for name, url in CANDIDATES.items():
    body = get(url)
    if body.startswith("__ERR__"):
        print(f"{name:<22} {body}"); continue
    locs = re.findall(r'<loc>([^<]+)</loc>', body)
    sub_sitemaps = [l for l in locs if l.endswith('.xml')]
    # office/agent-looking URLs
    officeish = [l for l in locs if re.search(r'/(office|offices|agent|agents|broker|company|real-estate-offices|locations?)/', l, re.I)]
    print(f"{name:<22} locs={len(locs):<5} sub-sitemaps={len(sub_sitemaps):<3} office/agent-urls={len(officeish)}")
    if sub_sitemaps[:3]: print("      sub:", [s.split('/')[-1] for s in sub_sitemaps[:5]])
    if officeish[:2]: print("      ex :", officeish[:2])
