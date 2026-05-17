"""lead_scrape.py — autonomous lead acquisition for a niche.

Reads `niches/<slug>.yaml`, iterates each seed team-page URL, extracts every
mailto: link with its surrounding context (name, role, phone, page section),
verifies each email through lead_verify, and upserts to Supabase prospects.

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
from lead_verify import verify, VerificationResult, GENERIC_LOCAL_PARTS  # noqa: E402

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

def fetch_html(url: str, timeout: int = 25) -> Optional[str]:
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
    email = email.strip().lower()
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
    soup = BeautifulSoup(html, "lxml")
    by_email: dict[str, ScrapedLead] = {}

    # 1. JSON-blob extraction (runs on raw HTML, BEFORE DOM parsing so we
    # capture script-tag content the parser keeps but doesn't expose well).
    for m in JSON_EMAIL_THEN_NAME_RX.finditer(html):
        _absorb_json_pair(by_email, url, m.group(1), m.group(2), html)
    for m in JSON_NAME_THEN_EMAIL_RX.finditer(html):
        _absorb_json_pair(by_email, url, m.group(2), m.group(1), html)

    def absorb_dom(node: Tag, email: str) -> None:
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


def run(niche_slug: str, *, dry: bool = False, smtp: bool = True) -> int:
    niche = load_niche(niche_slug)
    profile_slug = niche.get("profile_slug") or "aureon"
    seeds: list[str] = niche.get("seeds") or []
    if not seeds:
        sys.exit(f"niche {niche_slug} has no seeds")
    exclude_locals = set(niche.get("filter", {}).get("exclude_local_parts", [])) | GENERIC_LOCAL_PARTS
    exclude_domains = set(niche.get("filter", {}).get("exclude_domains", []))

    print(f"=== lead-scrape: {niche_slug} ({len(seeds)} seeds) ===")
    print(f"  profile_slug = {profile_slug}")
    print(f"  smtp probe   = {smtp}")
    print(f"  dry          = {dry}\n")

    if not dry:
        url, key = load_supabase()

    summary = {"seeds_fetched": 0, "candidates": 0, "verified": 0,
               "rejected": 0, "skipped_generic": 0, "skipped_domain": 0,
               "upserted": 0}

    for seed in seeds:
        print(f"-- seed: {seed}")
        html = fetch_html(seed)
        if not html:
            continue
        summary["seeds_fetched"] += 1
        leads = extract_leads_from_page(seed, html)
        print(f"   extracted {len(leads)} candidate emails")
        summary["candidates"] += len(leads)

        for lead in leads:
            local, _, domain = lead.email.partition("@")
            if local in exclude_locals:
                summary["skipped_generic"] += 1; continue
            if domain in exclude_domains:
                summary["skipped_domain"] += 1; continue

            # Domain heuristic: company website = email's domain root (e.g. whitestagrealty.com).
            # Skip free-mail providers — gmail.com etc. aren't anyone's company site.
            FREE_MAIL = {"gmail.com","yahoo.com","outlook.com","hotmail.com","icloud.com",
                          "aol.com","proton.me","protonmail.com","web.de","gmx.de","gmx.com",
                          "mail.com","live.com","msn.com","yandex.com","yandex.ru","zoho.com"}
            if not lead.website and domain not in FREE_MAIL:
                lead.website = f"https://{domain}"

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
    args = ap.parse_args()

    if args.cmd == "list":
        list_niches(); return 0
    if args.cmd == "run":
        return run(args.niche_slug, dry=args.dry, smtp=not args.no_smtp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
