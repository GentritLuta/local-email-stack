# -*- coding: utf-8 -*-
"""ab-status.py — read the aureon step-1 A/B (seller-test vs give-first attorney list).

The runner splits step 1 50/50 by prospect_id hash: A-side = "a seller test for {company}",
B-side = "45 attorneys who hand off listings, {company}". Both carry the company merge, so we
match each step-1 send to its side by a stable subject substring, and tie genuine replies back
through the run. Compares delivered / open rate / reply rate per side since the A/B started.

  py scripts/ab-status.py            # since 2026-06-22 (A/B start)
  py scripts/ab-status.py --since 2026-06-25
"""
from __future__ import annotations
import argparse
import json
import ssl
import sys
import urllib.request
from pathlib import Path

ssl._create_default_https_context = ssl._create_unverified_context
REPO = Path(__file__).resolve().parent.parent
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def env(p: Path) -> dict:
    d = {}
    for ln in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        if "=" in ln and not ln.strip().startswith("#"):
            k, v = ln.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


S = env(REPO / "sequences" / "supabase.env")
TOK = S.get("SUPABASE_ACCESS_TOKEN")
REF = "ccmqkljsjiuavpydbkva"


def q(sql: str):
    req = urllib.request.Request(
        f"https://api.supabase.com/v1/projects/{REF}/database/query",
        data=json.dumps({"query": sql}).encode(),
        headers={"Authorization": f"Bearer {TOK}", "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 Chrome/123"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=40).read())


def pct(n, d):
    return round(100 * n / d, 2) if d else 0.0


# per-profile step-1 A/B: (label, subject substring) for each side. A = current opener, B = give-first.
AB = {
    "aureon": {"a_lab": "A  seller test", "a_sub": "seller test",
               "b_lab": "B  give-first list", "b_sub": "attorneys who hand off"},
    "energ":  {"a_lab": "A  CHECK assessment", "a_sub": "schriftliche",
               "b_lab": "B  give-first FALLEN list", "b_sub": "vertragsfallen"},
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default="aureon", choices=list(AB), help="which client A/B to read")
    ap.add_argument("--since", default="2026-06-22", help="A/B start date (YYYY-MM-DD)")
    a = ap.parse_args()
    cfg = AB[a.profile]
    rows = q(f"""
      with s1 as (
        select s.run_id, s.delivered, s.opened_at,
          case when s.subject ilike '%%{cfg['b_sub']}%%' then '{cfg['b_lab']}'
               when s.subject ilike '%%{cfg['a_sub']}%%' then '{cfg['a_lab']}'
               else 'other' end side
        from send_log s join runs r on r.id=s.run_id join prospects p on p.id=r.prospect_id
        where p.profile_slug='{a.profile}' and s.step_n=1 and s.sent_at >= '{a.since}'),
      rep as (select distinct run_id from replies where profile_slug='{a.profile}' and class='reply')
      select s1.side, count(*) sends, count(*) filter (where s1.delivered) delivered,
        count(*) filter (where s1.opened_at is not null) opened,
        count(*) filter (where rep.run_id is not null) replies
      from s1 left join rep on rep.run_id=s1.run_id
      group by s1.side order by s1.side""")
    print(f"{a.profile} step-1 A/B  (since {a.since})\n" + "-" * 64)
    print(f"{'side':20} {'sends':>6} {'deliv':>6} {'open%':>7} {'repl':>5} {'reply%':>7}")
    for r in rows:
        print(f"{r['side']:20} {r['sends']:>6} {r['delivered']:>6} "
              f"{pct(r['opened'], r['delivered']):>6}% {r['replies']:>5} {pct(r['replies'], r['delivered']):>6}%")
    if not rows:
        print("(no step-1 sends since the start date yet — check back after the next send cycle)")
    print(f"\n{cfg['a_lab'].strip()} = current opener · {cfg['b_lab'].strip()} = give-first challenger")
    return 0


if __name__ == "__main__":
    sys.exit(main())
