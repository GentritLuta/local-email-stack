"""Null out unusable first_name values on Aureon prospects.

Keeps a first_name only if it looks like a real first name:
  - 2 to 12 letters, alphabetic only
  - not a business-suffix word (homes, realty, broker, mgmt, team, ...)

Anything else gets nulled so the strict merge gate skips that prospect
rather than greeting them "Hey Apluspropertymgmt,".
"""
from __future__ import annotations
import json, sys, urllib.request, urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H_R = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
H_W = {**H_R, "Content-Type": "application/json", "Prefer": "return=minimal"}

BAD_SUBSTRINGS = (
    "home", "real", "broker", "agent", "team", "mgmt", "homes",
    "realty", "century", "remax", "exp", "kw", "indy", "metro",
    "wheeler", "dixon", "tucco", "kieper", "wilson", "puckett",
    "litten", "basker", "hutton", "whalen", "chain", "william",
    "atc", "family", "myagent",
)


def is_real_name(s: str | None) -> bool:
    if not s: return False
    s = s.strip()
    if not (3 <= len(s) <= 12): return False
    if not s.isalpha():         return False
    low = s.lower()
    if any(b in low for b in BAD_SUBSTRINGS): return False
    return True


def main() -> int:
    req = urllib.request.Request(
        f"{URL}/rest/v1/prospects?profile_slug=eq.aureon&select=id,email,first_name&limit=500",
        headers=H_R,
    )
    rows = json.loads(urllib.request.urlopen(req).read())
    n_nulled = 0
    n_kept = 0
    for r in rows:
        fn = r.get("first_name")
        if not fn:
            continue
        if is_real_name(fn):
            n_kept += 1
            continue
        payload = json.dumps({"first_name": None}).encode("utf-8")
        req = urllib.request.Request(
            f"{URL}/rest/v1/prospects?id=eq.{r['id']}",
            method="PATCH", data=payload, headers=H_W,
        )
        urllib.request.urlopen(req)
        n_nulled += 1
        print(f"  - {r['email']:50s} nulled fn={fn!r}")
    print()
    print(f"kept   : {n_kept}")
    print(f"nulled : {n_nulled}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
