"""roster-send-audit.py - read-only send-health check across ALL profiles.

send_log has no profile_slug column, so we attribute each send to a profile by
matching the from_addr domain against each profile's relay.from_domains list.
Prints, per profile, sends in the last 1 / 7 days and the most recent send time.

Run: py scripts/roster-send-audit.py
"""
from __future__ import annotations
import datetime as dt
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV = REPO / "sequences" / "supabase.env"

env = {}
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def fetch(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def load_profiles() -> dict:
    """Map sending-domain -> profile_slug from every non-private profile JSON."""
    dom2slug = {}
    slugs = []
    for pf in sorted(REPO.glob("profiles/*.json")):
        if pf.name.endswith(".private.json"):
            continue
        slug = pf.stem
        slugs.append(slug)
        try:
            d = json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            continue
        for fd in d.get("relay", {}).get("from_domains", []):
            dom = fd.get("domain", "").lower()
            if dom:
                dom2slug[dom] = slug
    return dom2slug, slugs


def main() -> None:
    dom2slug, slugs = load_profiles()
    now = dt.datetime.now(dt.timezone.utc)
    since = (now - dt.timedelta(days=7)).strftime("%Y-%m-%dT00:00:00Z")
    rows = fetch(
        f"send_log?sent_at=gte.{urllib.parse.quote(since)}"
        f"&select=from_addr,sent_at,bounced,replied,error&order=sent_at.desc&limit=5000"
    )

    today = now.strftime("%Y-%m-%d")
    per = defaultdict(lambda: {"7d": 0, "today": 0, "last": None,
                               "bounced": 0, "errored": 0, "replied": 0})
    unmatched = defaultdict(int)

    for s in rows:
        fa = (s.get("from_addr") or "")
        dom = fa.split("@")[-1].lower() if "@" in fa else ""
        slug = dom2slug.get(dom)
        if not slug:
            # try suffix match (send.<sub>.<root> style)
            for d, sl in dom2slug.items():
                if dom.endswith(d) or d.endswith(dom):
                    slug = sl; break
        if not slug:
            unmatched[dom] += 1
            continue
        rec = per[slug]
        rec["7d"] += 1
        if (s.get("sent_at") or "").startswith(today):
            rec["today"] += 1
        if rec["last"] is None or (s.get("sent_at") or "") > rec["last"]:
            rec["last"] = s.get("sent_at")
        if s.get("bounced"): rec["bounced"] += 1
        if s.get("error"): rec["errored"] += 1
        if s.get("replied"): rec["replied"] += 1

    print("=" * 78)
    print(f"ROSTER SEND AUDIT  {now.strftime('%Y-%m-%d %H:%M UTC')}   (last 7 days)")
    print("=" * 78)
    print(f"{'profile':20s} {'7d':>5s} {'today':>6s} {'bounce':>7s} "
          f"{'err':>4s} {'reply':>6s}  last send")
    print("-" * 78)
    for slug in sorted(slugs):
        r = per.get(slug)
        if not r:
            print(f"{slug:20s} {'0':>5s} {'0':>6s} {'-':>7s} {'-':>4s} "
                  f"{'-':>6s}  NONE  <-- not sending")
            continue
        last = (r["last"] or "")[:19]
        flag = ""
        if r["7d"] == 0:
            flag = "  <-- not sending"
        elif r["today"] == 0:
            flag = "  (none yet today)"
        print(f"{slug:20s} {r['7d']:>5d} {r['today']:>6d} {r['bounced']:>7d} "
              f"{r['errored']:>4d} {r['replied']:>6d}  {last}{flag}")

    if unmatched:
        print("-" * 78)
        print("UNMATCHED sending domains (not in any profile from_domains):")
        for dom, n in sorted(unmatched.items(), key=lambda x: -x[1]):
            print(f"   {dom:40s} {n}")
    print("=" * 78)


if __name__ == "__main__":
    main()
