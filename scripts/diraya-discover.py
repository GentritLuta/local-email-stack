# -*- coding: utf-8 -*-
"""diraya-discover.py — grow Diraya's lead pool BEYOND YC, $0 and zero-bounce.

Diraya mails only founders who PUBLISH an email on their own site (bounce ~0). The
YC sitemap was one source; this adds more, each producing the same (company, website,
domain) rows that get APPENDED to the harvest worksheet (out/diraya_linkedin_targets.csv)
so diraya-site-scrape harvests their published emails next.

Sources (best-effort, isolated — one failing never breaks the others):
  1. CSE search   — Google CSE queries for seed-stage AI startups -> company sites.
                    The workhorse: $0, no new key, reuses seed_discover._search.
  2. Accelerators — server-rendered portfolio pages (Antler etc.) -> company links.
                    JS-only portfolios (Techstars/500) are skipped; need a browser.
  3. Product Hunt — AI-topic launches via PH's GraphQL API (needs a free PH token in
                    sequences/producthunt.env). Skipped (ready) until a token is set.

Deduped against the existing worksheet + the live Diraya prospect pool, so we never
re-add a company already in the funnel. Wired into diraya-harvest-full.py.

  py scripts/diraya-discover.py            # discover + append to the worksheet
  py scripts/diraya-discover.py --dry      # show what each source finds, append nothing
  py scripts/diraya-discover.py --cse-queries 15
"""
from __future__ import annotations
import argparse, csv, json, os, re, sys, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
WORKSHEET = REPO / "out" / "diraya_linkedin_targets.csv"
CANDIDATES = REPO / "out" / "diraya_nonyc_candidates.csv"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123 Safari/537.36"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

WS_COLS = ["full_name", "first", "last", "title", "company", "website", "domain",
           "linkedin", "twitter", "batch", "city", "one_liner", "tags"]
# never treat these as a startup company domain
BLOCK = {"google.com", "facebook.com", "twitter.com", "x.com", "linkedin.com", "youtube.com",
         "instagram.com", "github.com", "medium.com", "crunchbase.com", "wellfound.com",
         "angel.co", "producthunt.com", "techstars.com", "500.co", "antler.co", "ycombinator.com",
         "apple.com", "microsoft.com", "amazon.com", "notion.so", "substack.com", "wikipedia.org",
         "forbes.com", "techcrunch.com", "bloomberg.com", "reddit.com", "discord.com", "slack.com",
         "calendly.com", "typeform.com", "gmail.com", "google.co", "goo.gl", "bit.ly", "t.co"}
GOOD_TLD = re.compile(r"\.(com|ai|io|co|app|tech|dev|xyz|so|inc)$")
CSE_QUERIES = [
    "seed funded AI startup", "early stage AI startup founder", "generative AI startup team",
    "machine learning startup about us", "AI agents startup company", "LLM startup founders",
    "AI infrastructure startup", "computer vision startup company", "AI SaaS startup founder",
    "voice AI startup", "AI healthcare startup", "AI fintech startup", "AI devtools startup",
    "applied AI startup seed round", "AI data startup founders",
]


def dom_of(u: str) -> str:
    try:
        h = urlparse(u if u.startswith("http") else "https://" + u).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    except Exception:
        return ""


def good_company(dom: str) -> bool:
    return bool(dom) and dom not in BLOCK and bool(GOOD_TLD.search(dom)) \
        and not dom.endswith((".gov", ".edu", ".org")) and dom.count(".") <= 2 and len(dom) <= 40


def name_from_domain(dom: str) -> str:
    return re.sub(r"[-_]", " ", dom.split(".")[0]).strip().title()


def fetch(url: str) -> str | None:
    try:
        return urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}),
                                      timeout=12).read().decode("utf-8", "replace")
    except Exception:
        return None


def _resolve_redirect(url: str) -> str:
    """Follow a redirect (e.g. Product Hunt's producthunt.com/r/ tracker) to its
    final destination and return that real company domain."""
    if not url:
        return ""
    try:
        r = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=10)
        return dom_of(r.geturl())
    except Exception as e:
        final = getattr(e, "url", "")
        return dom_of(final) if final else ""


# Search returns lots of noise (dictionaries, seed catalogs, news). Gate every
# candidate on its OWN homepage actually reading like an AI startup, so the Diraya
# pool only ever gets real ICP companies — no fabrication, no off-target contacts.
AI_RX = re.compile(r"\b(a\.?i\.?|artificial intelligence|machine learning|\bml\b|\bllm\b|llms|"
                   r"gen ?ai|fine-?tun|inference|foundation model|\bagents?\b|neural|deep learning|"
                   r"computer vision|\bnlp\b|generative)\b", re.I)
NONSTARTUP = re.compile(r"dictionary|encyclopedia|thesaurus|vocabulary|garden|\bseeds?\b|nursery|"
                        r"\bcatalog|wikipedia|university|\bnews\b|newspaper|magazine|recipe|\.gov|template", re.I)
# Diraya official ICP (niches/diraya_ai.yaml): seed-to-Series-B SaaS / health-tech /
# fintech software companies that want AI engineering, not only AI-native startups.
SAAS_RX = re.compile(r"\b(saas|b2b|platform|api|sdk|software|developer|dev ?tool|fintech|"
                     r"payment|lending|insurtech|health ?tech|healthcare|medical|clinical|ehr|"
                     r"analytics|dashboard|workflow|automation|\bcrm\b|\berp\b|marketplace|"
                     r"compliance|cybersecurity|logistics|proptech|edtech|cloud)\b", re.I)
# Hard exclusions from the ICP (competitors / non-buyers).
EXCLUDE_RX = re.compile(r"\b(agency|agencies|staffing|recruit|outsourc|consultanc|white ?label|"
                        r"dev shop|systems integrator|it outsourcing)\b", re.I)


def looks_ai_startup(dom: str) -> bool:
    """ICP gate: AI-native OR a SaaS/health-tech/fintech software company, minus the
    agencies / staffing / outsourcing the offer excludes."""
    if NONSTARTUP.search(dom):
        return False
    html = fetch("https://" + dom)
    if not html:
        return False
    low = html[:25000].lower()
    if NONSTARTUP.search(low[:4000]) or EXCLUDE_RX.search(low[:4000]):
        return False
    return bool(AI_RX.search(low) or SAAS_RX.search(low))


def ai_verify(cands: list[tuple]) -> list[tuple]:
    out = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(looks_ai_startup, c[2]): c for c in cands}
        for f in as_completed(futs):
            try:
                if f.result():
                    out.append(futs[f])
            except Exception:
                pass
    return out


# ----- sources -----
def from_cse(max_queries: int) -> list[tuple]:
    try:
        import seed_discover as sd
    except Exception as e:
        print(f"  cse: seed_discover import failed: {e}"); return []
    found = []
    for q in CSE_QUERIES[:max_queries]:
        try:
            urls = sd._search(q, 10, "us")
        except Exception as e:
            print(f"  cse: search failed ({q[:24]}): {e}"); continue
        for u in urls:
            d = dom_of(u)
            if good_company(d):
                found.append((name_from_domain(d), "https://" + d, d))
    return found


def from_accelerators() -> list[tuple]:
    PORTFOLIOS = ["https://www.antler.co/portfolio"]   # server-rendered only; add more as found
    found = []
    for url in PORTFOLIOS:
        html = fetch(url)
        if not html:
            continue
        for m in set(re.findall(r'https?://(?:www\.)?([a-z0-9-]+\.[a-z]{2,6})', html.lower())):
            if good_company(m):
                found.append((name_from_domain(m), "https://" + m, m))
    return found


def from_producthunt() -> list[tuple]:
    tok = os.environ.get("PRODUCTHUNT_TOKEN", "")
    pe = REPO / "sequences" / "producthunt.env"
    if not tok and pe.exists():
        for ln in pe.read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith("PRODUCTHUNT_TOKEN") and "=" in ln:
                tok = ln.split("=", 1)[1].strip().strip('"')
    if not tok or "paste" in tok or "<" in tok:
        print("  producthunt: no token (sequences/producthunt.env) — skipped (ready when added)")
        return []
    query = {"query": '{ posts(order: RANKING, topic: "artificial-intelligence", first: 50)'
                       ' { edges { node { name website } } } }'}
    try:
        req = urllib.request.Request("https://api.producthunt.com/v2/api/graphql",
                                     data=json.dumps(query).encode(), method="POST",
                                     headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json",
                                              "User-Agent": UA})
        nodes = [e["node"] for e in json.loads(urllib.request.urlopen(req, timeout=20).read())
                 .get("data", {}).get("posts", {}).get("edges", [])]
    except Exception as e:
        print(f"  producthunt: query failed: {e}"); return []
    # PH's `website` is a producthunt.com/r/ tracking redirect -> resolve to the real domain
    found = []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(_resolve_redirect, n.get("website", "")): n for n in nodes}
        for f in as_completed(futs):
            try:
                d = f.result()
            except Exception:
                continue
            n = futs[f]
            if good_company(d):
                found.append((n.get("name") or name_from_domain(d), "https://" + d, d))
    return found


# ----- merge -----
def existing_domains() -> set:
    doms = set()
    if WORKSHEET.exists():
        for r in csv.DictReader(WORKSHEET.open(encoding="utf-8")):
            if r.get("domain"):
                doms.add(r["domain"].lower())
    # also the live Diraya prospect pool (don't re-add anyone already a lead)
    try:
        env = {}
        for ln in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); env[k.strip()] = v.strip()
        U = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"; K = env["SUPABASE_ANON_KEY"]
        req = urllib.request.Request(U + "prospects?profile_slug=eq.diraya&select=email&limit=10000",
                                     headers={"apikey": K, "Authorization": "Bearer " + K})
        for p in json.loads(urllib.request.urlopen(req, timeout=30).read()):
            d = (p.get("email") or "").split("@")[-1].lower()
            if d:
                doms.add(d)
    except Exception as e:
        print(f"  (could not load prospect pool for dedupe: {e})")
    return doms


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--cse-queries", type=int, default=12, help="CSE queries (quota-shared, keep modest)")
    args = ap.parse_args()

    print("discovering non-YC AI startups...")
    cse = from_cse(args.cse_queries); print(f"  cse:          {len(cse)} candidates")
    acc = from_accelerators();        print(f"  accelerators: {len(acc)} candidates")
    ph = from_producthunt();          print(f"  producthunt:  {len(ph)} candidates")

    seen = existing_domains()
    uniq, new_doms = [], set()
    for company, website, dom in cse + acc + ph:
        if dom in seen or dom in new_doms:
            continue
        new_doms.add(dom); uniq.append((company, website, dom))
    print(f"\n{len(uniq)} unique new domains (deduped vs worksheet + {len(seen)} known); AI-verifying homepages...")
    verified = ai_verify(uniq)
    print(f"{len(verified)} confirmed AI startups (off-target/noise dropped)")
    merged = [{c: "" for c in WS_COLS} | {"company": company, "website": website,
              "domain": dom, "batch": "non-yc", "tags": "ai,discovered"}
              for company, website, dom in verified]

    if args.dry:
        for company, website, dom in verified[:15]:
            print(f"  + {dom:<28} {company}")
        if len(verified) > 15:
            print(f"  ... +{len(verified)-15} more")
        return 0

    # write a candidates file + APPEND to the harvest worksheet
    with CANDIDATES.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=WS_COLS); w.writeheader(); w.writerows(merged)
    if merged:
        new_file = not WORKSHEET.exists()
        with WORKSHEET.open("a", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=WS_COLS)
            if new_file:
                w.writeheader()
            w.writerows(merged)
    print(f"appended {len(merged)} rows to {WORKSHEET.name} (diraya-site-scrape harvests them next).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
