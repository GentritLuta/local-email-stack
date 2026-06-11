# -*- coding: utf-8 -*-
"""Probe 2: find the JS bundle that holds YC's Algolia search key, then query
the company index and dump one hit's full field schema."""
import re, json, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
def get(url, data=None, headers=None):
    h = {"User-Agent": UA}
    if headers: h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")

html = get("https://www.ycombinator.com/companies")
srcs = re.findall(r'<script[^>]+src="([^"]+)"', html)
print("script srcs:", len(srcs))
APP = "45BWZJ1SGC"
key = None
for s in srcs:
    url = s if s.startswith("http") else ("https://www.ycombinator.com" + s)
    try:
        js = get(url)
    except Exception as e:
        continue
    if "algolia" in js.lower() or APP in js:
        # search-only keys appear right next to the app id
        for m in re.finditer(r'["\']([A-Za-z0-9]{32,})["\']', js):
            tok = m.group(1)
            ctx = js[max(0, m.start()-120):m.start()]
            if APP in ctx or "algolia" in ctx.lower() or "apiKey" in ctx or "searchKey" in ctx:
                print("  candidate key in", url.split("/")[-1], "->", tok[:20], "...", len(tok))
                key = key or tok
        if key: break
print("KEY:", (key[:24]+"...") if key else None)

if key:
    body = json.dumps({"requests":[{"indexName":"YCCompany_production",
        "params":"hitsPerPage=5&query=artificial%20intelligence"}]}).encode()
    res = get(f"https://{APP.lower()}-dsn.algolia.net/1/indexes/*/queries",
              data=body, headers={"X-Algolia-API-Key":key,"X-Algolia-Application-Id":APP,
                                  "Content-Type":"application/json"})
    d = json.loads(res)
    hits = d.get("results",[{}])[0].get("hits",[])
    print("\nhits:", len(hits))
    if hits:
        print("FIELD KEYS:", sorted(hits[0].keys()))
        h0 = hits[0]
        for k in ("name","slug","website","all_locations","long_description","industries","subindustry","tags","batch","team_size","founders"):
            v = h0.get(k)
            print(f"  {k}: {str(v)[:90]}")
