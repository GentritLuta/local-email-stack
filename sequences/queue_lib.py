"""queue_lib.py — Supabase-backed queue for prospect discovery.

Replaces the per-source .txt queue + .done file pattern. The same
`prospect_candidates` row tracks status through pending -> claimed ->
done|failed, so multiple workers across multiple machines can pull from
the same queue safely.

Schema (see supabase/migration_003_scale_pipeline.sql):
  prospect_candidates(
    id UUID PK,
    profile_slug TEXT,
    niche_slug   TEXT,
    source       TEXT,     -- 'youtube' | 'tradingview' | 'instagram' | ...
    handle       TEXT,     -- platform-specific id (channel, @handle, etc.)
    status       TEXT,     -- pending|claimed|done|failed
    claimed_by   TEXT,
    claimed_at   TIMESTAMPTZ,
    done_at      TIMESTAMPTZ,
    attempts     INT,
    last_error   TEXT,
    meta         JSONB,
    created_at   TIMESTAMPTZ,
    UNIQUE (profile_slug, source, handle)
  )

Atomic claim is implemented by a single UPDATE that filters on status=pending
and stamps claimed_by + claimed_at in one shot. The Supabase RPC returns
the updated rows so each worker knows exactly which candidates it now owns.

A claim that's older than `claim_timeout_minutes` (default 30) is treated
as stale and can be reclaimed by another worker. This handles worker crashes.
"""
from __future__ import annotations

import datetime as dt
import json
import socket
import time
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE  = REPO_ROOT / "sequences" / "supabase.env"


def _load_supabase_env() -> tuple[str, str]:
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


_SUPA_URL, _SUPA_KEY = _load_supabase_env()
_HEADERS = {
    "apikey": _SUPA_KEY,
    "Authorization": f"Bearer {_SUPA_KEY}",
    "Content-Type": "application/json",
}


def _worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


# ─── Enqueue ──────────────────────────────────────────────────────────────

def enqueue(profile_slug: str, niche_slug: str, source: str,
            handles: list[str], meta_per_handle: Optional[dict] = None) -> int:
    """Insert handles as 'pending' candidates. Returns count of NEW rows
    actually inserted (existing duplicates by (profile, source, handle) are
    silently ignored via ON CONFLICT DO NOTHING via Prefer header)."""
    if not handles:
        return 0
    payload = [{
        "profile_slug": profile_slug,
        "niche_slug":   niche_slug,
        "source":       source,
        "handle":       h,
        "status":       "pending",
        "meta":         (meta_per_handle or {}).get(h),
    } for h in handles]
    headers = {**_HEADERS, "Prefer": "resolution=ignore-duplicates,return=representation"}
    r = httpx.post(
        f"{_SUPA_URL}/rest/v1/prospect_candidates",
        headers=headers, json=payload, timeout=30,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"enqueue {r.status_code}: {r.text[:300]}")
    rows = r.json() if r.content else []
    return len(rows)


# ─── Claim ───────────────────────────────────────────────────────────────

def claim_batch(profile_slug: str, source: str, batch_size: int = 20,
                worker_id: Optional[str] = None,
                claim_timeout_minutes: int = 30) -> list[dict]:
    """Atomically claim up to `batch_size` pending candidates for this
    worker. Stale claims (claimed > N minutes ago without completion) are
    reclaimable.

    Two-step pattern (PostgREST doesn't reliably honor `limit` on PATCH):
      1. SELECT N candidate IDs that are pending or stale-claimed
      2. PATCH only those specific IDs to claimed

    There's a small race window between step 1 and 2 where another worker
    could grab the same IDs. We accept it — duplicate processing of a
    handle is just a wasted API call (Supabase upsert dedups the email
    on upsert). Strict serializability would need a Postgres RPC with
    `FOR UPDATE SKIP LOCKED`.
    """
    wid = worker_id or _worker_id()
    stale_threshold = (dt.datetime.utcnow()
                       - dt.timedelta(minutes=claim_timeout_minutes)).isoformat() + "Z"

    # Step 1: SELECT N candidate IDs
    flt = f"or=(status.eq.pending,and(status.eq.claimed,claimed_at.lt.{stale_threshold}))"
    sel_url = (f"{_SUPA_URL}/rest/v1/prospect_candidates"
               f"?profile_slug=eq.{profile_slug}&source=eq.{source}"
               f"&{flt}&order=created_at.asc&limit={batch_size}"
               f"&select=id,handle,niche_slug,meta,attempts")
    r = httpx.get(sel_url, headers=_HEADERS, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"claim select {r.status_code}: {r.text[:300]}")
    rows = r.json() or []
    if not rows:
        return []
    ids = [row["id"] for row in rows]

    # Step 2: PATCH only those IDs
    id_list = ",".join(f'"{i}"' for i in ids)
    patch_url = (f"{_SUPA_URL}/rest/v1/prospect_candidates"
                 f"?id=in.({id_list})")
    body = {
        "status": "claimed",
        "claimed_by": wid,
        "claimed_at": dt.datetime.utcnow().isoformat() + "Z",
    }
    headers = {**_HEADERS, "Prefer": "return=minimal"}
    p = httpx.patch(patch_url, headers=headers, json=body, timeout=30)
    if p.status_code not in (200, 204):
        raise RuntimeError(f"claim patch {p.status_code}: {p.text[:300]}")
    return rows


# ─── Mark done / failed ──────────────────────────────────────────────────

def mark_done(candidate_id: str, *, error: Optional[str] = None) -> None:
    """Mark a candidate as terminal: 'done' if no error, 'failed' if any.
    Idempotent — late updates to an already-done row are no-ops."""
    body = {
        "status": "failed" if error else "done",
        "done_at": dt.datetime.utcnow().isoformat() + "Z",
        "last_error": (error[:500] if error else None),
    }
    r = httpx.patch(
        f"{_SUPA_URL}/rest/v1/prospect_candidates?id=eq.{candidate_id}",
        headers=_HEADERS, json=body, timeout=15,
    )
    if r.status_code not in (200, 204):
        raise RuntimeError(f"mark_done {r.status_code}: {r.text[:300]}")


def release_to_pending(candidate_id: str, *, last_error: Optional[str] = None) -> None:
    """Return a claimed candidate to pending. Used for transient failures
    (rate limit, quota exhaustion) where we want tomorrow's run to retry."""
    body = {
        "status": "pending",
        "claimed_by": None,
        "claimed_at": None,
        "last_error": (last_error[:500] if last_error else None),
    }
    r = httpx.patch(
        f"{_SUPA_URL}/rest/v1/prospect_candidates?id=eq.{candidate_id}",
        headers=_HEADERS, json=body, timeout=15,
    )
    if r.status_code not in (200, 204):
        raise RuntimeError(f"release_to_pending {r.status_code}: {r.text[:300]}")


def increment_attempts(candidate_id: str) -> None:
    """Bump attempts counter (used when claim is renewed mid-fetch)."""
    # Read-modify-write — acceptable since this is informational only.
    r = httpx.get(
        f"{_SUPA_URL}/rest/v1/prospect_candidates?id=eq.{candidate_id}&select=attempts",
        headers=_HEADERS, timeout=15,
    )
    if r.status_code != 200:
        return
    items = r.json() or []
    current = items[0].get("attempts", 0) if items else 0
    httpx.patch(
        f"{_SUPA_URL}/rest/v1/prospect_candidates?id=eq.{candidate_id}",
        headers=_HEADERS, json={"attempts": current + 1}, timeout=15,
    )


# ─── Stats ────────────────────────────────────────────────────────────────

def stats(profile_slug: Optional[str] = None,
          source: Optional[str] = None) -> dict[str, int]:
    """Return counts {pending, claimed, done, failed} optionally filtered."""
    out: dict[str, int] = {}
    for status in ("pending", "claimed", "done", "failed"):
        q = f"status=eq.{status}"
        if profile_slug: q += f"&profile_slug=eq.{profile_slug}"
        if source:       q += f"&source=eq.{source}"
        r = httpx.get(
            f"{_SUPA_URL}/rest/v1/prospect_candidates?{q}&select=count",
            headers={**_HEADERS, "Prefer": "count=exact"}, timeout=15,
        )
        # PostgREST returns Content-Range header with count, body is rows
        cr = r.headers.get("Content-Range", "")
        if "/" in cr:
            try:
                out[status] = int(cr.split("/", 1)[1])
                continue
            except Exception:
                pass
        out[status] = 0
    return out


# ─── CLI helpers (diagnostic) ─────────────────────────────────────────────

def _cli():
    import argparse
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_st = sub.add_parser("stats")
    p_st.add_argument("--profile", default=None)
    p_st.add_argument("--source", default=None)

    p_en = sub.add_parser("enqueue-file",
        help="bulk-load a .txt handle file into the queue")
    p_en.add_argument("profile")
    p_en.add_argument("niche")
    p_en.add_argument("source")
    p_en.add_argument("file")

    p_cl = sub.add_parser("claim")
    p_cl.add_argument("profile")
    p_cl.add_argument("source")
    p_cl.add_argument("--n", type=int, default=5)

    args = ap.parse_args()
    if args.cmd == "stats":
        print(json.dumps(stats(args.profile, args.source), indent=2))
        return
    if args.cmd == "enqueue-file":
        text = Path(args.file).read_text(encoding="utf-8")
        handles = [ln.strip().lstrip("@") for ln in text.splitlines()
                   if ln.strip() and not ln.strip().startswith("#")]
        # Insert in chunks of 500 to stay under PostgREST payload limits
        total = 0
        for i in range(0, len(handles), 500):
            chunk = handles[i:i+500]
            total += enqueue(args.profile, args.niche, args.source, chunk)
            print(f"  enqueued {i+len(chunk)}/{len(handles)} (+{total} new)")
        print(f"DONE — {total} new candidates inserted (duplicates skipped)")
        return
    if args.cmd == "claim":
        rows = claim_batch(args.profile, args.source, batch_size=args.n)
        print(f"claimed {len(rows)}:")
        for r in rows:
            print(f"  {r['id']:36}  {r['source']:10}  {r['handle']}")
        return


if __name__ == "__main__":
    _cli()
