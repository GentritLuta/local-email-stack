# -*- coding: utf-8 -*-
"""POC: scrape Diraya's ICP where they actually leave a real email — GitHub.
Search AI/LLM repos -> read commit-author emails -> keep COMPANY-DOMAIN emails
(skip gmail/free-mail + github noreply) -> derive first_name + company. These are
technical people (engineers/CTOs/founders) at companies building AI features.

POC only: prints candidates + counts, does NOT upsert. Unauthenticated GitHub API
(60 core req/hr) so it's capped small. With a token we scale 80x."""
import sys, json, time, urllib.request, urllib.parse
from collections import Counter
from pathlib import Path
REPO = Path(r"C:\Users\bernh\local-email-stack")
sys.path.insert(0, str(REPO / "sequences"))
from name_derive import is_free_or_isp_domain, derive_first_name, derive_company  # noqa

GH = "https://api.github.com"
H = {"User-Agent": "Mozilla/5.0", "Accept": "application/vnd.github+json"}
QUERIES = [
    "rag llm in:name,description stars:8..400 pushed:>2026-02-01",
    "llm agent production in:name,description stars:8..400 pushed:>2026-02-01",
    "vector search rag in:name,description stars:5..300 pushed:>2026-01-01",
]

def gh(path):
    try:
        r = urllib.request.urlopen(urllib.request.Request(GH + path, headers=H), timeout=25)
        return json.loads(r.read()), r.headers.get("X-RateLimit-Remaining")
    except urllib.error.HTTPError as e:
        return {"_err": e.code, "_msg": e.read()[:80].decode("utf-8", "replace")}, None
    except Exception as e:
        return {"_err": str(e)[:60]}, None

# 1) collect repos
repos = []
for q in QUERIES:
    d, rem = gh("/search/repositories?per_page=12&sort=updated&q=" + urllib.parse.quote(q))
    for it in d.get("items", []):
        repos.append(it["full_name"])
    time.sleep(2)  # search is 10/min unauth
repos = list(dict.fromkeys(repos))[:24]
print(f"repos found: {len(repos)}")

# 2) mine commit-author emails
leads = {}            # email -> dict
skipped = Counter()
for full in repos:
    d, rem = gh(f"/repos/{full}/commits?per_page=60")
    if isinstance(d, dict) and d.get("_err"):
        skipped["api_" + str(d.get("_err"))] += 1
        if d.get("_err") == 403:    # rate limited -> stop
            print("  rate-limited, stopping at", full, "| remaining:", rem); break
        continue
    for c in d:
        a = (c.get("commit") or {}).get("author") or {}
        email = (a.get("email") or "").lower().strip()
        name = (a.get("name") or "").strip()
        if not email or "@" not in email:
            continue
        dom = email.split("@")[-1]
        if "noreply" in email or dom.endswith("users.noreply.github.com"):
            skipped["noreply"] += 1; continue
        if is_free_or_isp_domain(dom):
            skipped["free_mail"] += 1; continue
        if email in leads:
            continue
        leads[email] = {"email": email, "name": name, "company": derive_company(email),
                        "first": derive_first_name(email), "repo": full}

print(f"\nskipped: {dict(skipped)}")
print(f"COMPANY-DOMAIN leads found: {len(leads)}")
print("\nsample (first 25):")
for e, v in list(leads.items())[:25]:
    print(f"  {v['email']:<38} name={v['name'][:20]:<20} company={str(v['company'])[:22]:<22} repo={v['repo'][:30]}")
# domain spread (are these real companies?)
doms = Counter(e.split("@")[-1] for e in leads)
print("\ntop lead domains:", dict(doms.most_common(12)))
