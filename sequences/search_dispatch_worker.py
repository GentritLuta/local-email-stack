"""search_dispatch_worker.py — react to "Start lead search" button clicks.

Polls `search_jobs` for status='pending'. For each, reads the profile's
lead_intent block from Supabase and dispatches the right discovery actions
to enqueue candidates into prospect_candidates. The async workers then
pick them up on the next scheduled cron.

Schedule: every 5 min via Windows Task Scheduler.

CLI:
    py search_dispatch_worker.py once   # process all pending now
    py search_dispatch_worker.py loop   # run forever, polling every 60s
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from queue_lib import _SUPA_URL, _SUPA_KEY, _HEADERS, enqueue
from youtube_scraper import (
    load_api_keys, load_channels, discover as yt_discover,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

# Map intent industries → which seed files to use for which platforms.
# Niche-specific. As more clients land, this grows.
INDUSTRY_SEEDS: dict[str, dict[str, list[Path]]] = {
    "trading_crypto": {
        "youtube_handles":   [REPO_ROOT / "niches" / "crypto_yt_discovered.txt"],
        "youtube_terms":     [REPO_ROOT / "niches" / "crypto_yt_search_terms.txt"],
        "tradingview":       [REPO_ROOT / "niches" / "tv_handles.txt"],
        "instagram":         [REPO_ROOT / "niches" / "crypto_social_handles.txt"],
        "twitter":           [REPO_ROOT / "niches" / "crypto_social_handles.txt"],
        "tiktok":            [REPO_ROOT / "niches" / "crypto_social_handles.txt"],
    },
    # Add more industries as new clients onboard. Each gets seed files in
    # niches/ and registered here.
}


def _read_handles(p: Path) -> list[str]:
    if not p.exists():
        return []
    out: list[str] = []
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip().lstrip("@")
        if line and not line.startswith("#"):
            out.append(line)
    return out


# ─── Supabase helpers ─────────────────────────────────────────────────────

def fetch_pending_jobs() -> list[dict]:
    r = httpx.get(
        f"{_SUPA_URL}/rest/v1/search_jobs?status=eq.pending&order=created_at.asc"
        f"&select=id,profile_slug,niche_slug,intent_snap",
        headers=_HEADERS, timeout=15)
    if r.status_code != 200:
        raise RuntimeError(f"fetch_jobs {r.status_code}: {r.text[:200]}")
    return r.json() or []


def mark_job(job_id: str, status: str, *, last_error: Optional[str] = None,
             result: Optional[dict] = None) -> None:
    body = {
        "status":      status,
        "started_at":  dt.datetime.utcnow().isoformat() + "Z" if status == "running" else None,
        "finished_at": dt.datetime.utcnow().isoformat() + "Z" if status in ("done", "failed") else None,
        "last_error":  last_error[:500] if last_error else None,
        "result":      result,
    }
    body = {k: v for k, v in body.items() if v is not None}
    r = httpx.patch(
        f"{_SUPA_URL}/rest/v1/search_jobs?id=eq.{job_id}",
        headers=_HEADERS, json=body, timeout=15)
    if r.status_code not in (200, 204):
        raise RuntimeError(f"mark_job {r.status_code}: {r.text[:200]}")


def fetch_profile_intent(profile_slug: str) -> Optional[dict]:
    r = httpx.get(
        f"{_SUPA_URL}/rest/v1/profiles?slug=eq.{profile_slug}&select=lead_intent,config",
        headers=_HEADERS, timeout=15)
    if r.status_code != 200 or not r.json():
        return None
    row = r.json()[0]
    # Prefer dedicated column; fall back to config.lead_intent for older profiles
    return row.get("lead_intent") or (row.get("config") or {}).get("lead_intent")


# ─── Dispatch logic ──────────────────────────────────────────────────────

def dispatch_one(job: dict) -> dict:
    """Process a single job. Returns a per-platform result dict for the
    `result` column. Raises on hard failure."""
    profile_slug = job["profile_slug"]
    intent_snap = job.get("intent_snap") or {}
    # If the job carried a snapshot, use it. Otherwise pull live from profile.
    intent = intent_snap or fetch_profile_intent(profile_slug) or {}
    if not intent:
        raise RuntimeError(f"no lead_intent for profile '{profile_slug}'")

    niche_slug = job.get("niche_slug") or "auto_search"
    industries = intent.get("industries") or []
    platforms = [p.lower() for p in (intent.get("platforms") or [])]
    custom_keywords = intent.get("search_keywords") or []

    result: dict = {"per_platform": {}, "intent_applied": intent}

    # For each chosen platform, enqueue candidates from the seed files
    # mapped to each chosen industry.
    for plat in platforms:
        added_total = 0
        for industry in industries:
            seeds = (INDUSTRY_SEEDS.get(industry) or {})
            files = seeds.get(plat) if plat != "youtube" else seeds.get("youtube_handles")
            for f in files or []:
                handles = _read_handles(f)
                if not handles:
                    continue
                added = enqueue(profile_slug, niche_slug, plat, handles)
                added_total += added
        result["per_platform"][plat] = added_total

    # Optionally trigger a fresh YouTube discovery for custom keywords
    if custom_keywords and "youtube" in platforms:
        try:
            tmp_terms = REPO_ROOT / "niches" / f".search_job_{job['id']}.txt"
            tmp_terms.write_text("\n".join(custom_keywords), encoding="utf-8")
            yt_out = REPO_ROOT / "niches" / "crypto_yt_discovered.txt"
            yt_discover([str(tmp_terms)], str(yt_out), max_pages=1)
            tmp_terms.unlink(missing_ok=True)
            result["custom_yt_discover_keywords"] = len(custom_keywords)
        except Exception as e:
            result["custom_yt_discover_error"] = str(e)[:200]

    return result


def run_once() -> int:
    jobs = fetch_pending_jobs()
    if not jobs:
        return 0
    processed = 0
    for job in jobs:
        jid = job["id"]
        print(f"-- job {jid}  profile={job['profile_slug']}", flush=True)
        try:
            mark_job(jid, "running")
            result = dispatch_one(job)
            mark_job(jid, "done", result=result)
            processed += 1
            print(f"   done: {json.dumps(result.get('per_platform', {}))}", flush=True)
        except Exception as e:
            print(f"   ! failed: {e}", flush=True)
            try:
                mark_job(jid, "failed", last_error=str(e))
            except Exception:
                pass
    return processed


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once")
    p_l = sub.add_parser("loop")
    p_l.add_argument("--interval", type=int, default=60)
    args = ap.parse_args()

    if args.cmd == "once":
        n = run_once()
        print(f"processed {n} jobs")
        return 0
    if args.cmd == "loop":
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"! loop error: {e}", flush=True)
            time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
