# -*- coding: utf-8 -*-
"""research-dispatcher.py — autonomous builder for UNCOVERED referral metros.

The fulfiller queues any metro it can't serve into referral-lists/.research_queue.json
with a ready, anti-fabrication research brief. This dispatcher drains that queue:

  1. For each pending metro, ask Claude (with web search) to research the brief and
     return a strict JSON list of verified firms.
  2. Derive the metro's match block (area codes / zip prefixes / cities / state) from
     the returned firms + the queue signal.
  3. Build the curated list (build-curated-list.py) and run the STRICT QC gate
     (verify-curated-lists.py). The gate independently re-verifies every firm, so a
     hallucinated firm can never reach an agent — it just fails QC and is flagged.
  4. Mark the queue entry built / failed_qc / needs_attention. The fulfiller (runs
     every minute) then auto-serves every agent who was waiting on that metro.

LLM access: needs an Anthropic API key (env ANTHROPIC_API_KEY or sequences/anthropic.env).
This machine runs the Claude *desktop app*, which has no headless CLI, so the key is the
activation switch. WITHOUT a key the dispatcher stays idle and simply preserves the queue
(it never fabricates) — covered metros keep being served instantly by the fulfiller, and
queued metros are built the moment a key is present (or by hand in a session).

  py scripts/research-dispatcher.py                  # drain queue (needs API key)
  py scripts/research-dispatcher.py --dry            # show pending, don't call LLM/build
  py scripts/research-dispatcher.py --mock firms.json --key testmetro   # test plumbing
"""
from __future__ import annotations
import argparse, json, os, re, subprocess, sys, urllib.request
from pathlib import Path
from urllib.parse import urlparse

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
LISTS = REPO / "referral-lists"
QUEUE = LISTS / ".research_queue.json"
CURATED = LISTS / "curated.json"
IDLE_ALERTED = LISTS / ".research_idle_alerted"     # so we alert "no key" only once
MIN_FIRMS = 16                                       # the curated standard (estate+divorce)
MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ----- config -----
def anthropic_key() -> str:
    k = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if k:
        return k
    f = REPO / "sequences" / "anthropic.env"
    if f.exists():
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.strip().startswith("ANTHROPIC_API_KEY") and "=" in ln:
                return ln.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def aureon_resend_key() -> str:
    try:
        priv = json.loads((REPO / "profiles" / "aureon.private.json").read_text(encoding="utf-8"))
        return priv.get("relay", {}).get("resend_api_key", "")
    except Exception:
        return ""


# ----- LLM research (active only when a key is present) -----
def research_firms(prompt: str, key: str) -> dict | None:
    import anthropic
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(
        model=MODEL, max_tokens=8000,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 25}],
        messages=[{"role": "user", "content": prompt + "\n\nReturn ONLY the JSON object — no prose, no markdown fences."}],
    )
    text = "".join(getattr(b, "text", "") for b in msg.content if getattr(b, "type", None) == "text")
    return extract_json(text)


def extract_json(text: str) -> dict | None:
    if not text:
        return None
    m = re.search(r'\{[^{}]*"firms"\s*:\s*\[.*\]\s*\}', text, re.S) or re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


# ----- $0 heuristic research (web search + scrape; QC gate guarantees no bad firm) -----
# Used when there's no ANTHROPIC_API_KEY. Quality depends on a working search backend
# (Google CSE preferred — Brave/ddgs degrade to off-target results), but the strict QC
# gate independently re-verifies every firm, so a wrong candidate can never be served.
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/123 Safari/537.36"
DIRECTORY = {"avvo.com", "justia.com", "findlaw.com", "lawyers.com", "martindale.com",
             "superlawyers.com", "yelp.com", "yellowpages.com", "mapquest.com", "thumbtack.com",
             "expertise.com", "facebook.com", "linkedin.com", "indeed.com", "ziprecruiter.com",
             "bbb.org", "nolo.com", "legalzoom.com", "wikipedia.org", "birdeye.com", "angi.com",
             "trustpilot.com", "manta.com", "chamberofcommerce.com", "lawinfo.com"}
ESTATE_RX = re.compile(r"estate planning|probate|\bwills?\b|\btrust\b|elder law|guardianship", re.I)
DIVORCE_RX = re.compile(r"\bdivorce\b|family law|child custody|paternity|child support|dissolution", re.I)
PHONE_RX = re.compile(r"\(?(\d{3})\)?[-.\s]?(\d{3})[-.\s]?(\d{4})")
ADDR_RX = re.compile(r"\d{1,6}\s+[\w.\s]+?(?:St|Street|Ave|Avenue|Rd|Road|Dr|Drive|Blvd|Way|Suite|Ste|Lane|Ln|Ct|Court|Pkwy|Plaza)\b[\w.,\s#]*?\b[A-Z]{2}\s+\d{5}")
ATTY_RX = re.compile(r"(?:Attorney|Law Office[s]? of|Lawyer)\s+([A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)")


def _fetch(url: str) -> str | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return urllib.request.urlopen(req, timeout=10).read().decode("utf-8", "replace")
    except Exception:
        return None


def extract_firm(url: str, acs: set) -> dict | None:
    """Pull a firm record off its OWN site. Requires a metro-area phone + a law-practice
    signal, else returns None. lead_attorney/practice are best-effort (QC re-verifies)."""
    html = _fetch(url)
    if not html:
        return None
    text = re.sub(r"<[^>]+>", " ", html)
    phone = ""
    for m in PHONE_RX.finditer(html):
        if not acs or m.group(1) in acs:
            phone = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"; break
    if not phone:
        return None
    est, div = len(ESTATE_RX.findall(html)), len(DIVORCE_RX.findall(html))
    if est == 0 and div == 0:
        return None
    typ = "Estate / Probate" if est >= div else "Divorce / Family"
    # firm name: prefer og:site_name (the real brand) over the SEO <title>
    import html as _h
    og = re.search(r'<meta[^>]+property=["\']og:site_name["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if og:
        name = og.group(1)
    else:
        mt = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
        name = re.sub(r"\s*[|\-–—:].*$", "", mt.group(1)).strip() if mt else urlparse(url).netloc
    name = _h.unescape(re.sub(r"(?i)\s*\b(home|welcome)\b\s*$", "", name)).strip().rstrip(" |-–—:•·").strip() or urlparse(url).netloc
    me = re.search(r"mailto:([\w.+-]+@[\w.-]+\.\w{2,})", html)
    email = me.group(1) if me and "example" not in me.group(1).lower() else ""
    ma = ADDR_RX.search(re.sub(r"\s+", " ", text))
    address = _h.unescape(re.sub(r"\s+", " ", ma.group(0)).strip()) if ma else ""
    city = ""
    mc = re.search(r",\s*([A-Za-z .]+?),?\s+[A-Z]{2}\s+\d{5}", address)
    if mc:
        city = mc.group(1).strip()
    matty = ATTY_RX.search(text)
    atty = matty.group(1) if matty else ""
    # reject obvious non-names (nav/SEO words that slipped into the pattern)
    _BAD = {"spotlight", "home", "menu", "office", "law", "attorney", "practice", "areas",
            "contact", "about", "team", "our", "the", "services", "free", "call"}
    if atty and any(w.lower() in _BAD for w in atty.split()):
        atty = ""
    return {"firm": _h.unescape(name)[:80], "type": typ, "lead_attorney": atty,
            "practice": "Estate planning, wills, trusts & probate" if typ.startswith("Estate")
                        else "Divorce, child custody & family law",
            "city": city, "phone": phone, "email": email, "website": url, "address": address}


def research_firms_heuristic(entry: dict) -> dict | None:
    import seed_discover as sd                       # the stack's CSE/Brave/ddgs search
    city, state = (entry.get("city") or "").strip(), (entry.get("state") or "").strip()
    where = (f"{city} {state}").strip() or (f"area code {entry.get('area_code')}" if entry.get("area_code") else "")
    if not where:
        return None
    acs = {entry["area_code"]} if entry.get("area_code") else set()
    queries = [f"estate planning probate attorney {where}", f"wills trust elder law attorney {where}",
               f"divorce family law attorney {where}", f"child custody divorce lawyer {where}"]
    seen, firms = set(), []
    for q in queries:
        try:
            urls = sd._search(q, 12, "us")
        except Exception as e:
            print(f"    search failed ({q[:30]}...): {e}"); urls = []
        for u in urls:
            dom = urlparse(u).netloc.lower().replace("www.", "")
            if not dom or dom in DIRECTORY or dom in seen:
                continue
            seen.add(dom)
            f = extract_firm(u, acs)
            if f:
                firms.append(f)
    return {"firms": firms}


# ----- metro assembly (pure; unit-testable) -----
def _digits(p: str) -> str:
    d = re.sub(r"\D", "", p or "")
    return d[1:] if len(d) == 11 and d.startswith("1") else d


def derive_match(entry: dict, firms: list[dict]) -> dict:
    acs, zips, cities, states = set(), set(), set(), set()
    if entry.get("area_code"):
        acs.add(entry["area_code"])
    if entry.get("zip"):
        zips.add(entry["zip"][:3])
    if entry.get("state"):
        states.add(entry["state"].upper())
    for f in firms:
        d = _digits(f.get("phone", ""))
        if len(d) >= 10:
            acs.add(d[:3])
        if f.get("city"):
            cities.add(f["city"].strip().lower())
        m = re.search(r"\b([A-Z]{2})\s+(\d{5})", f.get("address", "") or "")
        if m:
            states.add(m.group(1))
            zips.add(m.group(2)[:3])
    return {"area_codes": sorted(acs), "states": sorted(states),
            "cities": sorted(cities), "zip_prefixes": sorted(zips)}


def _title(s: str) -> str:
    return " ".join(w.capitalize() for w in (s or "").split())


def build_metro_json(entry: dict, firms: list[dict]) -> tuple[Path, str]:
    primary = entry.get("city") or (firms[0].get("city") if firms else entry.get("key", "metro"))
    primary = _title(primary)
    slug = re.sub(r"[^a-z0-9]+", "-", primary.lower()).strip("-") or "metro"
    meta = {"metro": primary, "label": f"{primary} and surrounding area",
            "basename": f"Attorney-Referral-List-{primary.replace(' ', '-')}",
            "match": derive_match(entry, firms), "firms": firms}
    path = LISTS / "metros" / f"{slug}.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path, primary


def qc_passed(metro: str) -> tuple[bool, list]:
    cur = json.loads(CURATED.read_text(encoding="utf-8"))
    for e in cur.get("lists", []):
        if e.get("metro") == metro:
            q = e.get("quality") or {}
            return bool(q.get("passed")), (q.get("flagged") or [])
    return False, []


def run(script: str, *a) -> int:
    return subprocess.run([sys.executable, str(REPO / "scripts" / script), *a],
                          cwd=str(REPO)).returncode


def alert_idle(pending: list) -> None:
    if IDLE_ALERTED.exists():
        return
    rk = aureon_resend_key()
    if not rk:
        return
    metros = ", ".join(q.get("key", "?") for q in pending)
    payload = {"from": "Anna from Aureon Global <anna@outreach.aureonglobal.de>",
               "to": ["info@aureonglobal.de"],
               "subject": "[Aureon] autonomous metro research came up thin (enable Google CSE)",
               "text": ("The $0 heuristic research dispatcher ran but couldn't find enough "
                        "verified firms — almost always because no quality search backend is "
                        f"live (Google CSE returns 403 until you enable the Custom Search JSON "
                        f"API + add the key; Brave/ddgs return off-target results).\n\n"
                        f"Queued metros: {metros}\n\nFinish Google CSE in search.env to activate "
                        "hands-free $0 research, or add ANTHROPIC_API_KEY for LLM-grade research. "
                        "Covered metros keep being served instantly; nothing is lost or fabricated.")}
    req = urllib.request.Request("https://api.resend.com/emails", data=json.dumps(payload).encode(),
                                 method="POST", headers={"Authorization": "Bearer " + rk,
                                 "Content-Type": "application/json", "User-Agent": "les research-dispatcher/1.0"})
    try:
        urllib.request.urlopen(req, timeout=30)
        IDLE_ALERTED.write_text("alerted", encoding="utf-8")
    except Exception as e:
        print("  ! idle alert failed:", e)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="show pending, don't research/build")
    ap.add_argument("--limit", type=int, default=1, help="max metros to build per run (cost control)")
    ap.add_argument("--mock", help="path to a firms JSON file (skip the LLM; test plumbing)")
    ap.add_argument("--key", help="with --mock: the queue key/metro name to build")
    args = ap.parse_args()

    queue = json.loads(QUEUE.read_text(encoding="utf-8")) if QUEUE.exists() else []
    pending = [q for q in queue if q.get("status") == "pending"]

    # --mock: inject a synthetic entry to exercise build + QC without the queue/LLM
    if args.mock:
        firms = json.loads(Path(args.mock).read_text(encoding="utf-8")).get("firms", [])
        entry = {"key": args.key or "mockmetro", "city": args.key or "Mock Metro"}
        path, metro = build_metro_json(entry, firms)
        print(f"[mock] wrote {path.name} ({len(firms)} firms) -> match={json.dumps(derive_match(entry, firms))}")
        run("build-curated-list.py", str(path)); run("verify-curated-lists.py")
        ok, flags = qc_passed(metro)
        print(f"[mock] {metro}: QC passed={ok} flags={flags[:4]}")
        return 0

    if not pending:
        print("research queue: nothing pending."); return 0
    print(f"research queue: {len(pending)} pending -> {[q.get('key') for q in pending]}")
    if args.dry:
        return 0

    key = anthropic_key()
    backend = "LLM (Claude)" if key else "heuristic (web search + scrape, $0)"
    print(f"research backend: {backend}")

    built = thin = 0
    for q in pending[:args.limit]:
        print(f"  researching {q.get('key')} ({q.get('city') or q.get('state') or '?'}) ...")
        try:
            data = research_firms(q["dispatch_prompt"], key) if key else research_firms_heuristic(q)
        except Exception as e:
            print(f"  ! research failed: {e}"); q["status"] = "needs_attention"; continue
        firms = (data or {}).get("firms") or []
        if len(firms) < MIN_FIRMS:
            q["attempts"] = q.get("attempts", 0) + 1          # transient (e.g. CSE daily quota) -> retry
            retry = q["attempts"] < 3
            q["status"] = "pending" if retry else "needs_attention"
            q["found"] = len(firms); thin += 1
            print(f"  ~ only {len(firms)} firms (< {MIN_FIRMS}); "
                  f"{'will retry next run' if retry else 'needs_attention'} (attempt {q['attempts']})"
                  f"{' — check Google CSE daily quota' if not key else ''}")
            continue
        path, metro = build_metro_json(q, firms)
        run("build-curated-list.py", str(path)); run("verify-curated-lists.py")
        ok, flags = qc_passed(metro)
        q["status"] = "built" if ok else "failed_qc"
        q["metro"] = metro; q["flagged"] = flags[:6]
        built += ok
        print(f"  {'+' if ok else '~'} {metro}: QC passed={ok} ({len(firms)} firms){' flags=' + str(flags[:3]) if not ok else ''}")

    QUEUE.write_text(json.dumps(queue, indent=2), encoding="utf-8")
    if thin and not key:                              # heuristic starved -> search backend not live
        alert_idle(pending)
    elif built:
        IDLE_ALERTED.unlink(missing_ok=True)
    print(f"\nbuilt {built} metro(s); fulfiller will auto-serve waiting agents within ~1 min.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
