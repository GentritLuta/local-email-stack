# -*- coding: utf-8 -*-
"""yc-guess-verify.py — strategic lead source for Diraya (early-stage AI startups).

WHERE they are: YC's public company directory. Every company page embeds an
Inertia `data-page` JSON with the company website + founder names + tags + batch.
HOW we get a sendable email: guess founder addresses (firstname@domain, etc.) and
CATCH-ALL-AWARE SMTP-verify each — keep ONLY addresses that truly resolve
(method=smtp_verified on a non-catch-all domain). That protects the bounce rate:
a guess we can't positively confirm is dropped, never sent.

Pipeline:
  1. sitemap -> all YC company slugs
  2. fetch each page -> data-page JSON -> {name, website, founders, tags, batch, team_size}
  3. keep early-stage AI cos (AI keywords + recent batch + small team)
  4. per founder: skip catch-all/no-MX domains; else try guesses, keep first 250
  5. write a Diraya-ready CSV (email, first_name, last_name, company, title, website)

Usage:
  py scripts/yc-guess-verify.py --max-pages 500 --target-leads 60 --out out/yc_diraya_leads.csv
  py scripts/yc-guess-verify.py            # full sweep (all ~6k), default caps
Then: py scripts/import-prospects-csv.py diraya out/yc_diraya_leads.csv --niche yc_ai
"""
from __future__ import annotations
import re, json, sys, csv, uuid, argparse, threading, html as ihtml, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
import lead_verify                              # noqa
from name_derive import is_free_or_isp_domain   # noqa
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
AI_RX = re.compile(
    r"\b(a\.?i\.?|artificial intelligence|machine learning|\bml\b|\bllm\b|llms|gen ?ai|"
    r"generative|\brag\b|agent|agents|agentic|copilot|co-pilot|chatbot|\bnlp\b|"
    r"computer vision|deep learning|neural|gpt|embedding|vector (db|database|search)|"
    r"fine-?tun|inference|foundation model|prompt|voice ai|speech)\b", re.I)
# Diraya's REAL ICP (per variants.json target): seed-to-Series-B SaaS / fintech /
# health-tech SOFTWARE companies that want an AI feature shipped. Most of them do
# NOT describe themselves as "AI" on YC (they describe their product: payments, EHR,
# analytics), so AI_RX alone misses them. This widens the net to those technical
# software buyers the existing technical copy actually fits.
SAAS_RX = re.compile(
    r"\b(saas|b2b|platform|api|sdk|software|developer|dev ?tool|infrastructure|backend|"
    r"fintech|payment|payments|lending|banking|insurance|insurtech|"
    r"health ?tech|healthcare|medical|clinical|patient|ehr|telehealth|"
    r"analytics|dashboard|data (platform|pipeline|warehouse|infra)|observability|"
    r"workflow|automation|\bcrm\b|\berp\b|marketplace|compliance|cybersecurity|"
    r"logistics|proptech|legal ?tech|hr ?tech|edtech|vertical saas|devops|cloud)\b", re.I)
# The offer itself excludes these (they are competitors / non-buyers, not ICP).
EXCLUDE_RX = re.compile(
    r"\b(agency|agencies|staffing|staff aug|recruit|recruiting|outsourc|outsourcing|"
    r"consultanc|consulting firm|white ?label|body shop|dev shop|systems integrator)\b", re.I)


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8", "replace")


def sitemap_slugs() -> list[str]:
    x = get("https://www.ycombinator.com/companies/sitemap.xml")
    return re.findall(r'<loc>https://www\.ycombinator\.com/companies/([^<]+)</loc>', x)


def fetch_company(slug: str) -> dict | None:
    try:
        p = get(f"https://www.ycombinator.com/companies/{slug}")
        m = re.search(r'data-page="([^"]+)"', p)
        if not m:
            return None
        return json.loads(ihtml.unescape(m.group(1)))["props"]["company"]
    except Exception:
        return None


def batch_year(comp: dict) -> int:
    blob = f"{comp.get('batch','')} {comp.get('batch_name','')}"
    yrs = re.findall(r'20\d{2}', blob)
    if yrs:
        return max(int(y) for y in yrs)
    m = re.search(r'[WSXF](\d{2})', comp.get("batch") or "")
    if m:
        return 2000 + int(m.group(1))
    try:
        return int(comp.get("year_founded") or 0)
    except Exception:
        return 0


def is_icp(comp: dict) -> bool:
    """Diraya ICP gate: AI-native OR a seed-to-Series-B technical software company
    (SaaS/fintech/health-tech), minus agencies/staffing/outsourcing the offer excludes."""
    text = " ".join(str(comp.get(k) or "") for k in ("one_liner", "long_description"))
    text += " " + " ".join(comp.get("tags") or [])
    if EXCLUDE_RX.search(text):
        return False
    return bool(AI_RX.search(text) or SAAS_RX.search(text))


def domain_of(comp: dict) -> str:
    w = comp.get("website") or ""
    m = re.search(r'https?://([^/]+)', w)
    d = (m.group(1) if m else w).strip().lower()
    return d[4:] if d.startswith("www.") else d


def name_parts(full: str) -> tuple[str, str]:
    parts = [p for p in re.split(r'\s+', (full or "").strip()) if p]
    if not parts:
        return "", ""
    first = re.sub(r'[^a-z]', '', parts[0].lower())
    last = re.sub(r'[^a-z]', '', parts[-1].lower()) if len(parts) > 1 else ""
    return first, last


def guesses(first: str, last: str, domain: str) -> list[str]:
    out = []
    if first:
        out.append(f"{first}@{domain}")
    if first and last:
        out += [f"{first}.{last}@{domain}", f"{first[0]}{last}@{domain}",
                f"{first}{last}@{domain}", f"{first}_{last}@{domain}", f"{first}{last[0]}@{domain}"]
    return out


# ─── catch-all-aware domain gate (cached) ──────────────────────────────────
_dom_cache: dict[str, str] = {}
_dom_lock = threading.Lock()

def domain_status(domain: str) -> str:
    with _dom_lock:
        if domain in _dom_cache:
            return _dom_cache[domain]
    probe = f"zz-no-such-user-{uuid.uuid4().hex[:8]}@{domain}"
    r = lead_verify.verify(probe, do_catchall_probe=False)
    if r.method == "no_mx":
        st = "no_mx"
    elif r.method == "smtp_verified":
        st = "catchall"          # accepts a random local -> can't trust guesses
    elif r.method == "smtp_rejected":
        st = "ok"                # rejects unknown -> guesses are trustworthy
    else:
        st = "unknown"           # mx_verified/greylist/port-blocked -> skip to be safe
    with _dom_lock:
        _dom_cache[domain] = st
    return st


def verify_founder(first: str, last: str, domain: str) -> tuple[str | None, str]:
    st = domain_status(domain)
    if st != "ok":
        return None, st
    for cand in guesses(first, last, domain):
        r = lead_verify.verify(cand, do_catchall_probe=False)
        if r.method == "smtp_verified":
            return cand, "verified"
    return None, "no_guess_hit"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-pages", type=int, default=6500, help="cap YC pages fetched")
    ap.add_argument("--target-leads", type=int, default=150, help="stop verifying at N hits")
    ap.add_argument("--min-year", type=int, default=2024, help="keep batches >= this year")
    ap.add_argument("--max-team", type=int, default=300, help="skip teams larger than this")
    ap.add_argument("--workers", type=int, default=14)
    ap.add_argument("--out", default=str(REPO / "out" / "yc_diraya_leads.csv"))
    ap.add_argument("--dump-candidates", default=None, help="also write all ICP candidates (pre-verify) here")
    ap.add_argument("--no-verify", action="store_true",
                    help="skip SMTP verify (port 25); dump the full ICP list as a LinkedIn worksheet")
    args = ap.parse_args()

    print("fetching sitemap ...")
    slugs = sitemap_slugs()
    print(f"  {len(slugs)} YC companies in sitemap")
    print(f"  order sample: first={slugs[:3]}  last={slugs[-3:]}")
    slugs = slugs[:args.max_pages]

    # 1) fetch + filter to early-stage AI companies (parallel I/O)
    cands, fetched, ai_hits, recent_hits = [], 0, 0, 0
    yr_dist: dict[int, int] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch_company, s): s for s in slugs}
        for fut in as_completed(futs):
            fetched += 1
            if fetched % 250 == 0:
                print(f"  fetched {fetched}/{len(slugs)}  (AI={ai_hits} recent-AI={recent_hits} candidates={len(cands)})")
            comp = fut.result()
            if not comp:
                continue
            yr = batch_year(comp)
            yr_dist[yr] = yr_dist.get(yr, 0) + 1
            if not is_icp(comp):
                continue
            ai_hits += 1
            if yr < args.min_year:
                continue
            ts = comp.get("team_size")
            try: ts = int(ts) if ts not in (None, "") else 0
            except Exception: ts = 0
            if ts and ts > args.max_team:
                continue
            recent_hits += 1
            dom = domain_of(comp)
            if not dom or "." not in dom or is_free_or_isp_domain(dom):
                continue
            for f in (comp.get("founders") or []):
                first, last = name_parts(f.get("full_name") or f.get("name") or "")
                if not first or len(first) < 2:
                    continue
                cands.append({"first": first, "last": last, "domain": dom,
                              "full_name": (f.get("full_name") or "").strip(),
                              "title": f.get("title") or "Founder",
                              "company": comp.get("name") or "", "website": comp.get("website") or "",
                              "linkedin": f.get("linkedin_url") or "", "twitter": f.get("twitter_url") or "",
                              "city": comp.get("city") or "", "batch": comp.get("batch") or "",
                              "one_liner": comp.get("one_liner") or "",
                              "tags": ",".join(comp.get("tags") or [])[:120]})

    # dedupe candidate founders by (domain, first, last)
    seen, uniq = set(), []
    for c in cands:
        k = (c["domain"], c["first"], c["last"])
        if k in seen: continue
        seen.add(k); uniq.append(c)
    print(f"\nfetched={fetched}  AI-cos={ai_hits}  early-stage-AI-cos={recent_hits}  "
          f"founder-candidates={len(uniq)} (across {len({c['domain'] for c in uniq})} domains)")
    print("  batch-year distribution (top):",
          dict(sorted(yr_dist.items(), key=lambda kv: -kv[1])[:8]))
    if args.dump_candidates:
        with open(args.dump_candidates, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(uniq[0].keys()) if uniq else ["first"]); w.writeheader(); w.writerows(uniq)
        print("  candidates dumped ->", args.dump_candidates)

    # --no-verify: port 25 is blocked here, so emit the rich LinkedIn worksheet
    # (name+title+company+domain+LinkedIn URL) for the manual outreach motion. These
    # are NOT imported into the sending pool — guessed emails stay out until verified.
    if args.no_verify:
        outp = Path(args.out); outp.parent.mkdir(parents=True, exist_ok=True)
        cols = ["full_name", "first", "last", "title", "company", "website", "domain",
                "linkedin", "twitter", "batch", "city", "one_liner", "tags"]
        uniq.sort(key=lambda c: (-(int(re.search(r'\d{2}', c.get("batch","") or "0").group()) if re.search(r'\d{2}', c.get("batch","") or "") else 0), c["company"]))
        with open(outp, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore"); w.writeheader(); w.writerows(uniq)
        print(f"\n=== LinkedIn worksheet ===  {len(uniq)} founders across "
              f"{len({c['domain'] for c in uniq})} AI startups  ->  {outp}")
        print("  (manual outreach list; NOT imported to the send pool — guessed emails need a verifier first)")
        return 0

    # 2) guess + catch-all-aware SMTP-verify (parallel), stop at target
    print(f"\nverifying (target {args.target_leads}) ...")
    leads, done, reasons = [], 0, {}
    stop = threading.Event()
    def work(c):
        if stop.is_set(): return None
        email, why = verify_founder(c["first"], c["last"], c["domain"])
        return (c, email, why)
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = [ex.submit(work, c) for c in uniq]
        for fut in as_completed(futs):
            done += 1
            res = fut.result()
            if not res: continue
            c, email, why = res
            reasons[why] = reasons.get(why, 0) + 1
            if email:
                leads.append({**c, "email": email})
                print(f"  ✓ {email:<34} {c['full_name'][:20]:<20} {c['company'][:22]:<22} ({c['title'][:18]})")
                if len(leads) >= args.target_leads:
                    stop.set()
            if done % 200 == 0:
                print(f"    ... checked {done}/{len(uniq)} domains  verified={len(leads)}")

    # 3) write Diraya-ready CSV
    outp = Path(args.out); outp.parent.mkdir(parents=True, exist_ok=True)
    cols = ["email", "first_name", "last_name", "company", "title", "website", "city"]
    with open(outp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols); w.writeheader()
        for L in leads:
            w.writerow({"email": L["email"], "first_name": L["full_name"].split()[0] if L["full_name"] else L["first"].title(),
                        "last_name": L["last"].title(), "company": L["company"], "title": L["title"],
                        "website": L["website"], "city": L["city"]})
    print(f"\n=== done ===  verified leads: {len(leads)}  ->  {outp}")
    print("  verify outcomes:", reasons)
    print(f"  next: py scripts/import-prospects-csv.py diraya \"{outp}\" --niche yc_ai")
    return 0


if __name__ == "__main__":
    sys.exit(main())
