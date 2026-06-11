"""tradingview_scrape.py — discover crypto-aligned indicator authors on
TradingView and extract their contact emails by scraping the external
website they linked from their profile.

Why this is high-yield for AlgoAlpha specifically:
  - AlgoAlpha sells TradingView indicators.
  - Other TradingView indicator authors have the exact same audience.
  - Many have public profiles that link out to their own commercial site
    (their indicator's marketing page) where their contact email lives.
  - TradingView appends `?utm_source=tradingview` to every user-supplied
    external URL on profile pages — that gives us a clean way to detect
    "this is the author's own website, not a TradingView staff link."

Pipeline:
  1. discover  -> paginate /scripts/page-N/ for handles, append to queue file
  2. run       -> for each handle: fetch /u/<handle>/, find utm_source URL,
                  scrape that website for emails, upsert verified ones

CLI:
  py tradingview_scrape.py discover --out niches/tv_handles.txt --pages 200
  py tradingview_scrape.py run crypto_influencer niches/tv_handles.txt --limit 500

The run step is idempotent (Supabase upsert dedup by profile_slug,email)
and stateful (it appends processed handles to <queue>.done so future runs
skip them).
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from pathlib import Path
from typing import Optional

# Profile titles + bios can contain emoji / non-Latin script. Same UTF-8
# reconfigure as youtube_scraper.py to survive on Windows cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from urllib.parse import urljoin, urlparse, unquote

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lead_verify import verify, JUNK_LOCAL_PARTS  # noqa: E402
from lead_scrape import (  # noqa: E402
    ScrapedLead, load_supabase, supa_upsert_prospect, load_niche,
    fetch_html, fetch_html_playwright, extract_leads_from_page,
    start_playwright_pool, stop_playwright_pool,
)
from crypto_projects_scrape import _is_junk_email, _try_pages  # noqa: E402
from name_derive import derive_first_name, derive_company  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

TV_BASE = "https://www.tradingview.com"
HANDLE_RX = re.compile(r"/u/([A-Za-z0-9_\-]+)/?")

# Two ways the user's external URL can show up on a TV profile page:
#   1. An <a href> that TV has tagged with ?utm_source=tradingview
#   2. Plain text in the bio (e.g. "🌐 www.LuxAlgo.com 📈")
# We try (1) first because it's cleanest, then fall back to plain-text domain
# mentions inside the bio <span>.
UTM_URL_RX = re.compile(
    r"https?://[A-Za-z0-9.\-/_:?&%=+~#]+?[?&]utm_source=tradingview[A-Za-z0-9.\-/_:?&%=+~#]*",
    re.I)
# Domain mention in bio text. We require a real public TLD as the last
# label, otherwise we'd match JS identifiers like `window.initdata`.
VALID_TLDS = (
    "com","net","org","io","co","ai","app","dev","xyz","me","tv","tech",
    "info","biz","online","site","website","store","shop","club","blog",
    "uk","de","fr","es","it","nl","pl","ru","jp","kr","cn","au","ca","us",
    "ch","at","be","se","no","fi","dk","cz","ee","lv","lt","gr","pt",
    "in","sg","hk","tw","my","th","ph","id","vn","tr","ae","sa","ng",
    "za","mx","br","ar","cl","co","pe","ve","fund","capital","trade",
    "trading","finance","money","invest","exchange","markets","cash",
    "crypto","coin","token","network","gg","la","im","is","ly",
)
BIO_DOMAIN_RX = re.compile(
    r"(?:https?://)?(?:www\.)?"
    r"([a-z0-9][a-z0-9\-]{1,62}(?:\.[a-z]{2,16})+)"
    r"(?=\W|$)",
    re.I)
# The bio is inside this preview span class on modern TV. Class hash is opaque
# but stable suffix `-HQxEs30K` works as of 2026. We extract a broader regex
# that catches any span with role="text" or class containing "preview" so it's
# robust to class-name churn.
BIO_BLOCK_RX = re.compile(
    r'<(?:span|div)[^>]*class="[^"]*(?:preview|signature|signatureText)[^"]*"[^>]*>(.*?)</(?:span|div)>',
    re.I | re.DOTALL)

# Skip mentions of domains that are obviously not a user's own website.
EXTERNAL_BLOCKLIST_DOMAINS = {
    "tradingview.com", "tradingview-user-uploads.b-cdn.net",
    "tradingview-widget.com", "tradingviewstore.com",
    # Link shorteners — never the user's actual site
    "bit.ly", "tinyurl.com", "ow.ly", "t.co", "buff.ly", "rebrand.ly",
    "shorturl.at", "rb.gy", "is.gd", "v.gd", "cli.gs",
    "googleapis.com", "gstatic.com", "googletagmanager.com",
    "google.com", "google-analytics.com", "googleadservices.com",
    "doubleclick.net", "facebook.com", "fbcdn.net", "instagram.com",
    "twitter.com", "x.com", "t.co", "youtube.com", "youtu.be",
    "linkedin.com", "tiktok.com", "discord.com", "discord.gg",
    "t.me", "telegram.org", "github.com", "medium.com",
    "schema.org", "w3.org", "creativecommons.org",
    # Hosting platforms — usually not the user's brand site
    "wix.com", "wixsite.com", "weebly.com", "squarespace.com",
    "godaddysites.com", "carrd.co", "linktr.ee", "lnk.bio",
    "beacons.ai", "bento.me",
    # Course/community platforms (point to a profile, not the user's brand)
    "skool.com", "lemonsqueezy.com", "gumroad.com", "podia.com",
    "teachable.com", "thinkific.com", "kajabi.com", "circle.so",
    "patreon.com", "ko-fi.com", "buymeacoffee.com",
    # Email providers (a personal gmail.com etc. isn't a project site)
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com",
}

# Built-in TradingView/social handles to ignore
HANDLE_BLOCKLIST = {
    "tradingview", "TradingView",
}


def _read_set(p: Path) -> set[str]:
    s: set[str] = set()
    if p.exists():
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                s.add(line)
    return s


def discover(out_file: str, max_pages: int = 200, start_page: int = 1) -> int:
    """Iterate /scripts/page-N/ collecting author handles. Stops when a page
    yields zero new handles in a row (likely past end)."""
    out_path = Path(out_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seen = _read_set(out_path)
    print(f"=== TV discover -> {out_file}  pages={start_page}..{start_page+max_pages-1} ===")
    print(f"  starting with {len(seen)} handles in queue")
    start_playwright_pool()
    consecutive_empty = 0
    try:
        for pg in range(start_page, start_page + max_pages):
            url = f"{TV_BASE}/scripts/" if pg == 1 else f"{TV_BASE}/scripts/page-{pg}/"
            html = fetch_html_playwright(url, timeout=15)
            if not html:
                print(f"  page-{pg}: no html")
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    print(f"  giving up after 3 empty pages")
                    break
                continue
            new_handles: list[str] = []
            for h in HANDLE_RX.findall(html):
                if h in HANDLE_BLOCKLIST or h in seen:
                    continue
                seen.add(h)
                new_handles.append(h)
            print(f"  page-{pg}: +{len(new_handles)} new (queue {len(seen)})")
            if new_handles:
                with open(out_path, "a", encoding="utf-8") as f:
                    for h in new_handles:
                        f.write(h + "\n")
                consecutive_empty = 0
            else:
                consecutive_empty += 1
                if consecutive_empty >= 5:
                    print(f"  5 pages without new handles — stopping")
                    break
    finally:
        stop_playwright_pool()
    print(f"DONE — {len(seen)} unique handles total")
    return 0


def _external_url_from_profile(html: str) -> Optional[str]:
    """Find the author's own website on their TV profile page.

    Two strategies, in order:
      1. <a href> tagged with ?utm_source=tradingview (cleanest signal).
      2. Plain-text domain mention inside the bio span. We pick the first
         non-blocklisted domain — usually the user's own site (they almost
         never plug a competitor's URL in their bio).

    Returns a canonical https URL, or None if no candidate found.
    """
    html = html or ""
    m = UTM_URL_RX.search(html)
    if m:
        url = re.sub(r"[?&]utm_source=tradingview[^&]*", "", m.group(0))
        if url.endswith("?") or url.endswith("&"):
            url = url[:-1]
        return url

    # Fall back to bio text. Find the bio block, then the first plausible
    # domain mention inside it.
    bio_match = BIO_BLOCK_RX.search(html)
    if bio_match:
        bio_text = bio_match.group(1)
    else:
        # Couldn't find bio block; scan a window near the top of the page
        # (where the profile header lives) as a last resort.
        bio_text = html[:80000]

    for m in BIO_DOMAIN_RX.finditer(bio_text):
        domain = m.group(1).lower()
        # Require last label to be a recognized public TLD; otherwise we
        # spuriously match JS variables like `window.initdata`, `app.value`
        last_label = domain.rsplit(".", 1)[-1]
        if last_label not in VALID_TLDS:
            continue
        if domain in EXTERNAL_BLOCKLIST_DOMAINS:
            continue
        if any(domain.endswith("." + b) or domain == b for b in EXTERNAL_BLOCKLIST_DOMAINS):
            continue
        # Skip obvious file extensions captured by the broad regex
        if domain.endswith((".js", ".css", ".png", ".jpg", ".svg", ".json")):
            continue
        # Skip raw IP-like patterns
        if re.match(r"^\d+\.\d+\.\d+\.\d+$", domain):
            continue
        # Skip if domain is suspiciously short (likely a partial match)
        if len(domain) < 5:
            continue
        return f"https://{domain}"
    return None


def run(niche_slug: str, queue_file: str, *, limit: int, dry: bool,
        smtp: bool, allow_role_mailboxes: bool = True) -> int:
    """Scrape emails from each queued TradingView author's external website.

    `allow_role_mailboxes` is True by default because for influencer-style
    outreach, the company's published contact mailbox (contact@luxalgo.com,
    support@bigbeluga.com) IS the right target — these emails go to the
    founder/team who can decide on partnerships, not to a random support
    desk. Set False to fall back to the niche YAML's exclude_local_parts.
    """
    queue_path = Path(queue_file)
    if not queue_path.exists():
        sys.exit(f"queue file not found: {queue_path}")
    done_path = queue_path.with_suffix(queue_path.suffix + ".done")
    done = _read_set(done_path)

    niche = load_niche(niche_slug)
    profile_slug = niche.get("profile_slug") or "aureon"
    exclude_locals = (set() if allow_role_mailboxes
                      else set(niche.get("filter", {}).get("exclude_local_parts", []))
                           | JUNK_LOCAL_PARTS)
    exclude_domains = set(niche.get("filter", {}).get("exclude_domains", []))
    require_name = bool(niche.get("require_first_name", True))  # crypto: company-only OK
    supa = ("", "") if dry else load_supabase()

    handles = [h for h in _read_set(queue_path) if h not in done]
    if limit:
        handles = handles[:limit]

    print(f"=== TV run -> {niche_slug} ===")
    print(f"  queue size:  {len(handles)} (skipping {len(done)} done)")
    print(f"  profile:     {profile_slug}")
    print(f"  smtp probe:  {smtp}")
    print(f"  dry:         {dry}\n")

    summary = {"handles": 0, "with_website": 0, "sites_fetched": 0,
               "verified": 0, "rejected": 0, "skipped_generic": 0,
               "skipped_low_quality": 0, "upserted": 0}

    start_playwright_pool()
    try:
        for handle in handles:
            summary["handles"] += 1
            print(f"-- {handle}", flush=True)
            prof_url = f"{TV_BASE}/u/{handle}/"
            html = fetch_html_playwright(prof_url, timeout=15)
            ext = _external_url_from_profile(html or "")
            # Mark done regardless (don't re-poke handles without a website)
            with open(done_path, "a", encoding="utf-8") as f:
                f.write(handle + "\n")
            if not ext:
                continue
            summary["with_website"] += 1
            ext = ext.rstrip("/")
            print(f"   website: {ext}", flush=True)

            # Use the same multi-page heuristic as crypto_projects_scrape
            pairs = _try_pages(ext)
            if not pairs:
                continue
            summary["sites_fetched"] += 1
            emails_seen: set[str] = set()
            for page_url, page_html in pairs:
                leads = extract_leads_from_page(page_url, page_html)
                for lead in leads:
                    if lead.email in emails_seen:
                        continue
                    emails_seen.add(lead.email)
                    if _is_junk_email(lead.email):
                        summary["skipped_generic"] += 1
                        continue
                    local, _, dom = lead.email.partition("@")
                    if local in exclude_locals or dom in exclude_domains:
                        summary["skipped_generic"] += 1
                        continue
                    v = verify(lead.email, do_smtp_probe=smtp, do_catchall_probe=smtp)
                    tag = "OK " if v.verified else "BAD"
                    print(f"     [{tag}] {v.method:16} {lead.email:40}  ({handle})", flush=True)
                    if v.verified:
                        summary["verified"] += 1
                    else:
                        summary["rejected"] += 1
                        continue
                    if not lead.company:
                        lead.company = handle
                    if not lead.website:
                        lead.website = ext
                    # QUALITY GATE: crypto copy greets "Hey {first_name},", so a
                    # lead we can't personalize (role mailbox like
                    # contact@tool.com) is unusable — derive a name, reject if
                    # we still have no first_name.
                    if not lead.first_name:
                        lead.first_name = derive_first_name(lead.email, lead.company)
                    if (require_name and not lead.first_name) or not lead.company:
                        summary["skipped_low_quality"] += 1
                        print(f"     [SKIP] low-quality (no "
                              f"{'name' if require_name and not lead.first_name else 'company'}): {lead.email}")
                        continue
                    if dry:
                        continue
                    try:
                        supa_upsert_prospect(supa[0], supa[1], profile_slug, lead, v, niche_slug)
                        summary["upserted"] += 1
                    except Exception as e:
                        print(f"     ! upsert failed: {e}")
    finally:
        stop_playwright_pool()

    print("\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k:18} {v}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_dc = sub.add_parser("discover")
    p_dc.add_argument("--out", required=True)
    p_dc.add_argument("--pages", type=int, default=200)
    p_dc.add_argument("--start-page", type=int, default=1)

    p_rn = sub.add_parser("run")
    p_rn.add_argument("niche_slug")
    p_rn.add_argument("queue_file")
    p_rn.add_argument("--limit", type=int, default=0)
    p_rn.add_argument("--dry", action="store_true")
    p_rn.add_argument("--no-smtp", action="store_true")
    p_rn.add_argument("--strict-locals", action="store_true",
                      help="apply niche's exclude_local_parts (default: allow role mailboxes for influencer outreach)")

    args = ap.parse_args()
    if args.cmd == "discover":
        return discover(args.out, max_pages=args.pages, start_page=args.start_page)
    if args.cmd == "run":
        return run(args.niche_slug, args.queue_file, limit=args.limit,
                   dry=args.dry, smtp=not args.no_smtp,
                   allow_role_mailboxes=not args.strict_locals)
    return 0


if __name__ == "__main__":
    sys.exit(main())
