"""Remove editorial / non-creator AlgoAlpha leads.

AlgoAlpha targets crypto and trading content creators (YouTube,
TradingView authors, Substack writers). News outlets, exchanges, and
software companies are out of scope. This script:

  1. Marks all non-creator prospects unsubscribed=true + verified=false
     so the enqueue and strict gate both ignore them forever.
  2. Cancels any queued runs they have on the AlgoAlpha sequence so no
     follow-up emails go out.

Identification:
  - HARD-REMOVE domains:   editorial / exchanges / services / junk
  - GMAIL allow-list:      explicit creator handles
  - Default for unknown:   keep (assume creator brand domain)

Run:
    py scripts/purge-algoalpha-non-creators.py
"""
from __future__ import annotations
import json, sys, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV  = REPO / "sequences" / "supabase.env"

env = {}
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H_R = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
H_W = {**H_R, "Content-Type": "application/json", "Prefer": "return=minimal"}

# Editorial outlets, exchanges, software vendors, junk — NOT creators.
HARD_REMOVE_DOMAINS = {
    "decrypt.co", "decryptmedia.com",       # Decrypt — news
    "coindesk.com",                          # CoinDesk — news
    "cointelegraph.com",                     # Cointelegraph — news
    "cryptoslate.com",                       # CryptoSlate — news
    "tokeninsight.com",                      # research firm
    "consensys.net",                         # MetaMask parent, not a creator
    "bybit-tr.com",                          # exchange
    "quantum-algo.com",                      # trading service / competitor
    "example.com", "4x.png", "0.0.3",        # junk / placeholders
}

# Gmail addresses that ARE confirmed creators (allow-list).
GMAIL_CREATORS = {
    "sponsordatadash@gmail.com",   # DataDash YouTube channel
    "jrnycrypto@gmail.com",         # JRNY Crypto YouTube channel
    "conorkennyyt@gmail.com",       # Conor Kenny YouTube channel
}


def main() -> int:
    req = urllib.request.Request(
        f"{URL}/rest/v1/prospects?profile_slug=eq.algoalpha&select=id,email,unsubscribed&limit=500",
        headers=H_R,
    )
    rows = json.loads(urllib.request.urlopen(req).read())

    # Resolve AlgoAlpha sequence id once (need it to filter runs to cancel)
    req = urllib.request.Request(
        f"{URL}/rest/v1/sequences?profile_slug=eq.algoalpha&select=id",
        headers=H_R,
    )
    SID = json.loads(urllib.request.urlopen(req).read())[0]["id"]

    removed = kept = already_unsub = 0
    runs_cancelled = 0
    for r in rows:
        email = r["email"]
        domain = email.split("@")[-1].lower()
        is_creator = True
        if domain in HARD_REMOVE_DOMAINS:
            is_creator = False
        elif domain == "gmail.com" and email.lower() not in GMAIL_CREATORS:
            # Unknown gmail = treat conservatively. Only allow-listed gmails stay.
            is_creator = False
        elif domain in {"protonmail.com", "outlook.com", "yahoo.com", "aol.com"}:
            is_creator = False  # Free-mail without allow-list entry = out
        if is_creator:
            kept += 1
            continue
        if r.get("unsubscribed"):
            already_unsub += 1
            continue
        # Mark unsubscribed + unverified
        patch = {
            "unsubscribed": True,
            "verified": False,
            "verification_method": "auto_purge_non_creator",
        }
        req = urllib.request.Request(
            f"{URL}/rest/v1/prospects?id=eq.{r['id']}",
            method="PATCH",
            data=json.dumps(patch).encode(),
            headers=H_W,
        )
        urllib.request.urlopen(req)
        removed += 1
        print(f"  X {email}")

        # Cancel any queued runs for this prospect on the AlgoAlpha sequence
        req = urllib.request.Request(
            f"{URL}/rest/v1/runs?sequence_id=eq.{SID}&prospect_id=eq.{r['id']}&status=eq.queued",
            method="PATCH",
            data=json.dumps({"status": "cancelled"}).encode(),
            headers=H_W,
        )
        urllib.request.urlopen(req)
        runs_cancelled += 1

    print()
    print(f"removed (marked unsub)  : {removed}")
    print(f"already unsub (skipped) : {already_unsub}")
    print(f"queued runs cancelled   : {runs_cancelled}")
    print(f"kept as creator         : {kept}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
