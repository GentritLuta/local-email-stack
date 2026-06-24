"""_dorian-live-stats.py — read-only snapshot of Dorian / Mercury Scales live numbers.

Pulls prospect pool health, send_log funnel (sent/delivered/open/click/reply/bounce),
source breakdown, and run/step distribution straight from Supabase. No writes.
"""
from __future__ import annotations
import json
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV = REPO / "sequences" / "supabase.env"

env = {}
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]
KEY = env["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "User-Agent": "les-stats/1.0"}


def fetch(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def main() -> None:
    print("=" * 64)
    print("DORIAN / MERCURY SCALES — LIVE SNAPSHOT")
    print("=" * 64)

    # 1. Prospect pool
    rows = fetch("prospects?profile_slug=eq.dorian&select=*&limit=5000")
    if rows:
        print("  (prospect columns:", ", ".join(sorted(rows[0].keys())), ")")
    print(f"\nPOOL: {len(rows)} total prospects")
    print(f"  verified            : {sum(1 for r in rows if r.get('verified'))}")
    print(f"  unsubscribed        : {sum(1 for r in rows if r.get('unsubscribed'))}")
    print(f"  bounced flag        : {sum(1 for r in rows if r.get('bounced'))}")
    print(f"  has first_name      : {sum(1 for r in rows if r.get('first_name'))}")
    print(f"  has company         : {sum(1 for r in rows if r.get('company'))}")
    enrollable = [r for r in rows if r.get('verified') and not r.get('unsubscribed')
                  and not r.get('bounced')]
    print(f"  verified+active     : {len(enrollable)}")
    print(f"  verify_method mix   : {dict(Counter(r.get('verify_method') for r in rows))}")
    # domain mix of the lead emails (free vs business)
    dom = Counter((r.get('email') or '@?').split('@')[-1].lower() for r in rows)
    print(f"  top lead domains    : {dom.most_common(12)}")

    # 2. Send funnel — filter to mercuryscales senders
    sends = fetch("send_log?from_addr=like.*mercuryscales.com&select=*&limit=20000")
    if sends:
        print("\n  (send_log columns:", ", ".join(sorted(sends[0].keys())), ")")
    n = len(sends)
    print(f"\nSEND LOG: {n} sends from mercuryscales.com")
    if n:
        delivered = sum(1 for s in sends if not s.get('bounced') and not s.get('error'))
        bounced = sum(1 for s in sends if s.get('bounced'))
        errored = sum(1 for s in sends if s.get('error'))
        opened = sum(1 for s in sends if s.get('opened_at'))
        clicked = sum(1 for s in sends if s.get('clicked_at'))
        replied = sum(1 for s in sends if s.get('replied'))
        uniq_to = len(set(s.get('to_addr') for s in sends))
        print(f"  unique recipients   : {uniq_to}")
        print(f"  delivered (no b/e)  : {delivered} ({delivered/n*100:.0f}%)")
        print(f"  bounced             : {bounced} ({bounced/n*100:.0f}%)")
        print(f"  errored             : {errored} ({errored/n*100:.0f}%)")
        print(f"  opened              : {opened} ({opened/max(delivered,1)*100:.0f}% of delivered)")
        print(f"  clicked             : {clicked} ({clicked/max(delivered,1)*100:.0f}% of delivered)")
        print(f"  replied             : {replied} ({replied/max(delivered,1)*100:.1f}% of delivered)")
        print(f"  sends by step       : {dict(sorted(Counter(s.get('step_n') for s in sends).items(), key=lambda x: (x[0] is None, x[0])))}")
        # bounce by step (lead-quality vs sequence-fatigue signal)
        bstep = Counter(s.get('step_n') for s in sends if s.get('bounced'))
        print(f"  bounces by step     : {dict(bstep)}")
        dates = sorted(set((s.get('sent_at') or '')[:10] for s in sends if s.get('sent_at')))
        print(f"  active send dates   : {dates}")

    # 3. Runs / sequence position
    seq = fetch("sequences?profile_slug=eq.dorian&select=id,name")
    if seq:
        sid = seq[0]["id"]
        runs = fetch(f"runs?sequence_id=eq.{sid}&select=status,current_step&limit=5000")
        print(f"\nRUNS: {len(runs)} total on sequence '{seq[0].get('name','')[:40]}'")
        print(f"  by status           : {dict(Counter(r.get('status') for r in runs))}")
        print(f"  by current_step     : {dict(sorted(Counter(r.get('current_step') for r in runs).items(), key=lambda x:(x[0] is None,x[0])))}")
    else:
        print("\nRUNS: no sequence row for dorian (!) — nothing enrollable")


if __name__ == "__main__":
    main()
