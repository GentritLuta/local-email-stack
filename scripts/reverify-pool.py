"""reverify-pool.py — local (no-SMTP) re-verification sweep of a brand's pool.

Re-runs lead_verify.verify(do_smtp_probe=False) over every verified=true prospect
and flips to verified=false the ones that now fail the LOCAL checks: junk/role
local-part (out@, officer@, website@, businesses@, support@ ...), no-MX domain,
disposable, or placeholder. This is what catches the creator-scrape junk that was
driving dorian's 25% bounce, without needing port 25.

It cannot detect a dead mailbox on a live, MX-valid domain (that needs an SMTP
probe) — but it removes the whole junk-local class, which was the bulk of the
bounces.

Usage:
  py scripts/reverify-pool.py --dry
  py scripts/reverify-pool.py                          # dorian,energ,algoalpha
  py scripts/reverify-pool.py --profiles aureon,lk-advertising
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
import lead_verify as lv  # noqa: E402

ENV = REPO / "sequences" / "supabase.env"


def env():
    e = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1); e[k.strip()] = v.strip().strip('"').strip("'")
    return e


E = env()
URL = E.get("SUPABASE_URL")
KEY = E.get("SUPABASE_SERVICE_ROLE_KEY") or E.get("SUPABASE_SERVICE_KEY") or E.get("SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}


def get(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H), timeout=40).read())


def patch(path, body):
    r = urllib.request.Request(f"{URL}/rest/v1/{path}", data=json.dumps(body).encode(),
                               headers={**H, "Prefer": "return=minimal"}, method="PATCH")
    return urllib.request.urlopen(r, timeout=40).status


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", default="dorian,energ,algoalpha")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    for slug in [s.strip() for s in args.profiles.split(",") if s.strip()]:
        rows, off = [], 0
        while True:
            b = get(f"prospects?profile_slug=eq.{slug}&verified=is.true&select=id,email&order=id&limit=1000&offset={off}")
            rows += b
            if len(b) < 1000:
                break
            off += 1000
        fails, reasons = [], Counter()
        for p in rows:
            r = lv.verify(p["email"], do_smtp_probe=False, do_catchall_probe=False)
            if not r.verified:
                fails.append((p["id"], r.method))
                reasons[r.method] += 1
        print(f"\n{slug}: {len(rows)} verified prospects -> {len(fails)} now FAIL local re-verify")
        for m, n in reasons.most_common():
            print(f"    {m:14} {n}")
        if args.dry or not fails:
            if args.dry and fails:
                print("    [DRY] would set verified=false on those.")
            continue
        ids = [pid for pid, _ in fails]
        done = 0
        for i in range(0, len(ids), 50):
            chunk = ids[i:i + 50]
            st = patch(f"prospects?id=in.({','.join(chunk)})",
                       {"verified": False, "verification_method": "reverify_local_fail"})
            if st in (200, 204):
                done += len(chunk)
        print(f"    suppressed {done} (verified=false).")


if __name__ == "__main__":
    main()
