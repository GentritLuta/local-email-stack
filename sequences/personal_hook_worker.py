"""personal_hook_worker.py — fill the {personal_hook} merge tag per prospect.

For each prospect where:
    * source_platform = 'youtube'
    * personal_hook IS NULL
    * source_url is set

This worker:
    1. Resolves the channel from source_url (handle, channel ID, or URL).
    2. Fetches the most recent uploaded video via YouTube Data API
       (channels.contentDetails.uploads playlist → playlistItems).
    3. Generates a 1-sentence opener that references the actual video title.
    4. PATCHes the prospect row with personal_hook + recent_video_title +
       recent_video_url + personal_hook_generated_at.

Rule-based opener templates (deterministic, no LLM cost):
    "Just saw your video on '{title}' — quick note."
    "Caught your recent upload on '{title}'."
    "Your video '{title}' came across my feed."

Idempotent. Re-running only fills prospects whose personal_hook is still NULL.

CLI:
    py personal_hook_worker.py run [--profile <slug>] [--limit N] [--force]
    py personal_hook_worker.py stats

REQUIRED Supabase columns (paste into Supabase SQL Editor before first run):
    ALTER TABLE prospects ADD COLUMN personal_hook TEXT;
    ALTER TABLE prospects ADD COLUMN recent_video_title TEXT;
    ALTER TABLE prospects ADD COLUMN recent_video_url TEXT;
    ALTER TABLE prospects ADD COLUMN personal_hook_generated_at TIMESTAMPTZ;
"""
from __future__ import annotations

import argparse
import datetime as dt
import random
import re
import sys
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from youtube_scraper import load_api_keys, API_BASE, resolve_channel  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SUPA_ENV = REPO / "sequences" / "supabase.env"


# ─── Supabase config ──────────────────────────────────────────────────────

def _load_supa() -> tuple[str, str]:
    env = {}
    for line in SUPA_ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env["SUPABASE_URL"].rstrip("/") + "/rest/v1", env["SUPABASE_ANON_KEY"]


# ─── Channel ID extraction ────────────────────────────────────────────────

def channel_handle_from_url(url: str) -> Optional[str]:
    """youtube.com/@CryptoCarl, youtube.com/c/CryptoCarl, youtube.com/channel/UC...
    → returns the handle (or channel ID) usable with resolve_channel()."""
    if not url:
        return None
    try:
        u = urlparse(url if url.startswith("http") else f"https://{url}")
    except Exception:
        return None
    if "youtube.com" not in (u.netloc or "") and "youtu.be" not in (u.netloc or ""):
        return None
    path = (u.path or "").strip("/")
    if not path:
        return None
    # @handle
    if path.startswith("@"):
        return path.split("/")[0]
    # /channel/UCxxxxxx
    if path.startswith("channel/"):
        return path.split("/", 1)[1].split("/")[0]
    # /c/Name or /user/Name
    if path.startswith(("c/", "user/")):
        return path.split("/", 1)[1].split("/")[0]
    return None


# ─── YouTube API: fetch latest video for a channel ────────────────────────

def fetch_latest_video(c: httpx.Client, api_key: str,
                        channel_id: str) -> Optional[dict]:
    """Return {title, video_id, url, published_at} for the most recent
    upload, or None if the channel has no uploads / API errors."""
    # Channel.contentDetails.relatedPlaylists.uploads is the auto-playlist
    # of every video the channel has uploaded, newest first.
    r = c.get(f"{API_BASE}/channels",
              params={"part": "contentDetails", "id": channel_id, "key": api_key},
              timeout=15)
    if r.status_code != 200:
        return None
    items = r.json().get("items") or []
    if not items:
        return None
    uploads_pid = (items[0].get("contentDetails", {})
                            .get("relatedPlaylists", {})
                            .get("uploads"))
    if not uploads_pid:
        return None

    r = c.get(f"{API_BASE}/playlistItems",
              params={"part": "snippet", "playlistId": uploads_pid,
                       "maxResults": 1, "key": api_key},
              timeout=15)
    if r.status_code != 200:
        return None
    pl_items = r.json().get("items") or []
    if not pl_items:
        return None
    snip = pl_items[0]["snippet"]
    vid = snip.get("resourceId", {}).get("videoId")
    return {
        "title": (snip.get("title") or "").strip(),
        "video_id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}" if vid else None,
        "published_at": snip.get("publishedAt"),
    }


# ─── Hook generation (deterministic templates) ────────────────────────────

HOOK_TEMPLATES = [
    "Just saw your recent upload come across my feed. {title}.",
    "Caught your latest video this week. {title}.",
    "Watched your most recent video. {title}.",
    "Your latest upload popped up on my recommended. {title}.",
]


_APOSTROPHES = ("’", "‘", "ʼ", "'")    # curly + straight
_DASHES_TO_COMMA = ("—", "–", "−")      # em, en, minus-sign

def _sanitize_title(title: str) -> str:
    """Strip every character class the operator has banned from outbound
    copy: apostrophes (curly + straight), em-dashes, en-dashes, double
    hyphens, and word-internal hyphens. Word-internal hyphens become
    spaces so compound words like "100-day" become "100 day"."""
    if not title:
        return ""
    for a in _APOSTROPHES:
        title = title.replace(a, "")
    for d in _DASHES_TO_COMMA:
        title = title.replace(d, ",")
    title = title.replace("--", ",")
    title = re.sub(r"(?<=\w)-(?=\w)", " ", title)
    title = re.sub(r"\s+", " ", title).strip()
    return title


def _clip_title(title: str, max_len: int = 70) -> str:
    """Sanitize + truncate overly-long video titles to keep the opener tight."""
    title = _sanitize_title(title)
    if len(title) <= max_len:
        return title
    return title[:max_len - 1].rstrip() + "…"


def generate_hook(video_title: str, seed: Optional[str] = None) -> str:
    """Pick a deterministic template using the email as seed so the same
    prospect always gets the same hook (no jitter across re-runs)."""
    if not video_title:
        return ""
    title = _clip_title(video_title)
    rng = random.Random(seed or video_title)
    tpl = rng.choice(HOOK_TEMPLATES)
    return tpl.format(title=title)


# ─── Worker ──────────────────────────────────────────────────────────────

def fetch_unhooked(c: httpx.Client, profile_slug: Optional[str],
                   limit: int, force: bool) -> list[dict]:
    q = ("/prospects?source_platform=eq.youtube&verified=eq.true"
         "&select=id,email,source_url,first_name,personal_hook")
    if not force:
        q += "&personal_hook=is.null"
    if profile_slug:
        q += f"&profile_slug=eq.{profile_slug}"
    q += f"&limit={limit}&order=created_at.desc"
    r = c.get(q)
    r.raise_for_status()
    return r.json()


def patch_prospect(c: httpx.Client, prospect_id: str, body: dict) -> None:
    r = c.patch(f"/prospects?id=eq.{prospect_id}", json=body,
                headers={"Prefer": "return=minimal"})
    if r.status_code not in (200, 204):
        print(f"   ! patch {prospect_id} -> {r.status_code}: {r.text[:200]}")


def run(profile_slug: Optional[str], limit: int, force: bool) -> int:
    api_keys = load_api_keys()
    if not api_keys:
        sys.exit("no YOUTUBE_API_KEY in sequences/youtube.env")
    api_key = api_keys[0]
    url, anon = _load_supa()
    H = {"apikey": anon, "Authorization": f"Bearer {anon}",
         "Content-Type": "application/json"}

    stats = {"checked": 0, "hooked": 0, "no_channel": 0, "no_video": 0,
             "patch_errors": 0}

    with httpx.Client(base_url=url, headers=H, timeout=20) as supa, \
         httpx.Client(timeout=20) as yt:
        prospects = fetch_unhooked(supa, profile_slug, limit, force)
        print(f"=== personal-hook-worker ({len(prospects)} prospects) ===\n")

        for p in prospects:
            stats["checked"] += 1
            handle = channel_handle_from_url(p.get("source_url"))
            email = p["email"]
            if not handle:
                print(f"   - {email}: no channel handle in source_url={p.get('source_url')!r}")
                stats["no_channel"] += 1
                continue
            ch = resolve_channel(yt, api_key, handle)
            if not ch:
                print(f"   - {email}: channel resolve failed for {handle!r}")
                stats["no_channel"] += 1
                continue
            channel_id = ch["id"]
            latest = fetch_latest_video(yt, api_key, channel_id)
            if not latest or not latest.get("title"):
                print(f"   - {email}: no recent video for channel {channel_id}")
                stats["no_video"] += 1
                continue

            hook = generate_hook(latest["title"], seed=email)
            patch_prospect(supa, p["id"], {
                "personal_hook":            hook,
                "recent_video_title":       latest["title"],
                "recent_video_url":         latest["url"],
                "personal_hook_generated_at": dt.datetime.utcnow().isoformat() + "Z",
            })
            stats["hooked"] += 1
            print(f"   + {email[:40]:40s}  '{latest['title'][:50]}'")
            print(f"     hook: {hook}")

    print(f"\n=== summary ===")
    for k, v in stats.items():
        print(f"  {k:15} {v}")
    return 0


def stats_cmd() -> int:
    url, anon = _load_supa()
    H = {"apikey": anon, "Authorization": f"Bearer {anon}"}
    with httpx.Client(base_url=url, headers=H, timeout=15) as c:
        for col, q in [
            ("yt + hook",     "/prospects?source_platform=eq.youtube&personal_hook=not.is.null&select=count"),
            ("yt + no-hook",  "/prospects?source_platform=eq.youtube&personal_hook=is.null&select=count"),
            ("yt total",      "/prospects?source_platform=eq.youtube&select=count"),
            ("non-yt total",  "/prospects?source_platform=neq.youtube&select=count"),
        ]:
            r = c.get(q, headers={"Prefer": "count=exact"})
            n = r.headers.get("content-range", "?/?").split("/")[-1]
            print(f"  {col:20} {n}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--profile", default=None)
    p_run.add_argument("--limit", type=int, default=50)
    p_run.add_argument("--force", action="store_true",
                       help="Re-generate even for prospects that already have a hook")
    sub.add_parser("stats")
    args = ap.parse_args()
    if args.cmd == "run":
        return run(args.profile, args.limit, args.force)
    return stats_cmd()


if __name__ == "__main__":
    sys.exit(main())
