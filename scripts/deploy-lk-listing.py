# -*- coding: utf-8 -*-
"""deploy-lk-listing.py — push LK Advertising's listing content-plan copy into
Supabase so the live sequence-runner uses the new step-2 P.S. ({listing_ps}).

What has to land in the DB for the give-first content-plan offer to go live:

  1. The lk-advertising variants (sequences/lk-advertising-default/variants.json)
     upserted into the `variants` table. Step 2's body now ends with {listing_ps}.

  2. Any inline_body override on the CHANGED step must carry the new tag too
     (the runner uses inline_body when it is set, else the variant body).

A/B SAFETY (the reason this is a separate script from deploy-mark-eting-seo.py):
LK's STEP 1 runs a live A/B whose B-side is an inline_body override in the DB. We
therefore NEVER reconcile step 1 here — doing so would overwrite the B-side and
destroy the test. This script only ever touches steps whose variant body actually
contains {listing_ps} (i.e. step 2), and hard-skips step 1 as a belt-and-braces
guard. Editing step 1 is a deliberate, separate decision for the operator.

Idempotent, supports --dry.
    py scripts/deploy-lk-listing.py --dry     # show what it would change
    py scripts/deploy-lk-listing.py           # apply

Recurring research lives in sequences/listing_research.py (schedule it as
LES-listing-research). The fulfiller (LES-fulfill-magnets) already delivers the
plan on a "plan"/"teardown" reply via the updated magnet spec.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / "sequences" / "supabase.env"
VARIANTS = REPO / "sequences" / "lk-advertising-default" / "variants.json"
SLUG = "lk-advertising"
SEQ_SLUG = "lk-advertising-default"
TAG = "{listing_ps}"
AB_PROTECTED_STEPS = {1}   # step 1 runs a live A/B (inline B-side) — never touch it

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load_env() -> tuple[str, str]:
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env["SUPABASE_URL"].rstrip("/"), env["SUPABASE_ANON_KEY"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="show changes, do not write")
    a = ap.parse_args()

    data = json.loads(VARIANTS.read_text(encoding="utf-8"))
    variants = data.get("variants", [])
    changed = [v for v in variants if TAG in (v.get("body") or "")]
    if not changed:
        sys.exit(f"no variant contains {TAG} — refusing to deploy stale copy")
    changed_ns = {v["n"] for v in changed}
    if changed_ns & AB_PROTECTED_STEPS:
        sys.exit(f"{TAG} is on an A/B-protected step {changed_ns & AB_PROTECTED_STEPS}; "
                 "review the step-1 A/B by hand before deploying")
    print(f"steps carrying {TAG}: {sorted(changed_ns)}")

    url, key = load_env()
    with httpx.Client(base_url=f"{url}/rest/v1",
                      headers={"apikey": key, "Authorization": f"Bearer {key}",
                               "Content-Type": "application/json",
                               "Prefer": "resolution=merge-duplicates,return=representation"},
                      timeout=30) as c:
        # 1) upsert all lk variants (refreshes the linked-variant bodies; step 1's
        #    A-side variant is unchanged, so the A/B is unaffected)
        rows = [{"profile_slug": SLUG, "n": v["n"], "angle": v.get("angle", ""),
                 "subject": v["subject"], "body": v["body"]} for v in variants]
        print(f"[1/2] upsert {len(rows)} variants for {SLUG}")
        if not a.dry:
            r = c.post("/variants?on_conflict=profile_slug,n", json=rows)
            r.raise_for_status()
            print(f"      ok: {len(r.json())} rows")

        # 2) reconcile inline_body ONLY for the changed, non-A/B steps
        body_by_n = {v["n"]: v["body"] for v in changed if v["n"] not in AB_PROTECTED_STEPS}
        seqs = c.get("/sequences?select=*"); seqs.raise_for_status()
        mine = [s for s in seqs.json()
                if s.get("profile_slug") == SLUG or SEQ_SLUG in str(s.get("slug", ""))]
        if not mine:
            print("[2/2] no sequence row matched lk — skip (runner uses variant body)")
            return 0
        reconciled = 0
        for s in mine:
            sid = s.get("id")
            st = c.get(f"/sequence_steps?sequence_id=eq.{sid}"
                       f"&select=id,step_n,inline_subject,inline_body,variant_id")
            st.raise_for_status()
            for row in st.json():
                n = row.get("step_n")
                if n in AB_PROTECTED_STEPS:
                    continue
                want = body_by_n.get(n)
                if row.get("inline_body") and want and row["inline_body"] != want:
                    print(f"[2/2] seq {s.get('slug', sid)} step {n}: updating inline_body "
                          f"to carry {TAG} (inline_subject preserved)")
                    if not a.dry:
                        up = c.patch(f"/sequence_steps?id=eq.{row['id']}",
                                     json={"inline_body": want})
                        up.raise_for_status()
                    reconciled += 1
        print(f"[2/2] inline_body rows reconciled: {reconciled}"
              + ("  (none had an inline_body override — runner uses variant bodies)"
                 if reconciled == 0 else ""))
    print("\ndone." + ("  [DRY]" if a.dry else ""))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except httpx.HTTPStatusError as e:
        sys.stderr.write(f"{e.response.status_code}: {e.response.text[:300]}\n")
        sys.exit(1)
