"""daily-status.py - one-page health report on the autonomous pipeline.

Prints, per profile:
  - prospects in pool (verified / has-merges / enrolled / unenrolled)
  - runs by status + step
  - today's sends per subdomain vs cap
  - current_day on each subdomain (warmup ramp position)
  - seed count in the niche YAML

Plus today's totals (sends, bounces, errors, replies) and the next
upcoming step-2 fire-time per profile.

Run: py scripts/daily-status.py
"""
from __future__ import annotations
import datetime as dt
import json
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ENV  = REPO / "sequences" / "supabase.env"

env = {}
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

PROFILES = [
    ("aureon",          "real_estate_us",            False),
    ("algoalpha",       "crypto_influencer",         False),
]


def fetch(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=30).read())


def main() -> None:
    today_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    sends_today = fetch(
        f"send_log?sent_at=gte.{urllib.parse.quote(today_iso)}"
        f"&select=from_addr,bounced,replied,error&limit=2000"
    )
    sub_counts = Counter(s["from_addr"].split("@")[-1]
                         for s in sends_today if s.get("from_addr"))
    bounced = sum(1 for s in sends_today if s.get("bounced"))
    replied = sum(1 for s in sends_today if s.get("replied"))
    errored = sum(1 for s in sends_today if s.get("error"))

    print("=" * 70)
    print(f"DAILY STATUS  {dt.datetime.now().strftime('%Y-%m-%d %H:%M %z')}")
    print("=" * 70)
    print(f"sends today: {len(sends_today)}   bounces: {bounced}   "
          f"errors: {errored}   replies: {replied}")
    print()

    for profile_slug, niche_slug, requires_city in PROFILES:
        # Pool counts
        rows = fetch(
            f"prospects?profile_slug=eq.{profile_slug}"
            f"&select=id,verified,unsubscribed,first_name,company,city&limit=2000"
        )
        verified_active = [r for r in rows
                           if r.get("verified") and not r.get("unsubscribed")]
        has_merges = [r for r in verified_active
                      if r.get("first_name") and r.get("company")
                      and (not requires_city or r.get("city"))]
        # Runs by status
        seq = fetch(f"sequences?profile_slug=eq.{profile_slug}&select=id")
        sid = seq[0]["id"] if seq else None
        if sid:
            runs = fetch(f"runs?sequence_id=eq.{sid}&select=status,current_step,next_send_at&limit=2000")
            enrolled_ids = set()
            try:
                enrolled_ids = {
                    r["prospect_id"] for r in fetch(
                        f"runs?sequence_id=eq.{sid}&select=prospect_id&limit=2000")
                }
            except Exception:
                pass
            status_ct = Counter(r["status"] for r in runs)
            step_ct = Counter(r["current_step"] for r in runs)
            # Next step-2 fire time
            future = [r for r in runs
                      if r["status"] == "queued" and r.get("next_send_at")
                      and r["next_send_at"] > dt.datetime.now(dt.timezone.utc).isoformat()]
            next_fire = min((r["next_send_at"] for r in future), default=None)
        else:
            runs = []
            status_ct = Counter()
            step_ct = Counter()
            next_fire = None
            enrolled_ids = set()
        eligible_unenrolled = [r for r in has_merges if r["id"] not in enrolled_ids]
        # Niche YAML
        niche_path = REPO / "niches" / f"{niche_slug}.yaml"
        seed_count = 0
        if niche_path.exists():
            d = yaml.safe_load(niche_path.read_text(encoding="utf-8"))
            seed_count = len(d.get("seeds") or [])
        # Warmup state per subdomain
        pf = REPO / "profiles" / f"{profile_slug}.json"
        sds = []
        if pf.exists():
            d = json.loads(pf.read_text(encoding="utf-8"))
            for fd in d.get("relay", {}).get("from_domains", []):
                sub = fd["domain"]
                w = fd.get("warmup", {})
                sds.append((sub, w.get("current_day", 0),
                            sub_counts.get(sub, 0)))

        print(f"--- {profile_slug} ---")
        print(f"  niche YAML seeds       : {seed_count}")
        print(f"  prospects in DB        : {len(rows)} total, "
              f"{len(verified_active)} verified-active, "
              f"{len(has_merges)} have-merges, "
              f"{len(eligible_unenrolled)} eligible-unenrolled")
        print(f"  runs                   : total={len(runs):3d}  "
              f"status={dict(status_ct)}  step={dict(step_ct)}")
        if sds:
            print(f"  subdomains (day / sent today / cap=15):")
            for sub, day, sent in sds:
                bar = "#" * sent
                print(f"    {sub:35s} day={day:2d}  {sent:2d}/15 {bar}")
        if next_fire:
            print(f"  next step fire        : {next_fire[:19]}")
        print()


if __name__ == "__main__":
    main()
