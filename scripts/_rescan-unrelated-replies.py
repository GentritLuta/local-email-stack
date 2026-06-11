# -*- coding: utf-8 -*-
"""_rescan-unrelated-replies.py — one-off: re-check existing replies.class='unrelated'
rows. If the sender is a known prospect (and not laso.finance/own-infra/noise), upgrade
the row to class='reply' so previously-missed prospect replies surface.

Mirrors the imap-poll.py upgrade guard exactly (EXCLUDE_FROM + NOISE_SUBJ + is_known_prospect).
Run with --apply to write; default is dry-run (prints what it would change).
"""
from __future__ import annotations
import sys, re, json
from pathlib import Path
import httpx

REPO = Path(__file__).resolve().parent.parent
env = {}
for ln in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.split("=", 1); env[k.strip()] = v.strip()
U = env["SUPABASE_URL"].rstrip("/") + "/rest/v1"
K = env["SUPABASE_ANON_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K, "Content-Type": "application/json"}

# Same guards as imap-poll.py
EXCLUDE_FROM = re.compile(r"@([\w.-]*(?:aureonglobal|diraya)[\w.-]*|laso\.finance)$", re.I)
NOISE_SUBJ = re.compile(r"\b(invoice|settlement|receipt|refund|retoure|chargeback|"
                        r"card on file|\bucof\b|account statement|past due|"
                        r"verification code|reset your password|confirm your email|"
                        r"order\s*#|return\s*#)\b", re.I)

APPLY = "--apply" in sys.argv

with httpx.Client(base_url=U, headers=H, timeout=30) as c:
    rows = c.get("/replies", params={"class": "eq.unrelated",
                                     "select": "id,from_addr,subject,body_snippet", "limit": "2000"}).json()
    print(f"scanning {len(rows)} 'unrelated' rows...")
    # build known-prospect set once
    prospects = set()
    off = 0
    while True:
        batch = c.get("/prospects", params={"select": "email", "limit": "1000", "offset": str(off)}).json()
        if not batch: break
        prospects.update((p["email"] or "").lower() for p in batch)
        off += 1000
        if len(batch) < 1000: break
    print(f"known prospects: {len(prospects)}")

    upgrades = []
    for r in rows:
        fa = (r.get("from_addr") or "").lower()
        subj = r.get("subject") or ""
        if not fa or EXCLUDE_FROM.search(fa) or NOISE_SUBJ.search(subj):
            continue
        if fa in prospects:
            upgrades.append(r)

    print(f"\n{'WOULD UPGRADE' if not APPLY else 'UPGRADING'} {len(upgrades)} -> class=reply:")
    for r in upgrades:
        sn = (r.get("body_snippet") or "").replace("\n", " ")[:60]
        print(f"  {r['from_addr'][:34]:<34} | {(r.get('subject') or '')[:30]:<30} | {sn}")

    if APPLY and upgrades:
        for r in upgrades:
            c.patch(f"/replies?id=eq.{r['id']}", json={"class": "reply"},
                    headers={**H, "Prefer": "return=minimal"})
        print(f"\napplied: {len(upgrades)} rows upgraded to class=reply")
    elif not APPLY:
        print("\n(dry run — re-run with --apply to write)")
