# -*- coding: utf-8 -*-
"""Probe: can we read YC's company directory? Find the Algolia app-id + search key
the page uses, then query it for AI companies and dump the field schema (does a hit
carry website + founders?). Read-only recon before building the real pipeline."""
import re, json, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"

def get(url, data=None, headers=None):
    h = {"User-Agent": UA}
    if headers: h.update(headers)
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    return urllib.request.urlopen(req, timeout=25).read().decode("utf-8", "replace")

html = get("https://www.ycombinator.com/companies")
print("page bytes:", len(html))
# Algolia app id is a 10-char A-Z0-9 token; search key is a long hex-ish string.
appids = sorted(set(re.findall(r'"([A-Z0-9]{10})"', html)))
print("candidate app ids:", appids[:20])
# look for algolia key near 'algolia' or 'apiKey'
for m in re.finditer(r'(algolia[^"]{0,30}|apiKey|api_key|searchKey)["\']?\s*[:=]\s*["\']([A-Za-z0-9]{20,})', html, re.I):
    print("  key-ctx:", m.group(0)[:90])
# also dump any 32+ char hex tokens (algolia search keys are ~64 hex)
hexes = sorted(set(re.findall(r'"([a-f0-9]{32,})"', html)))
print("hex tokens >=32:", [h[:16]+'...' for h in hexes[:10]])
# is there a __NEXT_DATA__ with companies?
nd = re.search(r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
if nd:
    try:
        data = json.loads(nd.group(1))
        keys = list((data.get("props", {}).get("pageProps", {}) or {}).keys())
        print("__NEXT_DATA__ pageProps keys:", keys)
        blob = json.dumps(data)
        for tok in ("algolia", "Algolia", "ALGOLIA", "appId", "apiKey", "indexName"):
            i = blob.find(tok)
            if i >= 0: print(f"  ND[{tok}]:", blob[i:i+80])
    except Exception as e:
        print("ND parse err:", e)
