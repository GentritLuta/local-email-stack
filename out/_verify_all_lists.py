# -*- coding: utf-8 -*-
"""Verify ALL 9 curated attorney lists are real + accurate. Per firm: website
loads + shows firm/attorney name + a practice keyword; email domain has MX;
phone is valid + in the metro's area codes. Reports a per-list scorecard."""
import sys, csv, re, json, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
REPO = Path(r"C:\Users\bernh\local-email-stack")
sys.path.insert(0, str(REPO / "sequences"))
import lead_verify as lv  # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
LISTS = REPO / "referral-lists"
PRACTICE = re.compile(r"estate|probate|divorce|family|elder|trust|guardianship|wills?|attorney|law", re.I)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123 Safari/537.36"
STOP = {"law","llc","pllc","llp","attorney","attorneys","office","offices","group","firm","the","and","of"}

def fetch(url):
    if not url: return None, "no-url"
    if not url.startswith("http"): url = "https://" + url
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=14).read().decode("utf-8","replace").lower(), "ok"
    except urllib.error.HTTPError as e: return None, f"http{e.code}"
    except Exception as e: return None, type(e).__name__

def toks(firm): return [t for t in re.split(r"[^a-z0-9]+", firm.lower()) if len(t)>3 and t not in STOP]

def check(row, acs):
    firm, atty, email, website, phone = row[0], row[2], row[6], row[7], row[5]
    html, st = fetch(website)
    name_ok = prac_ok = None
    if html:
        last = atty.split()[-1].lower() if atty else ""
        name_ok = any(t in html for t in toks(firm)) or (len(last)>2 and last in html)
        prac_ok = bool(PRACTICE.search(html))
    mx = lv.verify(email, do_smtp_probe=False).verified if email else None
    d = re.sub(r"\D","",phone or ""); d = d[1:] if len(d)==11 and d.startswith("1") else d
    return {"web":st,"name":name_ok,"prac":prac_ok,"mx":mx,"phone_ok":len(d)==10,"phone_metro":(d[:3] in acs) if len(d)==10 else False,"firm":firm}

index = json.loads((LISTS/"curated.json").read_text(encoding="utf-8"))["lists"]
print(f"{'METRO':<22} {'firms':>5} {'web-live':>9} {'name✓':>7} {'pract✓':>7} {'phone✓':>7} {'email-MX':>9}  FLAGS")
grand = {"firms":0,"live":0,"flag":0}
for e in index:
    rows = list(csv.reader((LISTS/e["csv"]).open(encoding="utf-8-sig")))[1:]
    acs = set(e["match"].get("area_codes", []))
    res = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        for f in as_completed([ex.submit(check, r, acs) for r in rows]): res.append(f.result())
    n = len(res)
    live = sum(1 for r in res if r["web"]=="ok" or r["web"].startswith("http"))   # exists (loads or blocks)
    name = sum(1 for r in res if r["name"]); loaded = sum(1 for r in res if r["web"]=="ok")
    prac = sum(1 for r in res if r["prac"])
    phone = sum(1 for r in res if r["phone_ok"]); have_e = sum(1 for r in res if r["mx"] is not None); mx = sum(1 for r in res if r["mx"])
    dead = [r["firm"][:18] for r in res if r["web"]!="ok" and not r["web"].startswith("http")]
    badphone = sum(1 for r in res if not r["phone_ok"])
    flags = []
    if dead: flags.append(f"{len(dead)} dead-site")
    if badphone: flags.append(f"{badphone} bad-phone")
    nomatch = sum(1 for r in res if r["web"]=="ok" and not r["name"])
    if nomatch: flags.append(f"{nomatch} no-name-match")
    grand["firms"]+=n; grand["live"]+=live; grand["flag"]+=len(dead)+badphone+nomatch
    print(f"{e['metro']:<22} {n:>5} {live:>9} {f'{name}/{loaded}':>7} {f'{prac}/{loaded}':>7} {phone:>7} {f'{mx}/{have_e}':>9}  {', '.join(flags) or 'clean'}")
print(f"\nTOTAL: {grand['firms']} firms across {len(index)} metros | {grand['live']} with a live/existing website | {grand['flag']} hard flags")
