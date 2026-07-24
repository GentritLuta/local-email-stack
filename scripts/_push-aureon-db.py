# -*- coding: utf-8 -*-
"""_push-aureon-db.py — surgical aureon-only copy push (variants ONLY).

Upserts the 7 aureon variants from sequences/aureon-default/variants.json into
the variants table (on_conflict profile_slug,n). Deliberately does NOT touch the
profiles row: aureon is a LIVE profile with warm relay + warmup state, and
overwriting its config from the repo file could clobber live settings. The
runner only needs the variants table for new copy (it reads
sequence_steps -> variants(subject,body)).

Run wire-sequence-steps.py aureon afterward to relink sequence_steps delays.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import httpx

REPO = Path(__file__).resolve().parent.parent
SLUG = "aureon"
VF = REPO / "sequences" / f"{SLUG}-default" / "variants.json"

env = {}
for ln in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.split("=", 1); env[k.strip()] = v.strip()
U = env["SUPABASE_URL"].rstrip("/") + "/rest/v1"
K = env["SUPABASE_ANON_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Content-Type": "application/json"}

data = json.loads(VF.read_text(encoding="utf-8"))
assert data["profile_slug"] == SLUG, "profile_slug mismatch"

with httpx.Client(base_url=U, headers=H, timeout=30) as c:
    # Sequence row must already exist for a live profile; create only if missing.
    existing = c.get(f"/sequences?profile_slug=eq.{SLUG}&select=id,slug").json()
    if existing:
        print(f"sequence exists: {existing[0]['slug']} ({existing[0]['id'][:8]})")
    else:
        seq_row = {"profile_slug": SLUG, "slug": f"{SLUG}-default", "name": data["name"],
                   "description": data.get("voice_notes", "")[:200],
                   "stop_on_reply": True, "stop_on_bounce": True, "active": True}
        r = c.post("/sequences", json=seq_row, headers={**H, "Prefer": "return=representation"})
        r.raise_for_status()
        print(f"created sequence {SLUG}-default ({r.json()[0]['id'][:8]})")

    rows = [{"profile_slug": SLUG, "n": v["n"], "angle": v.get("angle", ""),
             "subject": v["subject"], "body": v["body"]} for v in data["variants"]]
    r = c.post("/variants?on_conflict=profile_slug,n", json=rows,
               headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"})
    r.raise_for_status()
    print(f"upserted {len(rows)} aureon variants ({r.status_code})")

print("done. now run: py scripts/wire-sequence-steps.py aureon")
