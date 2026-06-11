"""Backfill missing company + first_name on Aureon prospects from email.

Safety-net pass over existing rows. The derivation logic now lives in the
single shared source of truth, sequences/name_derive.py, which lead_scrape.py
ALSO applies at scrape time — so as of the scrape-time quality gate this
backfill is largely a no-op (nameless leads no longer enter the pool). Kept
for one-off cleanup of legacy rows.

Run:
    py scripts/backfill-aureon-prospects.py
"""
from __future__ import annotations
import json, sys, urllib.request, urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV  = REPO / "sequences" / "supabase.env"

# Single source of truth for derivation (shared with lead_scrape.py).
sys.path.insert(0, str(REPO / "sequences"))
from name_derive import derive_first_name, derive_company  # noqa: E402

env = {}
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H_R = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
H_W = {**H_R, "Content-Type": "application/json", "Prefer": "return=minimal"}

PROFILE = "aureon"


def main() -> int:
    req = urllib.request.Request(
        f"{URL}/rest/v1/prospects?profile_slug=eq.{PROFILE}"
        f"&select=id,email,first_name,company&limit=2000",
        headers=H_R,
    )
    rows = json.loads(urllib.request.urlopen(req).read())
    n_co_patched = n_fn_patched = n_skipped = 0
    for r in rows:
        email = r["email"]
        patch = {}
        if not r.get("company"):
            co = derive_company(email)
            if co:
                patch["company"] = co
        if not r.get("first_name"):
            fn = derive_first_name(email, r.get("company") or patch.get("company"))
            if fn:
                patch["first_name"] = fn
        if not patch:
            n_skipped += 1
            continue
        payload = json.dumps(patch).encode("utf-8")
        req = urllib.request.Request(
            f"{URL}/rest/v1/prospects?id=eq.{r['id']}",
            method="PATCH", data=payload, headers=H_W,
        )
        try:
            urllib.request.urlopen(req)
            if "company" in patch:    n_co_patched += 1
            if "first_name" in patch: n_fn_patched += 1
            print(f"  + {email:50s} -> {patch}")
        except urllib.error.HTTPError as e:
            print(f"  ! {email:50s} HTTP {e.code}: {e.read().decode()[:200]}")
    print()
    print(f"company patched   : {n_co_patched}")
    print(f"first_name patched: {n_fn_patched}")
    print(f"skipped (no fix)  : {n_skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
