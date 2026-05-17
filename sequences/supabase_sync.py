"""supabase_sync.py — push local state into Supabase + pull canonical state back.

Reads SUPABASE_URL + SUPABASE_ANON_KEY from supabase.env (gitignored), then:
  - upserts every profile in profiles/
  - upserts every variant in sequences/aureon-20-variants/variants.json (and any other
    variants.json under sequences/)
  - upserts every send-log row from warmup-state/*.resend.jsonl

After this runs once, the cloud is the canonical state and both PCs read from it.

Usage:
    py supabase_sync.py push                # upload local → Supabase
    py supabase_sync.py pull                # download Supabase → local files (for backup)
    py supabase_sync.py status              # show counts on both sides
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = REPO_ROOT / "profiles"
SEQ_DIR = REPO_ROOT / "sequences"
WARMUP_DIR = REPO_ROOT / "warmup-state"
ENV_FILE = REPO_ROOT / "sequences" / "supabase.env"


def load_env() -> tuple[str, str]:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    url = env.get("SUPABASE_URL") or os.environ.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_ANON_KEY") or os.environ.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        sys.exit(f"set SUPABASE_URL + SUPABASE_ANON_KEY in {ENV_FILE} (or env vars)")
    return url.rstrip("/"), key


def client(url: str, key: str) -> httpx.Client:
    return httpx.Client(
        base_url=f"{url}/rest/v1",
        timeout=20,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            # Tell PostgREST to upsert + return rows
            "Prefer": "resolution=merge-duplicates,return=representation",
        },
    )


# ─── PUSH ──────────────────────────────────────────────────────────────────

def push_profiles(c: httpx.Client) -> int:
    n = 0
    for p in PROFILES_DIR.glob("*.json"):
        if p.stem.endswith(".private"):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"  ! skip {p.name}: {e}")
            continue
        row = {
            "slug":   data["slug"],
            "name":   data["name"],
            "config": data,
            "active": bool(data.get("active", True)),
        }
        r = c.post("/profiles?on_conflict=slug", json=row)
        r.raise_for_status()
        print(f"  + profile  {data['slug']}")
        n += 1
    return n


def push_variants(c: httpx.Client) -> int:
    n = 0
    for vfile in SEQ_DIR.glob("*/variants.json"):
        try:
            data = json.loads(vfile.read_text(encoding="utf-8"))
        except Exception:
            continue
        # Infer profile_slug from file/path — for aureon-20-variants/ use 'aureon'
        profile_slug = data.get("profile_slug")
        if not profile_slug:
            stem = vfile.parent.name.split("-")[0]
            profile_slug = stem
        rows = []
        for v in data.get("variants", []):
            rows.append({
                "profile_slug": profile_slug,
                "n":       v["n"],
                "angle":   v.get("angle", ""),
                "subject": v["subject"],
                "body":    v["body"],
            })
        if not rows:
            continue
        r = c.post("/variants?on_conflict=profile_slug,n", json=rows)
        r.raise_for_status()
        print(f"  + variants {profile_slug} ({len(rows)})")
        n += len(rows)
    return n


def push_send_log(c: httpx.Client) -> int:
    n = 0
    for log in WARMUP_DIR.glob("*.resend.jsonl"):
        # Each line is a send record from resend-pool-send.py
        rows = []
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            rows.append({
                "step_n":        1,
                "persona_slug":  row.get("persona"),
                "from_addr":     "(unknown)",
                "to_addr":       row.get("to"),
                "subject":       "(historical send)",
                "resend_id":     row.get("resend_id"),
                "delivered":     bool(row.get("delivered")),
                "sent_at":       _fmt_ts(row.get("ts")),
                "error":         row.get("error"),
            })
        if not rows:
            continue
        # send_log has no natural unique key for these historical entries;
        # we just insert (duplicates possible on re-runs — that's fine for now).
        r = c.post("/send_log", json=rows)
        if r.status_code >= 400:
            print(f"  ! send_log push failed: {r.status_code} {r.text[:120]}")
            continue
        print(f"  + send_log {log.stem} ({len(rows)})")
        n += len(rows)
    return n


def _fmt_ts(ts):
    if ts is None:
        return None
    try:
        import datetime as dt
        return dt.datetime.fromtimestamp(float(ts)).isoformat()
    except Exception:
        return None


# ─── PULL ──────────────────────────────────────────────────────────────────

def pull_profiles(c: httpx.Client) -> int:
    r = c.get("/profiles?select=slug,name,config,active")
    r.raise_for_status()
    n = 0
    for p in r.json():
        slug = p["slug"]
        path = PROFILES_DIR / f"{slug}.json"
        path.write_text(json.dumps(p["config"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        n += 1
    return n


# ─── STATUS ────────────────────────────────────────────────────────────────

def status(c: httpx.Client) -> None:
    for table in ("profiles", "variants", "sequences", "sequence_steps",
                  "prospects", "runs", "send_log", "replies"):
        r = c.get(f"/{table}?select=count", headers={"Prefer": "count=exact"})
        cnt = r.headers.get("content-range", "?/?").split("/")[-1]
        print(f"  {table:18} {cnt}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["push", "pull", "status"])
    args = ap.parse_args()
    url, key = load_env()
    with client(url, key) as c:
        if args.cmd == "push":
            np = push_profiles(c)
            nv = push_variants(c)
            ns = push_send_log(c)
            print(f"\npushed: {np} profiles · {nv} variants · {ns} send_log rows")
        elif args.cmd == "pull":
            np = pull_profiles(c)
            print(f"pulled: {np} profiles")
        elif args.cmd == "status":
            status(c)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.HTTPStatusError as e:
        sys.stderr.write(f"{e.response.status_code}: {e.response.text[:400]}\n")
        sys.exit(1)
