# -*- coding: utf-8 -*-
"""_push-energ-db.py — surgical energ-only DB push (NOT the global sync).

Creates the energ sequence row (active) and upserts the 7 energ variants from
sequences/energ-default/variants.json into the variants table. Then nothing
sends: energ has 0 leads and warmup hasn't started. Run wire-sequence-steps
afterward to link sequence_steps -> variant ids.

Deliberately energ-only so we don't re-push (and risk overwriting) every other
client's live copy the way supabase_sync.py push would.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import httpx

REPO = Path(__file__).resolve().parent.parent
SLUG = "energ"
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

prof = json.loads((REPO / "profiles" / f"{SLUG}.json").read_text(encoding="utf-8"))

with httpx.Client(base_url=U, headers=H, timeout=30) as c:
    # 0. Profile row must exist first (sequences.profile_slug FK -> profiles.slug)
    prow = {"slug": prof["slug"], "name": prof["name"], "config": prof,
            "active": bool(prof.get("active", True))}
    r = c.post("/profiles?on_conflict=slug", json=prow,
               headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"})
    r.raise_for_status()
    print(f"upserted profile {SLUG} ({r.status_code})")

    # 1. Sequence row (upsert on slug if your table has a unique on slug; else check first)
    existing = c.get(f"/sequences?profile_slug=eq.{SLUG}&select=id,slug").json()
    if existing:
        seq_id = existing[0]["id"]
        print(f"sequence exists: {existing[0]['slug']} ({seq_id[:8]})")
    else:
        seq_row = {
            "profile_slug": SLUG,
            "slug": f"{SLUG}-default",
            "name": data["name"],
            "description": data.get("voice_notes", "")[:200],
            "stop_on_reply": True,
            "stop_on_bounce": True,
            "active": True,
        }
        r = c.post("/sequences", json=seq_row, headers={**H, "Prefer": "return=representation"})
        r.raise_for_status()
        seq_id = r.json()[0]["id"]
        print(f"created sequence {SLUG}-default ({seq_id[:8]})")

    # 2. Variants upsert (on_conflict profile_slug,n)
    rows = [{"profile_slug": SLUG, "n": v["n"], "angle": v.get("angle", ""),
             "subject": v["subject"], "body": v["body"]} for v in data["variants"]]
    r = c.post("/variants?on_conflict=profile_slug,n", json=rows,
               headers={**H, "Prefer": "resolution=merge-duplicates,return=minimal"})
    r.raise_for_status()
    print(f"upserted {len(rows)} energ variants ({r.status_code})")

print("done. now run: py scripts/wire-sequence-steps.py energ")
