"""youtube_worker.py — async, concurrent YouTube scraper.

Pulls pending candidates from prospect_candidates (source=youtube), probes
the YouTube Data API channels.list endpoint with N concurrent workers, and
upserts verified emails into prospects with proper profile_slug isolation.

The async architecture is the multiplier vs the sync `youtube_scraper.py`:
  - Up to 10 concurrent channel.list calls in flight at once
  - Stays well under YouTube's rate limit (recommends 800 req/min for
    channels.list = 13 QPS; we run 10 concurrent ≈ 8-10 QPS)
  - Single shared YouTube API key (multi-key rotation in a later patch)
  - Cross-platform handle fan-out to IG/X/TikTok queues (via queue_lib.enqueue)

CLI:
    py youtube_worker.py run <profile_slug> [--workers 10] [--batch 5000]
    py youtube_worker.py stats <profile_slug>

Daily scheduled task should call `run` once with a sensible batch limit
(usually 4500-5000, leaving 500-1000 quota for discovery later in the day).
"""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import re
import sys
from pathlib import Path
from typing import Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lead_verify import verify, GENERIC_LOCAL_PARTS  # noqa: E402
from lead_scrape import (  # noqa: E402
    ScrapedLead, load_supabase, supa_upsert_prospect, EMAIL_TEXT_RX,
)
from youtube_scraper import (  # noqa: E402
    load_api_key, load_api_keys, API_BASE, _deobfuscate, emails_from_channel,
    extract_social_handles,
)
from crypto_projects_scrape import _is_junk_email  # noqa: E402
import queue_lib

# ─── per-niche knobs ──────────────────────────────────────────────────────

def _load_niche(slug: str) -> dict:
    """Light niche loader for filter info. The candidate row carries
    niche_slug already, so we just read filters and brand-derived exclusions."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    import yaml  # local import; module is already a project dep
    p = REPO_ROOT / "niches" / f"{slug}.yaml"
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


# ─── API key pool (multi-project rotation) ────────────────────────────────

class KeyPool:
    """Round-robin pool of YouTube API keys with per-key cooldown.
    When a key returns 403 quotaExceeded, it's marked cooled-down until
    the daily reset (~midnight Pacific). Other keys keep serving."""
    def __init__(self, keys: list[str]):
        if not keys:
            raise RuntimeError("KeyPool empty — at least one key required")
        self.keys = keys
        # cooldown[key] = unix timestamp until which key is unusable
        self.cooldown: dict[str, float] = {}
        self.lock = asyncio.Lock()
        self.next_idx = 0

    async def get(self) -> Optional[str]:
        """Return an available key, or None if all are cooled down."""
        async with self.lock:
            import time as _t
            now = _t.time()
            for _ in range(len(self.keys)):
                k = self.keys[self.next_idx]
                self.next_idx = (self.next_idx + 1) % len(self.keys)
                if self.cooldown.get(k, 0) <= now:
                    return k
            return None

    async def mark_exhausted(self, key: str) -> None:
        """Cool this key down until next Pacific midnight (rough YouTube reset)."""
        async with self.lock:
            import time as _t
            # 24h-from-now is a safe over-cooldown; we'll re-test next day.
            self.cooldown[key] = _t.time() + 24 * 3600


# ─── Channel resolution + email extraction (async) ────────────────────────

async def resolve_channel_async(client: httpx.AsyncClient, pool: KeyPool,
                                handle_or_id: str) -> Optional[dict]:
    """Async resolve. Uses the key pool — rotates keys on 403 quota.
    Raises QuotaExhausted when all keys are cooled down."""
    h = handle_or_id.strip().lstrip("@")
    is_id = bool(re.fullmatch(r"UC[A-Za-z0-9_\-]{22}", handle_or_id))

    while True:
        key = await pool.get()
        if key is None:
            raise RuntimeError("quota: all keys exhausted")
        params = {"part": "snippet,brandingSettings", "key": key}
        if is_id:
            params["id"] = handle_or_id
        else:
            params["forHandle"] = f"@{h}"
        try:
            r = await client.get(f"{API_BASE}/channels", params=params, timeout=15)
        except Exception as e:
            raise RuntimeError(f"channels.list timeout: {e}")
        if r.status_code == 200:
            items = r.json().get("items") or []
            return items[0] if items else None
        if r.status_code == 403 and "quota" in r.text.lower():
            # Key exhausted — cool it down, try the next one
            await pool.mark_exhausted(key)
            continue
        # Other errors are not quota — surface them
        raise RuntimeError(f"channels.list {r.status_code}: {r.text[:160]}")


# ─── Worker ───────────────────────────────────────────────────────────────

async def worker_loop(worker_idx: int, sem: asyncio.Semaphore,
                      pool: KeyPool, profile_slug: str,
                      candidates: list[dict], niche_filters: dict,
                      summary: dict, supa: tuple[str, str], dry: bool) -> None:
    """Each worker grabs items from `candidates` (shared mutable list, popped
    under sem). Probes YouTube, extracts emails, verifies, upserts. Marks
    each candidate done|failed in the queue table."""
    REPO_ROOT = Path(__file__).resolve().parent.parent
    fanout_files = {
        "instagram": REPO_ROOT / "niches" / "crypto_social_handles.txt",
        "twitter":   REPO_ROOT / "niches" / "crypto_social_handles.txt",
        "tiktok":    REPO_ROOT / "niches" / "crypto_social_handles.txt",
    }

    async with httpx.AsyncClient(timeout=httpx.Timeout(20)) as client:
        while True:
            async with sem:
                if not candidates:
                    return
                cand = candidates.pop()
            cid = cand["id"]
            handle = cand["handle"]
            niche_slug = cand.get("niche_slug") or "crypto_influencer"
            try:
                ch = await resolve_channel_async(client, pool, handle)
            except Exception as e:
                err = str(e)[:300]
                # Quota / rate-limit errors are TRANSIENT — release the
                # claim back to pending so tomorrow's run can retry.
                # Permanent errors (404, bad handle) -> failed.
                if "quota" in err.lower() or "403" in err or "429" in err:
                    queue_lib.release_to_pending(cid, last_error=err)
                    summary["quota_blocked"] += 1
                else:
                    queue_lib.mark_done(cid, error=err)
                    summary["errors"] += 1
                continue

            summary["probed"] += 1
            if not ch:
                queue_lib.mark_done(cid)  # no channel found = terminal
                continue
            summary["resolved"] += 1

            # Fan out cross-platform handles into other source queues
            for plat, handles_set in extract_social_handles(ch).items():
                if not handles_set:
                    continue
                try:
                    n = queue_lib.enqueue(profile_slug, niche_slug, plat,
                                          list(handles_set))
                    summary["fanout"][plat] = summary["fanout"].get(plat, 0) + n
                except Exception:
                    pass

            # Extract emails from About / description
            pairs = emails_from_channel(ch)
            if not pairs:
                queue_lib.mark_done(cid)
                continue

            title = ch.get("snippet", {}).get("title", "")
            channel_url = f"https://www.youtube.com/channel/{ch.get('id','')}"
            exclude_domains = set(niche_filters.get("exclude_domains") or [])
            for email, ctx in pairs:
                if _is_junk_email(email):
                    summary["junk"] += 1
                    continue
                _, _, dom = email.partition("@")
                if dom in exclude_domains:
                    continue
                # MX-only verify (faster; 200/day target needs throughput)
                v = verify(email, do_smtp_probe=False, do_catchall_probe=False)
                if not v.verified:
                    summary["rejected"] += 1
                    continue
                summary["verified"] += 1
                lead = ScrapedLead(
                    email=email,
                    first_name=title.split()[0] if title else None,
                    last_name=" ".join(title.split()[1:]) if len(title.split()) > 1 else None,
                    title="YouTube creator",
                    company=title,
                    website=channel_url,
                    source_url=channel_url,
                    context={"channel_handle": handle,
                              "about_snippet": ctx[:200]},
                )
                if dry:
                    continue
                try:
                    supa_upsert_prospect(supa[0], supa[1], profile_slug,
                                         lead, v, niche_slug)
                    summary["upserted"] += 1
                except Exception as e:
                    summary["upsert_errors"] += 1
                    print(f"     ! upsert {email}: {e}", flush=True)
            queue_lib.mark_done(cid)


async def run_async(profile_slug: str, batch_size: int, workers: int,
                    dry: bool, api_key_file: Optional[str] = None) -> int:
    if api_key_file:
        keys = load_api_keys(Path(api_key_file))
    else:
        keys = load_api_keys()
    if not keys:
        sys.exit("no YouTube API keys loaded")
    pool = KeyPool(keys)
    if not dry:
        supa = load_supabase()
    else:
        supa = ("", "")

    print(f"=== youtube_worker -> {profile_slug}  workers={workers}  batch={batch_size}  keys={len(keys)} ===")

    # Claim a batch. For 10 workers w/ 5000 batch, each worker gets ~500.
    candidates = queue_lib.claim_batch(profile_slug, "youtube",
                                       batch_size=batch_size)
    if not candidates:
        print("  no pending candidates")
        return 0
    print(f"  claimed {len(candidates)} candidates")

    # Load niche filters from ANY candidate (assume single niche per batch)
    niche_slug = candidates[0].get("niche_slug", "crypto_influencer")
    niche_data = _load_niche(niche_slug)
    niche_filters = niche_data.get("filter") or {}

    summary = {
        "probed": 0, "resolved": 0, "verified": 0, "rejected": 0,
        "junk": 0, "upserted": 0, "errors": 0, "upsert_errors": 0,
        "quota_blocked": 0,
        "fanout": {},
    }

    sem = asyncio.Semaphore(workers)
    started = dt.datetime.utcnow()
    coros = [worker_loop(i, sem, pool, profile_slug, candidates,
                         niche_filters, summary, supa, dry)
             for i in range(workers)]
    await asyncio.gather(*coros)
    elapsed = (dt.datetime.utcnow() - started).total_seconds()

    print("\n=== summary ===")
    for k, v in summary.items():
        print(f"  {k:18} {v}")
    print(f"  elapsed_sec        {elapsed:.1f}")
    print(f"  per_second         {summary['probed']/max(elapsed,1):.1f}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run")
    p_run.add_argument("profile_slug")
    p_run.add_argument("--workers", type=int, default=10)
    p_run.add_argument("--batch", type=int, default=2000)
    p_run.add_argument("--dry", action="store_true")
    p_run.add_argument("--keys", default=None,
                       help="path to env file with YOUTUBE_API_KEY_N entries (default: youtube.env)")

    p_st = sub.add_parser("stats")
    p_st.add_argument("profile_slug", nargs="?", default=None)

    args = ap.parse_args()
    if args.cmd == "run":
        return asyncio.run(run_async(args.profile_slug, args.batch,
                                      args.workers, args.dry,
                                      api_key_file=args.keys))
    if args.cmd == "stats":
        import json as _json
        print(_json.dumps(queue_lib.stats(args.profile_slug, "youtube"),
                          indent=2))
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
