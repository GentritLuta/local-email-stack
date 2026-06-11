# -*- coding: utf-8 -*-
"""Verify a curated attorney referral list is REAL + accurate before it ships.
Per firm: (1) website loads, (2) the firm or lead attorney name appears on the
site, (3) a practice keyword (estate/probate/divorce/family) appears, (4) email
domain has MX, (5) phone is a valid 10-digit number in the metro's area codes,
(6) website domain and email domain are consistent. Flags anything suspicious."""
import sys, csv, re, urllib.request, socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
REPO = Path(r"C:\Users\bernh\local-email-stack")
sys.path.insert(0, str(REPO / "sequences"))
import lead_verify as lv  # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CSVF = REPO / "referral-lists" / "Attorney-Referral-List-Indianapolis.csv"
METRO_ACS = {"317", "463"}                      # Indianapolis area codes
PRACTICE = re.compile(r"estate|probate|divorce|family|elder|trust|guardianship|wills?|attorney|law", re.I)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123 Safari/537.36"
STOP = {"law", "llc", "pllc", "llp", "pc", "attorney", "attorneys", "office", "offices",
        "group", "firm", "the", "and", "&", "of", "at", "p.c.", "co"}


def fetch(url):
    if not url: return None, "no-url"
    if not url.startswith("http"): url = "https://" + url
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=15)
        return r.read().decode("utf-8", "replace").lower(), "ok"
    except urllib.error.HTTPError as e:
        return None, f"http{e.code}"     # exists but blocked (403) or gone (404)
    except Exception as e:
        return None, type(e).__name__


def tokens(firm):
    return [t for t in re.split(r"[^a-z0-9]+", firm.lower()) if len(t) > 3 and t not in STOP]


def dom(s):
    m = re.search(r"https?://([^/]+)", s if s.startswith("http") else "http://" + s)
    d = (m.group(1) if m else s).lower().replace("www.", "")
    return d.strip("/")


def check(row):
    firm, atty, prac, city, phone, email, website, addr = row[0], row[2], row[3], row[4], row[5], row[6], row[7], row[8]
    out = {"firm": firm, "atty": atty}
    # website + content
    html, st = fetch(website)
    out["web"] = st
    if html:
        toks = tokens(firm); last = (atty.split()[-1].lower() if atty else "")
        out["name_on_site"] = any(t in html for t in toks) or (len(last) > 2 and last in html)
        out["practice_on_site"] = bool(PRACTICE.search(html))
    else:
        out["name_on_site"] = out["practice_on_site"] = None
    # email MX + consistency
    if email:
        out["email_mx"] = lv.verify(email, do_smtp_probe=False).verified
        out["dom_match"] = (website and dom(email.split("@")[-1]) == dom(website))
    else:
        out["email_mx"] = out["dom_match"] = None
    # phone
    d = re.sub(r"\D", "", phone or "")
    if len(d) == 11 and d.startswith("1"): d = d[1:]
    out["phone_ok"] = len(d) == 10
    out["phone_metro"] = d[:3] in METRO_ACS if len(d) == 10 else False
    return out


rows = list(csv.reader(CSVF.open(encoding="utf-8-sig")))[1:]
print(f"verifying {len(rows)} firms in {CSVF.name} ...\n")
results = []
with ThreadPoolExecutor(max_workers=12) as ex:
    futs = [ex.submit(check, r) for r in rows]
    for f in as_completed(futs):
        results.append(f.result())

# summary
loaded = [r for r in results if r["web"] == "ok"]
blocked = [r for r in results if r["web"].startswith("http") and r["web"] != "ok"]
dead = [r for r in results if r["web"] not in ("ok",) and not r["web"].startswith("http")]
name_ok = [r for r in loaded if r["name_on_site"]]
prac_ok = [r for r in loaded if r["practice_on_site"]]
mx_ok = sum(1 for r in results if r["email_mx"])
have_email = sum(1 for r in results if r["email_mx"] is not None)
phone_ok = sum(1 for r in results if r["phone_ok"])
phone_metro = sum(1 for r in results if r["phone_metro"])
print(f"WEBSITE : {len(loaded)} load OK | {len(blocked)} exist-but-block(403/4xx) | {len(dead)} unreachable {[r['web'] for r in dead]}")
print(f"  of loaded: {len(name_ok)}/{len(loaded)} show the firm/attorney name | {len(prac_ok)}/{len(loaded)} show a practice keyword")
print(f"EMAIL   : {mx_ok}/{have_email} with a valid-MX domain ({len(results)-have_email} firms have no email listed)")
print(f"PHONE   : {phone_ok}/{len(results)} valid 10-digit | {phone_metro}/{len(results)} in Indy area codes (317/463)")
print("\nFLAGGED (unreachable site, OR loaded-but-no-name, OR bad phone):")
flagged = [r for r in results if r["web"] in (d2 for d2 in [r2["web"] for r2 in dead])
           or (r["web"] == "ok" and not r["name_on_site"]) or not r["phone_ok"]]
for r in (flagged or [])[:12]:
    print(f"  - {r['firm'][:34]:<34} web={r['web']:<8} name_on_site={r['name_on_site']} phone_ok={r['phone_ok']}")
if not flagged: print("  none")
