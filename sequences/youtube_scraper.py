"""youtube_scraper.py — discover lead emails from YouTube creator channels.

Uses the official YouTube Data API v3 (free 10k units/day). For each input
channel handle (e.g. @CryptoWendyO) or channel ID, we fetch the channel's
description / about text and pull any email addresses out of it. Many crypto
influencers list a "business inquiries" email directly in their description.

We use the API instead of scraping the YouTube watch page because:
  - The API path is allowed by YouTube's ToS
  - The description is in `snippet.description` for free (no quota beyond 1
    unit per `channels.list` call)
  - Headless scraping requires JavaScript execution and gets rate-limited

CLI:
    py youtube_scraper.py run <niche_slug> <channels.txt>
    py youtube_scraper.py run <niche_slug> @CryptoWendyO @InvestAnswers ...
    py youtube_scraper.py probe @CryptoWendyO       # show one channel's About

Input file format: one channel handle or ID per line. Lines starting with #
are comments. Handles can include or omit the leading @.

The scraper reuses lead_scrape.supa_upsert_prospect + lead_verify so the
same isolation, verification, and dedup rules apply.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# Channel titles can contain emoji / non-Latin script. Force UTF-8 on stdout/stderr
# so a single weird title doesn't crash a 300-channel run on Windows cp1252.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lead_verify import verify, JUNK_LOCAL_PARTS  # noqa: E402
from lead_scrape import (  # noqa: E402
    ScrapedLead, load_supabase, supa_upsert_prospect, load_niche, EMAIL_TEXT_RX,
)
from name_derive import derive_first_name, derive_company  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE  = REPO_ROOT / "sequences" / "youtube.env"
API_BASE  = "https://www.googleapis.com/youtube/v3"


def load_api_key() -> str:
    """Backwards-compat single-key loader (sync scrapers still use this)."""
    keys = load_api_keys()
    if not keys:
        sys.exit(f"no YOUTUBE_API_KEY in {ENV_FILE}")
    return keys[0]


def load_api_keys(env_path: Optional[Path] = None) -> list[str]:
    """Load 1..N YouTube API keys from the env file. Supports both formats:

      YOUTUBE_API_KEY=AIza...          # legacy single-key
      YOUTUBE_API_KEY_1=AIza...        # multi-key (rotate on quota exhaustion)
      YOUTUBE_API_KEY_2=AIza...

    Order is preserved (first key tried first).
    """
    path = env_path or ENV_FILE
    if not path.exists():
        return []
    keys: list[tuple[str, str]] = []  # (name, key)
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, val = line.partition("=")
        name = name.strip()
        val = val.strip().strip('"').strip("'")
        if name == "YOUTUBE_API_KEY" or name.startswith("YOUTUBE_API_KEY_"):
            if val:
                keys.append((name, val))
    # Sort by suffix number (so _1, _2, _3 keep order); legacy name first
    def sort_key(t: tuple[str, str]) -> tuple[int, int]:
        n = t[0]
        if n == "YOUTUBE_API_KEY":
            return (0, 0)
        try:
            return (1, int(n.rsplit("_", 1)[-1]))
        except ValueError:
            return (2, 0)
    keys.sort(key=sort_key)
    return [k for _, k in keys]


# ─── YouTube API helpers ───────────────────────────────────────────────────

def resolve_channel(client: httpx.Client, api_key: str, handle_or_id: str) -> Optional[dict]:
    """Given an @handle, channel ID, or username, return the channel resource
    (id, title, description, customUrl). Returns None if not found."""
    h = handle_or_id.strip().lstrip("@")
    # Try as channel ID first (starts with UC and is 24 chars).
    if re.fullmatch(r"UC[A-Za-z0-9_\-]{22}", handle_or_id):
        params = {"part": "snippet,brandingSettings", "id": handle_or_id, "key": api_key}
    else:
        # Try forHandle (newer API for @handles). Costs 1 unit.
        params = {"part": "snippet,brandingSettings", "forHandle": f"@{h}", "key": api_key}

    r = client.get(f"{API_BASE}/channels", params=params, timeout=15)
    if r.status_code != 200:
        print(f"   ! channels.list {r.status_code}: {r.text[:200]}")
        return None
    items = r.json().get("items") or []
    if items:
        return items[0]

    # Fallback: search.list by query (costs 100 units). Use sparingly.
    r = client.get(f"{API_BASE}/search",
                   params={"part": "snippet", "type": "channel", "q": h, "key": api_key},
                   timeout=15)
    if r.status_code != 200:
        return None
    items = r.json().get("items") or []
    if not items:
        return None
    cid = items[0]["snippet"]["channelId"]
    r = client.get(f"{API_BASE}/channels",
                   params={"part": "snippet,brandingSettings", "id": cid, "key": api_key},
                   timeout=15)
    if r.status_code != 200:
        return None
    items = r.json().get("items") or []
    return items[0] if items else None


_OBFUSCATION_PATTERNS = [
    (re.compile(r"\s*[\(\[\{]\s*at\s*[\)\]\}]\s*", re.I), "@"),
    (re.compile(r"\s+at\s+(?=[A-Za-z0-9.\-]+\s*(?:[\(\[\{]\s*dot\s*[\)\]\}]|\.|\s+dot\s+)\s*[a-z]{2,})", re.I), "@"),
    (re.compile(r"\s*[\(\[\{]\s*dot\s*[\)\]\}]\s*", re.I), "."),
    (re.compile(r"\s+dot\s+", re.I), "."),
    (re.compile(r"\s*&#64;\s*"), "@"),
]

def _deobfuscate(text: str) -> str:
    """Convert common email obfuscations (x (at) y (dot) com) back to canonical
    form so the EMAIL_TEXT_RX can match. We run multiple passes since some
    channels combine patterns ('x [at] y [dot] com')."""
    out = text
    for rx, repl in _OBFUSCATION_PATTERNS:
        out = rx.sub(repl, out)
    return out


# Cross-platform handle extraction patterns — used to seed IG/X/TikTok
# scraper queues from each YouTube channel's description. Many crypto
# creators list their other socials in YouTube About.
SOCIAL_HANDLE_PATTERNS = {
    "instagram": [
        re.compile(r"instagram\.com/([A-Za-z0-9_.]{2,30})/?", re.I),
        re.compile(r"@?([A-Za-z0-9_.]{2,30})\s*(?:on|@)?\s*instagram\b", re.I),
    ],
    "twitter": [
        re.compile(r"(?:twitter|x)\.com/([A-Za-z0-9_]{2,15})", re.I),
        re.compile(r"@([A-Za-z0-9_]{2,15})\s+on\s+(?:twitter|x)\b", re.I),
    ],
    "tiktok": [
        re.compile(r"tiktok\.com/@?([A-Za-z0-9_.]{2,30})", re.I),
    ],
}


def extract_social_handles(channel: dict) -> dict[str, set[str]]:
    """From a channel.list resource, pull mentioned Instagram/X/TikTok
    handles. Reused at run-time to fan out the lead pipeline cross-platform."""
    desc = (channel.get("snippet", {}).get("description") or "") + "\n" + \
           ((channel.get("brandingSettings", {}).get("channel", {})
                    .get("description")) or "")
    out: dict[str, set[str]] = {}
    for plat, patterns in SOCIAL_HANDLE_PATTERNS.items():
        s: set[str] = set()
        for rx in patterns:
            for m in rx.finditer(desc):
                handle = m.group(1).strip().lstrip("@")
                # Skip obviously-not-handle captures
                if len(handle) < 2 or "/" in handle or "." in handle.rstrip("."):
                    if not handle.endswith("."):
                        s.add(handle.rstrip("."))
                else:
                    s.add(handle)
        if s:
            out[plat] = s
    return out


def append_handles_to_queue(handles: set[str], queue_file: Path) -> int:
    """Append new handles (deduped) to a queue file. Returns count added."""
    existing: set[str] = set()
    if queue_file.exists():
        for raw in queue_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip().lstrip("@")
            if line and not line.startswith("#"):
                existing.add(line)
    new = handles - existing
    if not new:
        return 0
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    with open(queue_file, "a", encoding="utf-8") as f:
        for h in sorted(new):
            f.write(h + "\n")
    return len(new)


def emails_from_channel(channel: dict) -> list[tuple[str, str]]:
    """Pull all email addresses out of a channel resource. Returns (email,
    surrounding_context) pairs so we can keep a snippet for the bio field.
    Deobfuscates common patterns first."""
    title = channel.get("snippet", {}).get("title", "")
    desc  = channel.get("snippet", {}).get("description", "") or ""
    branding_desc = (channel.get("brandingSettings", {})
                            .get("channel", {})
                            .get("description", "")) or ""
    raw_blob = "\n".join([title, desc, branding_desc])
    blob = _deobfuscate(raw_blob)

    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in EMAIL_TEXT_RX.finditer(blob):
        email = m.group(0).strip().lower()
        if email in seen:
            continue
        seen.add(email)
        start = max(0, m.start() - 80)
        end = min(len(blob), m.end() + 80)
        ctx = re.sub(r"\s+", " ", blob[start:end]).strip()
        out.append((email, ctx))
    return out


# ─── Input parsing ─────────────────────────────────────────────────────────

def load_channels(arg: str) -> list[str]:
    """If arg is a path to a file, read one handle/id per line. Otherwise
    treat arg as a single inline handle. Lines starting with # are comments."""
    p = Path(arg)
    if p.is_file():
        out = []
        for raw in p.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            out.append(line)
        return out
    return [arg]


# ─── Main run ──────────────────────────────────────────────────────────────

def run(niche_slug: str, channel_args: list[str], *, dry: bool, smtp: bool,
        allow_role_mailboxes: bool = True, limit: int = 0) -> int:
    """Scrape emails from YouTube channel About pages.

    Stateful — tracks processed handles in a sibling `.done` file so daily
    scheduled runs don't burn quota re-probing the same channels. Combined
    with daily discover this gives a sustainable per-day yield of roughly
    quota_used * (channel_email_rate ~5-10%) = several hundred verified
    emails per day at full free quota.

    `allow_role_mailboxes` defaults to True because for YouTube the channel
    title IS the lead identity — `business@channel.com` is the legitimate
    contact for influencer outreach.
    """
    niche = load_niche(niche_slug)
    profile_slug = niche.get("profile_slug") or "aureon"
    exclude_locals = (set() if allow_role_mailboxes
                      else set(niche.get("filter", {}).get("exclude_local_parts", []))
                           | JUNK_LOCAL_PARTS)
    exclude_domains = set(niche.get("filter", {}).get("exclude_domains", []))
    # name-optional niches (crypto): admit company-only leads (see crypto_influencer.yaml)
    require_name = bool(niche.get("require_first_name", True))

    channels: list[str] = []
    done_path: Optional[Path] = None
    done_set: set[str] = set()
    for a in channel_args:
        p = Path(a)
        if p.is_file():
            # First file argument gets a colocated .done state file
            if done_path is None:
                done_path = p.with_suffix(p.suffix + ".done")
                if done_path.exists():
                    for raw in done_path.read_text(encoding="utf-8").splitlines():
                        line = raw.strip()
                        if line and not line.startswith("#"):
                            done_set.add(line)
        channels.extend(load_channels(a))
    channels = [c for c in channels if c]
    if not channels:
        sys.exit("no channels supplied")
    # Filter out already-processed handles (massive quota saver on daily runs)
    pre_count = len(channels)
    channels = [c for c in channels if c not in done_set]
    skipped_done = pre_count - len(channels)

    # Auto-refill from crypto_yt_discovered.txt when the active queue is
    # fully drained. Without this the pool-monitor autopilot would spawn
    # the scraper every 2 hours and find 0 unprocessed channels — the
    # AlgoAlpha pool would never grow despite 3,000+ handles available
    # in the discovered backlog. Append the next 200 unscraped handles.
    if not channels and done_path is not None:
        discovered_path = done_path.parent / "crypto_yt_discovered.txt"
        active_file_path = done_path.with_suffix("")  # strip the .done suffix
        # The refill backlog is crypto-specific. Only refill the crypto queue —
        # other niches (dorian_social) grow their active file via `discover`
        # and must NOT inherit crypto handles (2026-06-10 incident: 200 crypto
        # channels auto-appended into dorian_yt_channels.txt and scraped into
        # the dorian pool).
        if (active_file_path.name == "crypto_youtube_channels.txt"
                and discovered_path.exists() and active_file_path.exists()):
            try:
                disc = [l.strip() for l in discovered_path.read_text(encoding="utf-8").splitlines()
                        if l.strip() and not l.startswith("#")]
                active_set = set()
                for raw in active_file_path.read_text(encoding="utf-8").splitlines():
                    line = raw.strip()
                    if line and not line.startswith("#"):
                        active_set.add(line)
                fresh = [h for h in disc if h not in active_set and h not in done_set][:200]
                if fresh:
                    addendum = (
                        f"\n\n# auto-refill {dt.date.today().isoformat()}: "
                        f"{len(fresh)} unscraped handles from crypto_yt_discovered.txt\n"
                        + "\n".join(fresh) + "\n"
                    )
                    with open(active_file_path, "a", encoding="utf-8") as f:
                        f.write(addendum)
                    print(f"  auto-refilled queue with {len(fresh)} fresh handles", flush=True)
                    channels = fresh
            except Exception as e:
                print(f"  auto-refill failed: {e}", flush=True)

    if limit and len(channels) > limit:
        channels = channels[:limit]

    api_key = load_api_key()
    if not dry:
        url, key = load_supabase()

    print(f"=== youtube_scraper: {niche_slug} ({len(channels)} channels) ===")
    print(f"  profile_slug = {profile_slug}")
    print(f"  skipped_done = {skipped_done}")
    print(f"  smtp probe   = {smtp}")
    print(f"  dry          = {dry}\n")

    summary = {"channels": 0, "resolved": 0, "emails_found": 0,
               "verified": 0, "rejected": 0, "skipped_generic": 0,
               "skipped_low_quality": 0, "upserted": 0}

    def mark_done(h: str) -> None:
        if done_path is None:
            return
        try:
            with open(done_path, "a", encoding="utf-8") as f:
                f.write(h + "\n")
        except Exception:
            pass

    # Cross-platform handle fan-out: every channel description gets scanned
    # for IG/X/TikTok handles which feed those platforms' scraper queues.
    niches_dir = REPO_ROOT / "niches"
    fanout_files = {
        "instagram": niches_dir / "crypto_social_handles.txt",
        "twitter":   niches_dir / "crypto_social_handles.txt",
        "tiktok":    niches_dir / "crypto_social_handles.txt",
    }
    fanout_added = {p: 0 for p in fanout_files}

    with httpx.Client() as c:
        for handle in channels:
            summary["channels"] += 1
            print(f"-- {handle}", flush=True)
            ch = resolve_channel(c, api_key, handle)
            # Mark every probed handle done — even "not found" ones, so we
            # don't waste quota repeatedly searching for invalid handles.
            mark_done(handle)
            if not ch:
                print("   ! not found")
                continue
            summary["resolved"] += 1
            title = ch.get("snippet", {}).get("title", "")
            channel_url = f"https://www.youtube.com/channel/{ch.get('id','')}"
            # Fan handles out to the other platforms' queues — they share
            # a single handle list per niche; the per-platform .done files
            # keep the dedup per platform.
            for plat, handles_set in extract_social_handles(ch).items():
                added = append_handles_to_queue(handles_set, fanout_files[plat])
                fanout_added[plat] += added
            pairs = emails_from_channel(ch)
            if not pairs:
                print(f"   (no email in About for '{title}')")
                continue
            for email, ctx in pairs:
                summary["emails_found"] += 1
                local, _, domain = email.partition("@")
                if local in exclude_locals:
                    summary["skipped_generic"] += 1
                    print(f"     [SKIP-generic] {email}")
                    continue
                if domain in exclude_domains:
                    continue

                v = verify(email, do_smtp_probe=smtp, do_catchall_probe=smtp)
                tag = "OK " if v.verified else "BAD"
                print(f"     [{tag}] {v.method:16} {email:40}  ({title[:30]})")

                if v.verified:
                    summary["verified"] += 1
                else:
                    summary["rejected"] += 1
                    continue

                # NOTE: do NOT take first_name from the channel title's first
                # word — channels are named after topics ("Altcoin Nexus",
                # "Crypto Notes") so the first word is the niche, not a human
                # name. Leave first_name None; backfill-algoalpha-prospects.py
                # derives it from the email local-part when a separator is
                # present (firstname.lastname@) and otherwise leaves it null
                # so the strict enrollment gate skips the prospect.
                # Normalize the channel title for use as `company`:
                # - strip whitespace
                # - title-case ALL-CAPS brands ("BITCOIN HOTEL" → "Bitcoin Hotel")
                # - drop Arabic / CJK / Korean script (we send in English/German;
                #   "Crypto News أخبار الكريپتو" → "Crypto News")
                co = (title or "").strip()
                # ؀-ۿ = Arabic, ݐ-ݿ = Arabic Suppl,
                # 一-鿿 = CJK Unified, ぀-ヿ = Hiragana/Katakana,
                # 가-힯 = Hangul. Replace with space then collapse.
                co = re.sub(r"[؀-ۿݐ-ݿ一-鿿぀-ヿ가-힯]+", " ", co)
                co = re.sub(r"\s+", " ", co).strip()
                if co.isupper() and len(co) > 4:
                    co = co.title()
                lead = ScrapedLead(
                    email=email,
                    first_name=None,
                    last_name=None,
                    title="YouTube creator",
                    company=co or None,
                    website=channel_url,
                    source_url=channel_url,
                    context={"channel_handle": handle, "about_snippet": ctx[:200]},
                )

                # QUALITY GATE (same as lead_scrape): derive a real first_name
                # from the email; reject the lead if we can't get a name + a
                # company. Creator emails are often brand-handle gmails
                # (mychannel@gmail.com) — those can't be personalized, so we
                # drop them rather than send "Hi [blank]," and bounce.
                lead.first_name = derive_first_name(email, lead.company)
                if not lead.company:
                    lead.company = derive_company(email)
                if (require_name and not lead.first_name) or not lead.company:
                    summary["skipped_low_quality"] += 1
                    print(f"     [SKIP] low-quality (no "
                          f"{'name' if require_name and not lead.first_name else 'company'}): {email}")
                    continue

                if dry:
                    continue
                try:
                    supa_upsert_prospect(url, key, profile_slug, lead, v, niche_slug)
                    summary["upserted"] += 1
                except Exception as e:
                    print(f"     ! upsert failed: {e}")

    print("\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k:18} {v}")
    if any(fanout_added.values()):
        print("  fanout (cross-platform handles enqueued):")
        for plat, n in fanout_added.items():
            if n:
                print(f"    {plat:10} +{n}")
    return 0


def discover(query_args: list[str], out_file: str, *, max_pages: int = 5,
             region_codes: Optional[list[str]] = None) -> int:
    """Use search.list to enumerate channels by keyword, dedup by channelId,
    append to `out_file`. Each search.list call costs 100 quota units and
    returns up to 50 channels — at 10k daily quota that's max 100 calls/day
    (~5000 new channels). Pagination stops when nextPageToken runs out or
    after max_pages.

    Pass `region_codes` to repeat the same query across multiple country
    biases — this reveals channels weighted toward those audiences (e.g.
    'US' surfaces different results than 'DE' for the same query).

    Skips channels already in `out_file` (so safe to re-run).
    """
    api_key = load_api_key()

    queries: list[str] = []
    for a in query_args:
        p = Path(a)
        if p.is_file():
            for raw in p.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if line and not line.startswith("#"):
                    queries.append(line)
        else:
            queries.append(a)
    if not queries:
        sys.exit("no queries supplied")

    out_path = Path(out_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    if out_path.exists():
        for raw in out_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                seen.add(line)
    print(f"=== youtube discover: {len(queries)} queries, out={out_file}, max_pages={max_pages} ===")
    print(f"  starting with {len(seen)} channels already in queue")

    regions = region_codes or [None]
    quota_used = 0
    quota_limit = 9_500  # leave headroom under 10k daily

    with httpx.Client() as c:
        outer_break = False
        for q in queries:
            if outer_break:
                break
            for region in regions:
                if outer_break:
                    break
                print(f"-- q='{q}'" + (f" (region={region})" if region else ""))
                page_token = None
                for page in range(max_pages):
                    if quota_used + 100 > quota_limit:
                        print(f"   ! near daily quota ({quota_used} used) — stopping")
                        outer_break = True
                        break
                    params = {"part": "snippet", "type": "channel", "q": q,
                              "maxResults": 50, "key": api_key}
                    if region:
                        params["regionCode"] = region
                    if page_token:
                        params["pageToken"] = page_token
                    r = c.get(f"{API_BASE}/search", params=params, timeout=20)
                    quota_used += 100
                    if r.status_code != 200:
                        print(f"   ! search {r.status_code}: {r.text[:200]}")
                        if "quotaExceeded" in r.text:
                            outer_break = True
                        break
                    data = r.json()
                    items = data.get("items", [])
                    new_ids: list[str] = []
                    for it in items:
                        cid = it.get("snippet", {}).get("channelId")
                        if cid and cid not in seen:
                            seen.add(cid)
                            new_ids.append(cid)
                    print(f"   page {page+1}: +{len(new_ids)} new (queue {len(seen)}, quota ~{quota_used})")
                    if new_ids:
                        with open(out_path, "a", encoding="utf-8") as f:
                            for cid in new_ids:
                                f.write(cid + "\n")
                    page_token = data.get("nextPageToken")
                    if not page_token:
                        break

    print(f"\nDONE — {len(seen)} unique channels queued in {out_file}")
    print(f"approx quota used: {quota_used} units")
    return 0


def enrich_from_articles(article_urls: list[str], out_file: str) -> int:
    """Scrape curated 'best crypto YouTubers' articles for channel mentions
    (youtube.com/@handle, youtube.com/c/handle, youtube.com/channel/UC...).
    Appends new handles/IDs to the queue file. No YouTube quota used.

    Yield is high because these lists are pre-curated for established
    audiences — every channel mentioned has at least a few hundred subs
    and the article author thought enough of them to include.
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from lead_scrape import (  # local import to avoid heavy startup cost
        fetch_html_playwright, start_playwright_pool, stop_playwright_pool,
    )

    out_path = Path(out_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    existing: set[str] = set()
    if out_path.exists():
        for raw in out_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                existing.add(line)

    # Three URL forms YouTube uses
    HANDLE_RX  = re.compile(r"youtube\.com/@([A-Za-z0-9_\.\-]{2,40})", re.I)
    CHANNEL_RX = re.compile(r"youtube\.com/channel/(UC[A-Za-z0-9_\-]{22})", re.I)
    USER_RX    = re.compile(r"youtube\.com/(?:c|user)/([A-Za-z0-9_\.\-]{2,40})", re.I)

    print(f"=== enrich from {len(article_urls)} articles -> {out_file} ===")
    print(f"  starting with {len(existing)} in queue")

    start_playwright_pool()
    new_total = 0
    try:
        for url in article_urls:
            print(f"-- {url}")
            html = fetch_html_playwright(url, timeout=20)
            if not html:
                print("   ! no html"); continue
            found: set[str] = set()
            for rx in (HANDLE_RX, USER_RX):
                for m in rx.finditer(html):
                    found.add("@" + m.group(1))
            for m in CHANNEL_RX.finditer(html):
                found.add(m.group(1))
            new = found - existing
            existing.update(new)
            new_total += len(new)
            print(f"   +{len(new)} new ({len(found)} total mentions)")
            if new:
                with open(out_path, "a", encoding="utf-8") as f:
                    for h in sorted(new):
                        f.write(h + "\n")
    finally:
        stop_playwright_pool()

    print(f"\nDONE — +{new_total} new handles ({len(existing)} total in queue)")
    return 0


def probe(handle: str) -> int:
    api_key = load_api_key()
    with httpx.Client() as c:
        ch = resolve_channel(c, api_key, handle)
        if not ch:
            print("not found")
            return 1
        print(f"title       : {ch.get('snippet',{}).get('title')}")
        print(f"channelId   : {ch.get('id')}")
        print(f"customUrl   : {ch.get('snippet',{}).get('customUrl')}")
        print(f"description :\n{ch.get('snippet',{}).get('description','')[:1500]}")
        print(f"\n--- emails found ---")
        for email, ctx in emails_from_channel(ch):
            print(f"  {email}   ({ctx[:80]}...)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("niche_slug")
    p_run.add_argument("channels", nargs="+", help="file path OR inline @handles/IDs")
    p_run.add_argument("--dry", action="store_true")
    p_run.add_argument("--no-smtp", action="store_true")
    p_run.add_argument("--strict-locals", action="store_true",
                       help="apply niche's exclude_local_parts filter (default: allow role mailboxes for YouTube)")
    p_run.add_argument("--limit", type=int, default=0,
                       help="max channels to probe this invocation (0=all). Useful when staying under daily quota.")
    p_pr = sub.add_parser("probe")
    p_pr.add_argument("handle")
    p_dc = sub.add_parser("discover")
    p_dc.add_argument("queries", nargs="+",
                      help="search terms (or path to file with one term per line)")
    p_dc.add_argument("--out", required=True,
                      help="output file — channel IDs appended, dedup against existing content")
    p_dc.add_argument("--pages", type=int, default=5,
                      help="max pages per query (each page = 50 channels, 100 quota units)")
    p_dc.add_argument("--regions", nargs="*", default=None,
                      help="ISO region codes to bias queries (e.g. US DE JP). Default: no bias.")
    p_en = sub.add_parser("enrich",
                          help="scrape curated 'best crypto YouTubers' articles for handle mentions")
    p_en.add_argument("articles", nargs="+",
                      help="article URLs (or path to a file with one URL per line)")
    p_en.add_argument("--out", required=True)
    args = ap.parse_args()

    if args.cmd == "run":
        return run(args.niche_slug, args.channels, dry=args.dry, smtp=not args.no_smtp,
                   allow_role_mailboxes=not args.strict_locals, limit=args.limit)
    if args.cmd == "probe":
        return probe(args.handle)
    if args.cmd == "discover":
        return discover(args.queries, args.out, max_pages=args.pages,
                        region_codes=args.regions)
    if args.cmd == "enrich":
        urls: list[str] = []
        for a in args.articles:
            p = Path(a)
            if p.is_file():
                for raw in p.read_text(encoding="utf-8").splitlines():
                    line = raw.strip()
                    if line and not line.startswith("#"):
                        urls.append(line)
            else:
                urls.append(a)
        return enrich_from_articles(urls, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
