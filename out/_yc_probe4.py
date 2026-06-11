# -*- coding: utf-8 -*-
"""Probe 4: extract the Inertia.js data-page JSON from a YC company page and map
where website / founders / industry / batch live."""
import re, json, html as ihtml, urllib.request
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=25).read().decode("utf-8","replace")

for slug in ("stripe","retool","airbnb"):
    p = get(f"https://www.ycombinator.com/companies/{slug}")
    m = re.search(r'data-page="([^"]+)"', p)
    if not m:
        print(slug, "no data-page; len", len(p)); continue
    data = json.loads(ihtml.unescape(m.group(1)))
    props = data.get("props", {})
    comp = props.get("company") or props.get("company_data") or {}
    if not comp:  # find the dict with a 'website' or 'name'
        for k, v in props.items():
            if isinstance(v, dict) and ("website" in v or "founders" in v): comp = v; break
    print(f"\n=== {slug} ===  props keys: {list(props.keys())}")
    print("company keys:", sorted(comp.keys()))
    for k in ("name","website","url","slug","one_liner","long_description","industry","industries","subindustry","tags","batch","team_size","status","former_names"):
        if k in comp: print(f"  {k}: {str(comp[k])[:80]}")
    fnd = comp.get("founders") or comp.get("team_members") or []
    print("  founders:", [(f.get("full_name") or f.get("name"), f.get("title"), f.get("linkedin") or f.get("linkedin_url")) for f in fnd][:6] if isinstance(fnd,list) else fnd)
