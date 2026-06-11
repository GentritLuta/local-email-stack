"""social_scrape.py — multi-platform social profile scraper.

One CLI for Instagram, Twitter/X, TikTok, and Twitch. Each platform shares
the same engine: take a list of handles, fetch each profile page (via
Playwright for HTML-based platforms, REST API for Twitch), extract email
from the rendered content, verify, and upsert with proper profile_slug
isolation.

The shape mirrors tradingview_scrape.py — discovery is intentionally
NOT built into this module because each platform's discovery story differs
(IG/X = hashtag/keyword search not free, TikTok = same, Twitch = Helix
search.list). Discovery is fed via curated handle files or by enriching
from another source's output.

CLI:
    py social_scrape.py instagram <niche> <handles_file> [--limit N]
    py social_scrape.py twitter   <niche> <handles_file> [--limit N]
    py social_scrape.py tiktok    <niche> <handles_file> [--limit N]
    py social_scrape.py twitch    <niche> <handles_file> [--limit N]  # uses helix API
    py social_scrape.py probe     <platform> <handle>                 # diagnostic

Per-platform notes:
  instagram: works without login as of 2026, ~25% yield on crypto creators
  twitter:   works without login as of 2026, ~20% yield, FRAGILE
             (X tightens periodically; expect breakage every few weeks)
  tiktok:    almost everything is gated behind login; <5% yield without
             credentials. Built but flagged.
  twitch:    needs TWITCH_CLIENT_ID + TWITCH_CLIENT_SECRET in twitch.env.
             Free credentials at dev.twitch.tv/console/apps.

Multi-client: same `profile_slug` + `niche_slug` isolation as the rest of
the stack. Each niche YAML names which social platforms to use.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lead_verify import verify, GENERIC_LOCAL_PARTS  # noqa: E402
from lead_scrape import (  # noqa: E402
    ScrapedLead, load_supabase, supa_upsert_prospect, load_niche,
    fetch_html_playwright, start_playwright_pool, stop_playwright_pool,
)
from crypto_projects_scrape import _is_junk_email  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# Generic email regex (same as lead_verify-compatible)
EMAIL_RX = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9\-]*[A-Za-z0-9])?)+",
)

# Common obfuscation patterns: "x (at) y (dot) com", "x AT y DOT com", etc.
DEOBFUSCATE = [
    (re.compile(r"\s*[\(\[\{]\s*at\s*[\)\]\}]\s*", re.I), "@"),
    (re.compile(r"\s+at\s+(?=[A-Za-z0-9.\-]+\s*(?:[\(\[\{]\s*dot\s*[\)\]\}]|\.|\s+dot\s+))", re.I), "@"),
    (re.compile(r"\s*[\(\[\{]\s*dot\s*[\)\]\}]\s*", re.I), "."),
    (re.compile(r"\s+dot\s+", re.I), "."),
    (re.compile(r"\s*&#64;\s*"), "@"),
]


def _deobfuscate(text: str) -> str:
    for rx, repl in DEOBFUSCATE:
        text = rx.sub(repl, text)
    return text


@dataclass
class PlatformConfig:
    name: str
    url_template: str           # "https://www.instagram.com/{handle}/"
    handle_strip: str = "@"     # leading char to strip from input handles
    user_label: str = "creator" # what we set as 'title' on the prospect


PLATFORMS = {
    "instagram": PlatformConfig(
        name="instagram",
        url_template="https://www.instagram.com/{handle}/",
        user_label="Instagram creator",
    ),
    "twitter": PlatformConfig(
        name="twitter",
        url_template="https://x.com/{handle}",
        user_label="X/Twitter creator",
    ),
    "tiktok": PlatformConfig(
        name="tiktok",
        url_template="https://www.tiktok.com/@{handle}",
        user_label="TikTok creator",
    ),
}


def _read_handles(path: Path) -> list[str]:
    if not path.exists():
        sys.exit(f"queue file not found: {path}")
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip().lstrip("@")
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _emails_from_page(html: str) -> list[tuple[str, str]]:
    """Pull emails out of arbitrary social profile HTML. Returns
    (email, context_snippet) pairs deduped by email. Strips obvious junk."""
    deob = _deobfuscate(html or "")
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in EMAIL_RX.finditer(deob):
        email = m.group(0).lower()
        if email in seen:
            continue
        if _is_junk_email(email):
            continue
        seen.add(email)
        start = max(0, m.start() - 80)
        end = min(len(deob), m.end() + 80)
        ctx = re.sub(r"\s+", " ", deob[start:end]).strip()
        out.append((email, ctx))
    return out


# ─── Playwright-based platforms (IG / X / TikTok) ─────────────────────────

def run_playwright_platform(platform: str, niche_slug: str, queue_file: str,
                            *, limit: int, dry: bool, smtp: bool) -> int:
    cfg = PLATFORMS[platform]
    queue_path = Path(queue_file)
    handles = _read_handles(queue_path)
    done_path = queue_path.with_suffix(queue_path.suffix + f".{platform}.done")
    done: set[str] = set()
    if done_path.exists():
        for raw in done_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                done.add(line)
    pending = [h for h in handles if h not in done]
    if limit:
        pending = pending[:limit]

    niche = load_niche(niche_slug)
    profile_slug = niche.get("profile_slug") or "aureon"
    exclude_domains = set(niche.get("filter", {}).get("exclude_domains", []))
    # For social platforms, allow role mailboxes by default (the channel IS
    # the lead identity — `business@brand.com` is fine).
    supa = ("", "") if dry else load_supabase()

    print(f"=== social_scrape[{platform}] -> {niche_slug} ===")
    print(f"  queue:       {len(pending)} pending ({len(done)} done, {len(handles)} total)")
    print(f"  profile:     {profile_slug}")
    print(f"  smtp probe:  {smtp}")
    print(f"  dry:         {dry}\n")

    summary = {"handles": 0, "pages_fetched": 0, "emails_found": 0,
               "verified": 0, "rejected": 0, "skipped_junk": 0, "upserted": 0}

    start_playwright_pool()
    try:
        for h in pending:
            summary["handles"] += 1
            url = cfg.url_template.format(handle=h)
            print(f"-- {platform}: {h}", flush=True)
            html = fetch_html_playwright(url, timeout=15)
            # Mark done regardless so we don't re-poke fail cases
            with open(done_path, "a", encoding="utf-8") as f:
                f.write(h + "\n")
            if not html:
                continue
            summary["pages_fetched"] += 1
            pairs = _emails_from_page(html)
            if not pairs:
                continue
            for email, ctx in pairs:
                summary["emails_found"] += 1
                _, _, domain = email.partition("@")
                if domain in exclude_domains:
                    summary["skipped_junk"] += 1
                    continue
                v = verify(email, do_smtp_probe=smtp, do_catchall_probe=smtp)
                tag = "OK " if v.verified else "BAD"
                print(f"     [{tag}] {v.method:16} {email:40}  ({h})", flush=True)
                if v.verified:
                    summary["verified"] += 1
                else:
                    summary["rejected"] += 1
                    continue
                lead = ScrapedLead(
                    email=email,
                    first_name=None,
                    last_name=None,
                    title=cfg.user_label,
                    company=h,
                    website=url,
                    source_url=url,
                    context={"platform": platform, "handle": h,
                              "snippet": ctx[:200]},
                )
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


# ─── Twitch (Helix API) ────────────────────────────────────────────────────

TWITCH_ENV = REPO_ROOT / "sequences" / "twitch.env"

def load_twitch_creds() -> tuple[str, str]:
    if not TWITCH_ENV.exists():
        sys.exit(f"missing {TWITCH_ENV} — set TWITCH_CLIENT_ID + TWITCH_CLIENT_SECRET\n"
                 f"  register an app at https://dev.twitch.tv/console/apps")
    env: dict[str, str] = {}
    for line in TWITCH_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    cid, csec = env.get("TWITCH_CLIENT_ID", ""), env.get("TWITCH_CLIENT_SECRET", "")
    if not cid or not csec:
        sys.exit(f"empty TWITCH_CLIENT_ID/SECRET in {TWITCH_ENV}")
    return cid, csec


def twitch_app_token(client_id: str, client_secret: str) -> str:
    r = httpx.post("https://id.twitch.tv/oauth2/token",
                   data={"client_id": client_id, "client_secret": client_secret,
                         "grant_type": "client_credentials"}, timeout=15)
    r.raise_for_status()
    return r.json()["access_token"]


def run_twitch(niche_slug: str, queue_file: str, *, limit: int,
               dry: bool, smtp: bool) -> int:
    cid, csec = load_twitch_creds()
    tok = twitch_app_token(cid, csec)
    queue_path = Path(queue_file)
    handles = _read_handles(queue_path)
    done_path = queue_path.with_suffix(queue_path.suffix + ".twitch.done")
    done: set[str] = set()
    if done_path.exists():
        for raw in done_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                done.add(line)
    pending = [h for h in handles if h not in done]
    if limit:
        pending = pending[:limit]

    niche = load_niche(niche_slug)
    profile_slug = niche.get("profile_slug") or "aureon"
    supa = ("", "") if dry else load_supabase()

    print(f"=== social_scrape[twitch] -> {niche_slug} ===")
    print(f"  queue: {len(pending)} pending  ({len(done)} done, {len(handles)} total)")

    headers = {"Client-ID": cid, "Authorization": f"Bearer {tok}"}
    summary = {"handles": 0, "resolved": 0, "with_panels": 0,
               "verified": 0, "rejected": 0, "upserted": 0}

    with httpx.Client(timeout=15) as c:
        for h in pending:
            summary["handles"] += 1
            print(f"-- twitch: {h}", flush=True)
            # Helix: get user info by login
            r = c.get("https://api.twitch.tv/helix/users",
                      params={"login": h}, headers=headers)
            if r.status_code != 200:
                print(f"   ! users.list {r.status_code}: {r.text[:120]}")
                continue
            items = r.json().get("data") or []
            if not items:
                with open(done_path, "a", encoding="utf-8") as f:
                    f.write(h + "\n")
                continue
            user = items[0]
            summary["resolved"] += 1
            # Twitch's bio is `description`; panels (about/contact) live in
            # the user "panels" endpoint which requires a separate call.
            desc = user.get("description") or ""
            # Many streamers paste their business email directly in the bio
            pairs = _emails_from_page(desc)
            with open(done_path, "a", encoding="utf-8") as f:
                f.write(h + "\n")
            if not pairs:
                continue
            summary["with_panels"] += 1
            for email, ctx in pairs:
                v = verify(email, do_smtp_probe=smtp, do_catchall_probe=smtp)
                tag = "OK " if v.verified else "BAD"
                print(f"     [{tag}] {v.method:16} {email:40}  ({h})", flush=True)
                if v.verified:
                    summary["verified"] += 1
                else:
                    summary["rejected"] += 1
                    continue
                lead = ScrapedLead(
                    email=email,
                    first_name=user.get("display_name", "").split()[0] if user.get("display_name") else None,
                    title="Twitch streamer",
                    company=user.get("display_name") or h,
                    website=f"https://twitch.tv/{h}",
                    source_url=f"https://twitch.tv/{h}",
                    context={"platform": "twitch", "handle": h,
                              "snippet": ctx[:200]},
                )
                if dry:
                    continue
                try:
                    supa_upsert_prospect(supa[0], supa[1], profile_slug, lead, v, niche_slug)
                    summary["upserted"] += 1
                except Exception as e:
                    print(f"     ! upsert failed: {e}")

    print("\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k:18} {v}")
    return 0


# ─── Probe (diagnostic) ────────────────────────────────────────────────────

def probe(platform: str, handle: str) -> int:
    if platform == "twitch":
        cid, csec = load_twitch_creds()
        tok = twitch_app_token(cid, csec)
        r = httpx.get("https://api.twitch.tv/helix/users",
                      params={"login": handle},
                      headers={"Client-ID": cid, "Authorization": f"Bearer {tok}"},
                      timeout=15)
        print(r.status_code, r.text[:800])
        return 0
    if platform not in PLATFORMS:
        sys.exit(f"unknown platform: {platform}")
    cfg = PLATFORMS[platform]
    start_playwright_pool()
    try:
        html = fetch_html_playwright(cfg.url_template.format(handle=handle), timeout=15)
        print(f"len: {len(html) if html else 0}")
        if html:
            for email, ctx in _emails_from_page(html):
                print(f"  {email}  ({ctx[:80]})")
    finally:
        stop_playwright_pool()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    for platform in ("instagram", "twitter", "tiktok", "twitch"):
        p = sub.add_parser(platform)
        p.add_argument("niche_slug")
        p.add_argument("queue_file")
        p.add_argument("--limit", type=int, default=0)
        p.add_argument("--dry", action="store_true")
        p.add_argument("--no-smtp", action="store_true")

    p_pr = sub.add_parser("probe")
    p_pr.add_argument("platform")
    p_pr.add_argument("handle")

    args = ap.parse_args()

    if args.cmd == "probe":
        return probe(args.platform, args.handle)
    if args.cmd == "twitch":
        return run_twitch(args.niche_slug, args.queue_file, limit=args.limit,
                          dry=args.dry, smtp=not args.no_smtp)
    if args.cmd in PLATFORMS:
        return run_playwright_platform(args.cmd, args.niche_slug, args.queue_file,
                                        limit=args.limit, dry=args.dry,
                                        smtp=not args.no_smtp)
    return 0


if __name__ == "__main__":
    sys.exit(main())
