"""wire-sequence-steps.py — sync sequence_steps rows on Supabase from each
client's variants.json (delay_days per variant) + the variants table.

For each profile_slug:
  1. Read its variants.json. Note each variant's n and delay_days.
  2. Find the sequence row (active=true, profile_slug=...).
  3. For each n in the variants, upsert a sequence_steps row:
       sequence_id      = <found>
       step_n           = n
       variant_id       = <variant row id with profile_slug,n>
       delay_days       = <from variants.json>
       inline_subject   = NULL   (variant table is source of truth)
       inline_body      = NULL

Idempotent. Safe to re-run after editing variants.json.

Usage:
    py scripts/wire-sequence-steps.py aureon           # one profile
    py scripts/wire-sequence-steps.py --all            # every active sequence
"""
from __future__ import annotations
import argparse
import json
import re
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
SEQ_DIR = REPO / "sequences"
SUPA_ENV = REPO / "sequences" / "supabase.env"


def load_supa() -> tuple[str, str]:
    env = {}
    for line in SUPA_ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env["SUPABASE_URL"].rstrip("/") + "/rest/v1", env["SUPABASE_ANON_KEY"]


def wire_profile(c: httpx.Client, profile_slug: str) -> int:
    vf = SEQ_DIR / f"{profile_slug}-default" / "variants.json"
    if not vf.exists():
        print(f"  ! no variants.json for {profile_slug}")
        return 0
    data = json.loads(vf.read_text(encoding="utf-8"))
    variants = data.get("variants") or []
    if not variants:
        return 0

    # Find the sequence row
    seq_resp = c.get(f"/sequences?profile_slug=eq.{profile_slug}&active=eq.true&select=id,slug")
    seq_resp.raise_for_status()
    seqs = seq_resp.json()
    if not seqs:
        print(f"  ! no active sequence for profile {profile_slug}")
        return 0
    seq = seqs[0]
    print(f"  + sequence {seq['slug']} ({seq['id'][:8]}...)")

    written = 0
    for v in variants:
        n = v["n"]
        delay_days = int(v.get("delay_days", 0))

        # Find the variant row id
        vr = c.get(f"/variants?profile_slug=eq.{profile_slug}&n=eq.{n}&select=id")
        vr.raise_for_status()
        rows = vr.json()
        if not rows:
            print(f"    ! variant n={n} not in DB (push variants first)")
            continue
        variant_id = rows[0]["id"]

        # Does step_n already exist for this sequence?
        ex = c.get(f"/sequence_steps?sequence_id=eq.{seq['id']}&step_n=eq.{n}&select=id")
        ex.raise_for_status()
        existing = ex.json()

        body = {
            "sequence_id":    seq["id"],
            "step_n":         n,
            "variant_id":     variant_id,
            "delay_days":     delay_days,
            "inline_subject": None,
            "inline_body":    None,
        }
        if existing:
            r = c.patch(f"/sequence_steps?id=eq.{existing[0]['id']}", json=body,
                        headers={"Prefer": "return=minimal"})
            verb = "updated"
        else:
            r = c.post("/sequence_steps", json=body,
                       headers={"Prefer": "return=minimal"})
            verb = "inserted"
        if r.status_code in (200, 201, 204):
            print(f"    {verb:8s} step_n={n}  delay_days={delay_days:2d}  variant_id={variant_id[:8]}...")
            written += 1
        else:
            print(f"    ! {verb} step_n={n} failed: {r.status_code} {r.text[:200]}")

    return written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile_slug", nargs="?")
    ap.add_argument("--all", action="store_true",
                    help="Wire every active sequence on Supabase")
    args = ap.parse_args()

    url, key = load_supa()
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}

    with httpx.Client(base_url=url, headers=headers, timeout=20) as c:
        if args.all:
            r = c.get("/sequences?active=eq.true&select=profile_slug")
            r.raise_for_status()
            slugs = sorted({row["profile_slug"] for row in r.json()})
            total = 0
            for slug in slugs:
                print(f"\n=== {slug} ===")
                total += wire_profile(c, slug)
            print(f"\nwrote {total} sequence_steps rows")
        elif args.profile_slug:
            wire_profile(c, args.profile_slug)
        else:
            ap.print_help()
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
