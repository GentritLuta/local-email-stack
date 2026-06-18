"""lead_scrape.py — autonomous lead acquisition for a niche.

Reads `niches/<slug>.yaml`, iterates each seed team-page URL, extracts every
mailto: link with its surrounding context (name, role, phone, page section),
verifies each email through lead_verify, and upserts to Supabase prospects.

Seed progress persists across runs in `niches/<slug>.seeds.done` (one URL per
walked seed): each run skips already-done seeds, resumes at the first pending
one, and clears the file to wrap around once every seed has been walked. The
time budget (--max-seconds) therefore covers NEW ground every run instead of
re-walking the same head of the list.

This is the thing that runs without a human in the chat. Schedule it:

    schtasks /Create /TN "LES-lead-scrape-real_estate_us" ^
      /TR "py C:\\Users\\bernh\\local-email-stack\\sequences\\lead_scrape.py run real_estate_us" ^
      /SC DAILY /ST 08:30

CLI:
    py lead_scrape.py run <niche_slug>           # scrape + verify + write
    py lead_scrape.py run <niche_slug> --dry     # scrape + verify, don't write
    py lead_scrape.py list                       # list available niches
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
import yaml
from bs4 import BeautifulSoup, Tag

# Local module — colocated.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lead_verify import verify, VerificationResult, JUNK_LOCAL_PARTS  # noqa: E402
from name_derive import derive_first_name, derive_company, is_free_or_isp_domain  # noqa: E402
from email_clean import clean_email  # noqa: E402

REPO_ROOT  = Path(__file__).resolve().parent.parent
NICHES_DIR = REPO_ROOT / "niches"
ENV_FILE   = REPO_ROOT / "sequences" / "supabase.env"

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/121.0 Safari/537.36 LocalEmailStack/0.4")

PHONE_RX = re.compile(r"(?<!\d)(\+?1[\s\-\.]?)?\(?\d{3}\)?[\s\-\.]?\d{3}[\s\-\.]?\d{4}(?!\d)")
EMAIL_TEXT_RX = re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+\b")

# Modern SSR pages (Next.js, Nuxt, Astro) embed team data as JSON in <script>
# tags rather than rendering full DOM cards. Pattern is consistent across
# frameworks: `"email":"x@y.com","name":"Person Name"` (sometimes with the
# fields swapped). These regexes catch both orderings.
JSON_EMAIL_THEN_NAME_RX = re.compile(
    r'"email"\s*:\s*"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"\s*,?\s*'
    r'[^{}"]{0,200}?'
    r'"(?:name|full_?name|display_?name)"\s*:\s*"([^"\\]{2,80})"',
    re.I | re.DOTALL,
)
JSON_NAME_THEN_EMAIL_RX = re.compile(
    r'"(?:name|full_?name|display_?name)"\s*:\s*"([^"\\]{2,80})"\s*,?\s*'
    r'[^{}"]{0,200}?'
    r'"email"\s*:\s*"([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})"',
    re.I | re.DOTALL,
)
# Optional bio/title field often follows the name. We capture it when present.
JSON_BIO_RX = re.compile(
    r'"email"\s*:\s*"{email}"[^{{}}]*?"(?:bio|title|role|position)"\s*:\s*"([^"\\]{{2,200}})"',
    re.I | re.DOTALL,
)
_HUMAN_NAME_RX = re.compile(r"^[A-Z][A-Za-z'`\-\.]+(?:\s+[A-Z][A-Za-z'`\-\.]+){0,3}$")


@dataclass
class ScrapedLead:
    email: str
    first_name: Optional[str] = None
    last_name:  Optional[str] = None
    title:      Optional[str] = None
    phone:      Optional[str] = None
    company:    Optional[str] = None
    city:       Optional[str] = None
    state:      Optional[str] = None
    website:    Optional[str] = None
    source_url: Optional[str] = None
    context:    dict = field(default_factory=dict)


# ─── Supabase helpers ──────────────────────────────────────────────────────

def load_supabase() -> tuple[str, str]:
    env: dict[str, str] = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    url, key = env.get("SUPABASE_URL", ""), env.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        sys.exit(f"missing SUPABASE_URL / SUPABASE_ANON_KEY in {ENV_FILE}")
    return url.rstrip("/"), key


def supa_upsert_prospect(url: str, key: str, profile_slug: str, lead: ScrapedLead,
                         verification: VerificationResult, niche_slug: str) -> dict:
    """Upsert into prospects by (profile_slug, email). Returns the row."""
    body = {
        "profile_slug":        profile_slug,
        "email":               lead.email,
        "first_name":          lead.first_name,
        "last_name":           lead.last_name,
        "company":             lead.company,
        "source":              lead.source_url,
        "niche_slug":          niche_slug,
        "title":               lead.title,
        "phone":               lead.phone,
        "city":                lead.city,
        "state":               lead.state,
        "website":             lead.website,
        "source_url":          lead.source_url,
        "verified":            verification.verified,
        "verified_at":         dt.datetime.utcnow().isoformat() + "Z",
        "verification_method": verification.method,
        "verification_error":  verification.error,
        "mx_hosts":            verification.mx_hosts or None,
        "enriched_context":    {**lead.context,
                                "catchall":   verification.catchall,
                                "is_generic": verification.is_generic},
    }
    body = {k: v for k, v in body.items() if v is not None}
    with httpx.Client(timeout=15) as c:
        r = c.post(
            f"{url}/rest/v1/prospects?on_conflict=profile_slug,email",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "Prefer": "return=representation,resolution=merge-duplicates"},
            json=body,
        )
        if r.status_code not in (200, 201):
            raise RuntimeError(f"supabase upsert {r.status_code}: {r.text[:200]}")
        rows = r.json()
        return rows[0] if rows else body


# ─── Page fetching + extraction ────────────────────────────────────────────

def fetch_html(url: str, timeout: int = 10) -> Optional[str]:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT,
                                   "Accept": "text/html,application/xhtml+xml"}) as c:
            r = c.get(url)
            if r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""):
                return r.text
    except Exception as e:
        print(f"  ! fetch failed {url}: {e}")
    return None


# Module-level singleton so callers in tight loops (e.g. crypto_projects_scrape
# iterating 5k+ project sites) don't pay ~3s Chromium launch per call.
# Call start_playwright_pool() once, fetch_html_playwright() many times,
# stop_playwright_pool() at the end.
_PW_STATE: dict = {"started": False, "p": None, "browser": None}

def start_playwright_pool() -> None:
    if _PW_STATE["started"]:
        return
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return
    p = sync_playwright().start()
    browser = p.chromium.launch(headless=True, args=[
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
    ])
    _PW_STATE.update({"started": True, "p": p, "browser": browser})


def stop_playwright_pool() -> None:
    if not _PW_STATE["started"]:
        return
    try: _PW_STATE["browser"].close()
    except Exception: pass
    try: _PW_STATE["p"].stop()
    except Exception: pass
    _PW_STATE.update({"started": False, "p": None, "browser": None})


def fetch_html_playwright(url: str, timeout: int = 15) -> Optional[str]:
    """Render `url` in a real Chromium (Playwright). Returns the post-JS DOM.

    Use for SPA sites (The Block, Bankless, Messari, etc.) where httpx
    returns an empty shell because the page mounts client-side. Soft bot
    protections (basic Cloudflare, Akamai bot manager, simple JS challenges)
    are bypassed because we ARE a real browser. We don't try to defeat
    CAPTCHA / Turnstile — those just get skipped (None return).

    A fresh browser context is launched per call so cookies/fingerprints
    don't carry across seeds. Each call costs ~3-5s; acceptable for a
    once-daily scrape cadence.
    """
    # Reuse the pooled browser if it's been started; otherwise launch + tear
    # down per call (the slow path, kept for backward compatibility).
    owns_pool = not _PW_STATE["started"]
    if owns_pool:
        start_playwright_pool()
    browser = _PW_STATE["browser"]
    if browser is None:
        return None
    ctx = None
    try:
        ctx = browser.new_context(
            user_agent=USER_AGENT.replace("LocalEmailStack/0.4", "").strip(),
            viewport={"width": 1366, "height": 900},
            locale="en-US",
        )
        page = ctx.new_page()
        page.route("**/*.{png,jpg,jpeg,gif,svg,webp,woff,woff2,mp4,webm}",
                   lambda r: r.abort())
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout * 1000)
        except Exception:
            try:
                page.goto(url, wait_until="commit", timeout=timeout * 1000)
            except Exception as e:
                print(f"  ! playwright fetch failed {url}: {e}")
                return None
        try:
            page.wait_for_timeout(800)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
            page.wait_for_timeout(400)
        except Exception:
            pass
        html = page.content()
        if _looks_like_challenge(html):
            print(f"  ! challenge page detected at {url} — skipping")
            return None
        return html
    except Exception as e:
        print(f"  ! playwright fetch failed {url}: {e}")
        return None
    finally:
        if ctx is not None:
            try: ctx.close()
            except Exception: pass
        if owns_pool:
            stop_playwright_pool()


def _looks_like_challenge(html: str) -> bool:
    """Detect Cloudflare/CAPTCHA challenge pages. Heuristic: very short body
    that prominently advertises a verification check. We deliberately don't
    blocklist 'cf-challenge' alone because it shows up as a tiny embedded
    script tag on many legitimate Cloudflare-hosted pages."""
    if not html:
        return True
    if len(html) < 800:
        # Tiny page that mentions verification → almost always a challenge
        low = html.lower()
        if any(p in low for p in ("just a moment", "checking your browser",
                                  "cf-challenge", "cf-turnstile",
                                  "g-recaptcha")):
            return True
    # Heuristic for slightly larger challenge shells: page is dominated by
    # the challenge keyword and has no real text.
    if "<title>just a moment" in html.lower()[:2000]:
        return True
    return False


_NAME_RX = re.compile(r"^([A-Z][a-z'`\-]+)(?:\s+[A-Z]\.?)?\s+([A-Z][a-zA-Z'`\-]+)$")
_CARD_CLASS_RX = re.compile(r"(team|agent|member|card|profile|staff|bio|person|broker|realtor)", re.I)


def _find_card_ancestor(node: Tag, max_walk: int = 8) -> Optional[Tag]:
    """Walk up until we hit a 'card-like' container (an element whose class
    name plausibly identifies an agent block), or the article/section root."""
    cur: Optional[Tag] = node
    for _ in range(max_walk):
        if cur is None or not hasattr(cur, "get"): return None
        classes = " ".join(cur.get("class", []))
        if classes and _CARD_CLASS_RX.search(classes):
            return cur
        if cur.name in ("article", "li"):  # li is the common "one agent" container
            return cur
        cur = cur.parent  # type: ignore[assignment]
    return None


def _name_in_subtree(card: Tag) -> Optional[str]:
    """Inside a card, find the first heading/strong/anchor whose text reads
    like a 'First Last' person name."""
    for el in card.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "strong", "b"], limit=10):
        text = el.get_text(" ", strip=True)
        if 4 <= len(text) <= 60 and _NAME_RX.match(text):
            return text
    # Try anchors next (some sites wrap names in <a>)
    for el in card.find_all("a", limit=10):
        text = el.get_text(" ", strip=True)
        if 4 <= len(text) <= 60 and _NAME_RX.match(text):
            return text
    return None


def _nearest_name(node: Tag) -> Optional[str]:
    """Find the agent name by locating the surrounding 'card' and pulling its
    heading. Works for both mailto: anchors and plain-text email mentions."""
    card = _find_card_ancestor(node)
    if card is None: return None
    return _name_in_subtree(card)


def _nearest_phone(anchor: Tag) -> Optional[str]:
    parent = anchor.find_parent(["div", "li", "section", "article", "td"]) or anchor.parent
    if not parent: return None
    tel = parent.find("a", href=re.compile(r"^tel:"))
    if tel:
        return tel["href"].split(":", 1)[1].strip()
    m = PHONE_RX.search(parent.get_text(" ", strip=True))
    return m.group(0).strip() if m else None


def _nearest_title(anchor: Tag) -> Optional[str]:
    parent = anchor.find_parent(["div", "li", "section", "article", "td"]) or anchor.parent
    if not parent: return None
    # Look at p/em/span/small inside the parent for short role-like text
    for el in parent.find_all(["p", "em", "span", "small", "i"], limit=8):
        t = el.get_text(" ", strip=True)
        if 3 <= len(t) <= 60 and re.search(r"(broker|agent|realtor|owner|founder|director|manager|"
                                           r"associate|specialist|advisor|principal|president|"
                                           r"co-owner|partner|consultant|sales)", t, re.I):
            return t
    return None


def _split_name(name: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    if not name: return None, None
    parts = name.strip().split()
    if len(parts) == 1: return parts[0], None
    return parts[0], " ".join(parts[1:])


def _build_lead(node: Tag, email: str, url: str) -> ScrapedLead:
    """Build a ScrapedLead by mining the surrounding 'card' for context."""
    name = _nearest_name(node)
    first, last = _split_name(name)
    card = _find_card_ancestor(node) or node.parent
    title = _nearest_title(node) if card else None
    phone = _nearest_phone(node) if card else None
    return ScrapedLead(
        email=email, first_name=first, last_name=last,
        title=title, phone=phone, source_url=url,
    )


def _merge(into: ScrapedLead, other: ScrapedLead) -> ScrapedLead:
    """Fill in `into`'s missing fields from `other` without overwriting."""
    for f in ("first_name", "last_name", "title", "phone", "company",
              "city", "state", "website", "source_url"):
        if not getattr(into, f) and getattr(other, f):
            setattr(into, f, getattr(other, f))
    return into


def _absorb_json_pair(by_email: dict, url: str, email: str, name: str, html: str) -> None:
    """Insert/merge a JSON-blob-derived lead with proper name + optional bio."""
    email = clean_email(email)
    name  = name.strip()
    if not email or not _HUMAN_NAME_RX.match(name): return
    first, last = _split_name(name)
    # Look for a bio/title field tied to this exact email in the same JSON blob
    title = None
    bio_rx = re.compile(JSON_BIO_RX.pattern.format(email=re.escape(email)), JSON_BIO_RX.flags)
    bm = bio_rx.search(html)
    if bm:
        bio = bm.group(1).strip()
        # First short sentence-like fragment is usually the title/role
        title = re.split(r"[.\n]", bio, 1)[0][:120]
    lead = ScrapedLead(email=email, first_name=first, last_name=last,
                       title=title, source_url=url)
    existing = by_email.get(email)
    if existing is None:
        by_email[email] = lead
    else:
        _merge(existing, lead)


def extract_leads_from_page(url: str, html: str) -> list[ScrapedLead]:
    """Three-pass extraction. Each pass adds rows or merges fields into the
    same email key, so the best-known name/title always wins.

      1. JSON blobs in <script> tags — what modern SSR sites (Next.js,
         Nuxt, Astro) ship as the team-page data. Highest signal because
         the JSON pairs email + name + bio directly.
      2. mailto: links — classic team-page pattern (WhiteStag).
      3. Plain-text email occurrences in rendered HTML — fallback for sites
         that print emails in copy without a mailto link.
    """
    # Compliance gate: if the page declares it does not accept unsolicited
    # marketing / outreach email (EN notices or the German Impressum anti-Werbung
    # clause), harvest NOTHING from it. Never cold-email a site that said no.
    try:
        from compliance import forbids_outreach
        _forbid, _label = forbids_outreach(html)
        if _forbid:
            print(f"   skip (no-solicitation [{_label}]): {url}")
            return []
    except Exception:
        pass

    soup = BeautifulSoup(html, "lxml")
    by_email: dict[str, ScrapedLead] = {}

    # 1. JSON-blob extraction (runs on raw HTML, BEFORE DOM parsing so we
    # capture script-tag content the parser keeps but doesn't expose well).
    for m in JSON_EMAIL_THEN_NAME_RX.finditer(html):
        _absorb_json_pair(by_email, url, m.group(1), m.group(2), html)
    for m in JSON_NAME_THEN_EMAIL_RX.finditer(html):
        _absorb_json_pair(by_email, url, m.group(2), m.group(1), html)

    def absorb_dom(node: Tag, email: str) -> None:
        email = clean_email(email)  # decode escapes/entities, drop labels + obfuscated/invalid
        if not email: return
        candidate = _build_lead(node, email, url)
        existing = by_email.get(email)
        if existing is None:
            by_email[email] = candidate
        else:
            _merge(existing, candidate)

    # 2. mailto: links
    for a in soup.find_all("a", href=re.compile(r"^mailto:", re.I)):
        absorb_dom(a, a["href"].split(":", 1)[1].split("?")[0].strip().lower())

    # 3. Plain-text email occurrences in rendered text
    for el in soup.find_all(string=EMAIL_TEXT_RX):
        for m in EMAIL_TEXT_RX.finditer(str(el)):
            parent_tag = el.parent if isinstance(el.parent, Tag) else None
            if parent_tag is None: continue
            absorb_dom(parent_tag, m.group(0).strip().lower())

    return list(by_email.values())


# ─── Niche loading + run ───────────────────────────────────────────────────

def load_niche(slug: str) -> dict:
    path = NICHES_DIR / f"{slug}.yaml"
    if not path.exists():
        sys.exit(f"no niche at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if data.get("slug") != slug:
        sys.exit(f"slug mismatch: file says {data.get('slug')!r}, expected {slug!r}")
    return data


def _seeds_done_path(slug: str) -> Path:
    return NICHES_DIR / f"{slug}.seeds.done"


def _load_seeds_done(slug: str) -> set[str]:
    path = _seeds_done_path(slug)
    if not path.exists():
        return set()
    return {ln.strip() for ln in path.read_text(encoding="utf-8").splitlines()
            if ln.strip()}


def _mark_seed_done(slug: str, seed_url: str) -> None:
    with _seeds_done_path(slug).open("a", encoding="utf-8") as f:
        f.write(seed_url + "\n")


def list_niches() -> None:
    if not NICHES_DIR.exists():
        print("(no niches/ directory)")
        return
    for p in sorted(NICHES_DIR.glob("*.yaml")):
        try:
            d = yaml.safe_load(p.read_text(encoding="utf-8"))
            print(f"  {d.get('slug','?'):30}  {d.get('name','')}")
        except Exception as e:
            print(f"  {p.name:30}  (broken: {e})")


def run(niche_slug: str, *, dry: bool = False, smtp: bool = True,
        force_engine: Optional[str] = None, max_seconds: int = 500) -> int:
    # Internal time budget. The orchestrator kills this subprocess at 600s
    # (SUBPROCESS_TIMEOUT) with rc=-1, losing the clean exit. We stop the seed
    # loop at `max_seconds` (default 500, 100s under the kill) and return 0 —
    # leads found so far are already upserted incrementally, so a partial pass
    # is real progress, not a failure. The seed cursor below makes the next
    # pass resume at the first seed this pass didn't reach.
    import time as _time
    deadline = _time.monotonic() + max_seconds
    niche = load_niche(niche_slug)
    profile_slug = niche.get("profile_slug") or "aureon"
    # Seeds may be plain strings or dicts. Dict form supports per-seed:
    #   - engine    : overrides niche-level engine
    #   - company   : applied as fallback to every ScrapedLead from this seed
    #   - city      : applied as fallback to every ScrapedLead from this seed
    #   - state     : applied as fallback to every ScrapedLead from this seed
    # The fallbacks fill in only what the page extractor didn't already capture.
    # Required for downstream merge-tag personalization in cold-outreach
    # variants (sequence-runner skips a prospect if {company}/{city} is null).
    raw_seeds = niche.get("seeds") or []
    niche_engine = (force_engine or niche.get("engine") or "team_pages").lower()
    seeds: list[tuple[str, str, dict]] = []
    for s in raw_seeds:
        if isinstance(s, str):
            seeds.append((s, niche_engine, {}))
        elif isinstance(s, dict) and s.get("url"):
            meta = {k: v for k, v in s.items()
                    if k in ("company", "city", "state") and v}
            seeds.append((s["url"], (s.get("engine") or niche_engine).lower(), meta))
    if not seeds:
        sys.exit(f"niche {niche_slug} has no seeds")
    # ── SEED CURSOR ──────────────────────────────────────────────────────
    # The time budget means one pass rarely covers every seed; without a
    # cursor each scheduled run re-walks the same head of the list and the
    # tail is never reached. niches/<slug>.seeds.done holds one URL per
    # fully-walked seed: this run skips those and walks the remaining seeds
    # in original file order (deterministic resume). Once every current seed
    # is done the cycle is complete — clear the file and wrap to the top.
    # Keyed on URL, not index, so seed_discover appending new seeds mid-cycle
    # just queues them; a seed interrupted mid-walk by the budget is NOT
    # marked done and is re-walked next run (upserts are idempotent).
    # Dry runs read the cursor but never write it.
    done = _load_seeds_done(niche_slug)
    pending = [t for t in seeds if t[0] not in done]
    if not pending:
        print(f"  seed cursor: all {len(seeds)} seeds walked — cycle complete, "
              f"wrapping to start")
        done = set()
        if not dry:
            _seeds_done_path(niche_slug).unlink(missing_ok=True)
        pending = list(seeds)

    def seed_done(url: str) -> None:
        if not dry:
            _mark_seed_done(niche_slug, url)

    exclude_locals = set(niche.get("filter", {}).get("exclude_local_parts", [])) | JUNK_LOCAL_PARTS
    exclude_domains = set(niche.get("filter", {}).get("exclude_domains", []))
    # Seed-level ICP gate: a seed page must carry at least one of these keywords
    # or the WHOLE seed is skipped before any lead is extracted. Catches non-ICP
    # contamination that fuzzy-matched its way into the seed list (e.g. a "Real
    # Madrid" fan site matching "real"). Niche-driven via `seed_require_keywords`,
    # so niches without the field (crypto, trades) are unaffected.
    seed_require_kw = [k.lower() for k in (niche.get("seed_require_keywords") or [])]
    # Niches whose copy greets by {greeting} (name-optional, company fallback)
    # set require_first_name: false so the quality gate admits leads that have a
    # company but no parseable personal name (e.g. crypto brand-handle emails).
    require_name = bool(niche.get("require_first_name", True))

    print(f"=== lead-scrape: {niche_slug} ({len(seeds)} seeds) ===")
    print(f"  profile_slug = {profile_slug}")
    print(f"  default eng  = {niche_engine}")
    print(f"  smtp probe   = {smtp}")
    print(f"  dry          = {dry}")
    print(f"  seed cursor  = {len(seeds) - len(pending)}/{len(seeds)} done this "
          f"cycle, {len(pending)} pending"
          + ("  (dry: progress not persisted)" if dry else "") + "\n")

    if not dry:
        url, key = load_supabase()

    summary = {"seeds_fetched": 0, "candidates": 0, "verified": 0,
               "rejected": 0, "skipped_generic": 0, "skipped_domain": 0,
               "skipped_low_quality": 0, "upserted": 0}

    for seed_i, (seed, eng, seed_meta) in enumerate(pending):
        if _time.monotonic() > deadline:
            print(f"  TIME BUDGET {max_seconds}s reached after {seed_i}/{len(pending)} "
                  f"pending seeds — stopping cleanly (leads found are already "
                  f"saved; next run resumes at the first unwalked seed).")
            break
        print(f"-- seed [{eng}]: {seed}"
              + (f"  (defaults: {seed_meta})" if seed_meta else ""))
        if eng == "playwright":
            html = fetch_html_playwright(seed)
        else:
            html = fetch_html(seed)
            # If team_pages came back near-empty (SPA shell), auto-upgrade
            # to playwright as a single retry — common on SSR-but-hydrated
            # sites where the static HTML has no team data.
            if html is not None and len(html) > 0 and not re.search(
                r"@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", html
            ):
                print(f"   (no email markers in static HTML, retrying via playwright)")
                html = fetch_html_playwright(seed) or html
        if not html:
            # Fetch failed but the seed had its attempt — mark it done so a
            # dead site can't eat budget at the head of every run; it gets
            # retried next cycle after the wrap.
            seed_done(seed)
            continue
        # ── SEED-LEVEL ICP GATE ──────────────────────────────────────────
        if seed_require_kw and not any(k in html.lower() for k in seed_require_kw):
            print(f"   [SKIP SEED] no real-estate signal on page — non-ICP, skipping")
            summary["skipped_seed_non_icp"] = summary.get("skipped_seed_non_icp", 0) + 1
            seed_done(seed)
            continue
        summary["seeds_fetched"] += 1
        leads = extract_leads_from_page(seed, html)
        print(f"   extracted {len(leads)} candidate emails")
        summary["candidates"] += len(leads)

        budget_hit_mid_seed = False
        for lead in leads:
            # Mid-seed budget check: a single page can yield many leads, each
            # costing a DNS/MX verify. Bail here too so a lead-heavy seed can't
            # overshoot the budget by minutes (the outer check is per-seed only).
            if _time.monotonic() > deadline:
                print(f"   TIME BUDGET reached mid-seed — saved {summary['upserted']} "
                      f"so far, stopping (this seed stays pending and is "
                      f"re-walked next run).")
                budget_hit_mid_seed = True
                break
            local, _, domain = lead.email.partition("@")
            if local in exclude_locals:
                summary["skipped_generic"] += 1; continue
            if domain in exclude_domains:
                summary["skipped_domain"] += 1; continue
            # Structural false-match guard: JS bundles embed Sentry DSNs and
            # package version strings that the email regex mis-reads as addresses
            # (e.g. rspack@1.6.8, intl-segmenter@11.7.10, <hex>@sentry.wixpress.com).
            # Reject them so the pool stays clean for every client. 2026-06-14.
            _tld = domain.rsplit(".", 1)[-1] if "." in domain else ""
            if (re.fullmatch(r"\d+(\.\d+)+", domain)
                    or "sentry.wixpress" in domain or "ingest.sentry" in domain
                    or domain.endswith("sentry.io")
                    or re.fullmatch(r"[0-9a-f]{32}", local or "")
                    or not re.fullmatch(r"[a-z]{2,24}", _tld)):   # real TLDs are alphabetic
                summary["skipped_domain"] += 1; continue

            # Inherit seed-level metadata (company / city / state) as fallback.
            # Only fills when the page extractor didn't capture the field —
            # per-page data always wins over per-seed defaults.
            for field, value in seed_meta.items():
                if not getattr(lead, field, None):
                    setattr(lead, field, value)

            # Domain heuristic: company website = email's domain root (e.g. whitestagrealty.com).
            # Skip free-mail / ISP / parked domains — a personal inbox is not the
            # firm's site (audit caught comcast.net / triad.rr.com / godaddy.com
            # becoming fake websites + companies on otherwise-real agents).
            if not lead.website and not is_free_or_isp_domain(domain):
                lead.website = f"https://{domain}"

            # ── QUALITY GATE ──────────────────────────────────────────────
            # Derive first_name + company from the email when the page
            # extractor didn't capture them, then HARD-REJECT any lead still
            # missing either. Person-based outreach needs a real {first_name}
            # and {company}; a lead lacking either can never enroll, so
            # admitting it only pads the pool with un-sendable junk and starves
            # the 3x buffer. Rejecting here (before the MX verify) keeps the
            # verified pool ~100% enrollable and saves the DNS lookup.
            if not lead.first_name:
                lead.first_name = derive_first_name(lead.email, lead.company)
            if not lead.company:
                lead.company = derive_company(lead.email)
            if (require_name and not lead.first_name) or not lead.company:
                summary["skipped_low_quality"] += 1
                print(f"     [SKIP] low-quality (no "
                      f"{'name' if require_name and not lead.first_name else 'company'}): {lead.email}")
                continue

            v = verify(lead.email, do_smtp_probe=smtp, do_catchall_probe=smtp)
            status = "OK " if v.verified else "BAD"
            print(f"     [{status}] {v.method:16} {lead.email:50}"
                  f"  {(lead.first_name or '?'):20} {(lead.title or ''):.30}")

            if v.verified: summary["verified"] += 1
            else:           summary["rejected"] += 1

            if dry: continue
            try:
                supa_upsert_prospect(url, key, profile_slug, lead, v, niche_slug)
                summary["upserted"] += 1
            except Exception as e:
                print(f"     ! upsert failed: {e}")

        if budget_hit_mid_seed:
            break  # seed NOT marked done — next run resumes at this seed
        seed_done(seed)

    print(f"\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k:18} {v}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_run = sub.add_parser("run")
    p_run.add_argument("niche_slug")
    p_run.add_argument("--dry", action="store_true")
    p_run.add_argument("--no-smtp", action="store_true",
                       help="skip SMTP probe (MX-only verification, ~10x faster)")
    p_run.add_argument("--engine", choices=["team_pages", "playwright"],
                       help="force fetch engine for all seeds")
    p_run.add_argument("--max-seconds", type=int, default=500,
                       help="internal time budget; stop the seed loop cleanly "
                            "before the orchestrator's 600s kill (default 500)")
    args = ap.parse_args()

    if args.cmd == "list":
        list_niches(); return 0
    if args.cmd == "run":
        return run(args.niche_slug, dry=args.dry, smtp=not args.no_smtp,
                   force_engine=args.engine, max_seconds=args.max_seconds)
    return 0


if __name__ == "__main__":
    sys.exit(main())
