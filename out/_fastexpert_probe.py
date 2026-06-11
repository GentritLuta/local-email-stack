# -*- coding: utf-8 -*-
"""Probe FastExpert as a structured RE source: does the agent sitemap enumerate
profiles, and does a profile page expose name + brokerage + a published email or
brokerage website we can harvest?"""
import re, json, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
def get(url):
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=20).read().decode("utf-8","replace")
    except Exception as e:
        return f"__ERR__ {type(e).__name__} {str(e)[:60]}"

sm = get("https://www.fastexpert.com/agent-public-profile-sitemap.xml")
if sm.startswith("__ERR__"):
    print("sitemap err:", sm)
else:
    urls = re.findall(r'<loc>([^<]+)</loc>', sm)
    print("agent profile URLs in sitemap:", len(urls))
    print("  samples:", urls[:3])
    # probe up to 3 profiles for email / website / brokerage
    EMAIL = re.compile(r'[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}')
    for u in urls[:3]:
        p = get(u)
        if p.startswith("__ERR__"):
            print(f"\n{u} -> {p}"); continue
        emails = sorted(set(e for e in EMAIL.findall(p) if "fastexpert" not in e.lower() and not e.lower().endswith(('.png','.jpg'))))
        ext = re.findall(r'href="(https?://(?!www\.fastexpert)[^"]+)"', p)
        ext = [e for e in ext if not re.search(r'(facebook|instagram|linkedin|twitter|youtube|google|apple|zillow|realtor)\.', e)]
        name = re.search(r'<title>([^<|]+)', p)
        brokerage = re.search(r'(?:Brokerage|Broker|Company|works (?:at|for))[^A-Za-z0-9]{0,8}([A-Z][A-Za-z0-9&\.,\' ]{3,40})', p)
        ld = re.search(r'"email"\s*:\s*"([^"]+)"', p) or re.search(r'"telephone"\s*:\s*"([^"]+)"', p)
        print(f"\n{u.split('/')[-1]}")
        print("  title:", (name.group(1).strip()[:50] if name else None))
        print("  emails on page:", emails[:4])
        print("  ld-json email/phone:", ld.group(1) if ld else None)
        print("  brokerage guess:", brokerage.group(1).strip() if brokerage else None)
        print("  ext links (non-social):", ext[:4])
