# -*- coding: utf-8 -*-
"""deploy-mark-eting-seo.py — push the SEO-magnet copy change for mark-eting into
Supabase, so the live sequence-runner uses the new step-1 P.S. ({seo_ps}).

Two things have to land in the DB for the email-1 personalization to go live:

  1. The mark-eting variants (sequences/mark-eting-default/variants.json) must be
     upserted into the `variants` table. Step 1's body now ends in {seo_ps}.

  2. Step 1 runs a subject A/B (inline_subject vs the linked variant subject). The
     runner only splits the BODY when inline_subject, inline_body, variant subject
     AND variant body are all set (sequence-runner.py ~L712). If the live step-1
     row has inline_body populated (a copy of the old body, with the old P.S.),
     the inline side would keep the OLD P.S. So we set inline_body to the new
     body too, preserving inline_subject so the subject A/B is untouched.

Run this ONCE when Supabase egress is restored (the project is currently 402
restricted: exceed_egress_quota). It is idempotent and supports --dry.

    py scripts/deploy-mark-eting-seo.py --dry     # show what it would change
    py scripts/deploy-mark-eting-seo.py           # apply

This is a one-time deploy helper; the recurring research lives in
sequences/seo_research.py (scheduled task LES-seo-research).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

REPO = Path(__file__).resolve().parent.parent
ENV_FILE = REPO / "sequences" / "supabase.env"
VARIANTS = REPO / "sequences" / "mark-eting-default" / "variants.json"
SLUG = "mark-eting"
SEQ_SLUG = "mark-eting-default"

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
    step1 = next((v for v in variants if v.get("n") == 1), None)
    if not step1:
        sys.exit("could not find step 1 in variants.json")
    new_subject, new_body = step1["subject"], step1["body"]
    if "{seo_ps}" not in new_body:
        sys.exit("step-1 body does not contain {seo_ps} — refusing to deploy stale copy")

    url, key = load_env()
    with httpx.Client(base_url=f"{url}/rest/v1",
                      headers={"apikey": key, "Authorization": f"Bearer {key}",
                               "Content-Type": "application/json",
                               "Prefer": "resolution=merge-duplicates,return=representation"},
                      timeout=30) as c:
        # 1) upsert all mark-eting variants
        rows = [{"profile_slug": SLUG, "n": v["n"], "angle": v.get("angle", ""),
                 "subject": v["subject"], "body": v["body"]} for v in variants]
        print(f"[1/2] upsert {len(rows)} variants for {SLUG} (step 1 body ends: "
              f"...{new_body[-60:].strip()!r})")
        if not a.dry:
            r = c.post("/variants?on_conflict=profile_slug,n", json=rows)
            r.raise_for_status()
            print(f"      ok: {len(r.json())} rows")

        # 2) reconcile any inline_body overrides so every A/B side carries the new
        #    merge tags ({seo_ps} on step 1, {seo_rivals} on step 5). The runner
        #    only uses inline_body when it is set; otherwise it reads the variant.
        body_by_n = {v["n"]: v["body"] for v in variants}
        seqs = c.get("/sequences?select=*"); seqs.raise_for_status()
        mine = [s for s in seqs.json()
                if s.get("profile_slug") == SLUG or SEQ_SLUG in str(s.get("slug", ""))]
        if not mine:
            print("[2/2] no sequence row matched mark-eting — skip (runner uses variant body)")
            return 0
        reconciled = 0
        for s in mine:
            sid = s.get("id")
            st = c.get(f"/sequence_steps?sequence_id=eq.{sid}"
                       f"&select=id,step_n,inline_subject,inline_body,variant_id")
            st.raise_for_status()
            for row in st.json():
                n = row.get("step_n")
                want = body_by_n.get(n)
                if row.get("inline_body") and want and row["inline_body"] != want:
                    print(f"[2/2] seq {s.get('slug', sid)} step {n}: inline_body differs from "
                          f"variant — updating it (keeping inline_subject for any A/B)")
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
