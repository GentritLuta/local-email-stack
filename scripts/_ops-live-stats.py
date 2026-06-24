"""_ops-live-stats.py — read-only operation-wide snapshot across ALL brands.

For each profile: prospect pool (total / verified / has-first-name / verified_method
coverage) and the lifetime send funnel (sent / delivered / bounce% / open% / click% /
reply% + sends-by-step) mapped from send_log via each profile's sending domains. No writes.
"""
from __future__ import annotations
import json
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV = REPO / "sequences" / "supabase.env"
env = {}
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "User-Agent": "les-ops/1.0"}


def fetch(path: str) -> list:
    """Paginate past PostgREST's 1000-row cap via Range headers."""
    out = []
    step = 1000
    start = 0
    sep = "&" if "?" in path else "?"
    while True:
        req = urllib.request.Request(f"{URL}/rest/v1/{path}{sep}limit={step}&offset={start}", headers=H)
        chunk = json.loads(urllib.request.urlopen(req, timeout=120).read())
        out.extend(chunk)
        if len(chunk) < step:
            break
        start += step
    return out


def main() -> None:
    # Map sending root-domain -> profile slug
    dom2profile = {}
    profiles = []
    for pf in sorted(REPO.glob("profiles/*.json")):
        if pf.name.endswith(".private.json"):
            continue
        d = json.loads(pf.read_text(encoding="utf-8"))
        slug = d.get("slug", pf.stem)
        active = d.get("active", True)
        profiles.append((slug, active))
        for fd in d.get("relay", {}).get("from_domains", []):
            dom2profile[fd["domain"].lower()] = slug

    # All send_log (lifetime). Map each row to a profile by its sender domain.
    sends = fetch("send_log?select=from_addr,bounced,replied,opened_at,clicked_at,error,step_n,sent_at")
    by_profile = defaultdict(list)
    unmatched = 0
    for s in sends:
        fa = (s.get("from_addr") or "").lower()
        dom = fa.split("@")[-1]
        slug = dom2profile.get(dom)
        if not slug:
            # try matching by root (strip leftmost label)
            parts = dom.split(".")
            for i in range(len(parts) - 1):
                cand = ".".join(parts[i:])
                if cand in dom2profile:
                    slug = dom2profile[cand]; break
        if slug:
            by_profile[slug].append(s)
        else:
            unmatched += 1

    print("=" * 78)
    print("OPERATION-WIDE SNAPSHOT  (lifetime send_log + current pool)")
    print("=" * 78)
    hdr = f"{'brand':<17}{'pool':>5}{'ver':>5}{'fn':>4}{'sent':>6}{'bnc%':>6}{'opn%':>6}{'clk%':>6}{'rpl%':>6}  steps"
    print(hdr); print("-" * 78)

    for slug, active in profiles:
        rows = fetch(f"prospects?profile_slug=eq.{slug}&select=verified,first_name,verification_method,unsubscribed")
        pool = len(rows)
        ver = sum(1 for r in rows if r.get("verified"))
        fn = sum(1 for r in rows if r.get("first_name"))
        vmeth = Counter(r.get("verification_method") for r in rows)
        s = by_profile.get(slug, [])
        n = len(s)
        if n:
            deliv = sum(1 for x in s if not x.get("bounced") and not x.get("error")) or 1
            bnc = sum(1 for x in s if x.get("bounced"))
            opn = sum(1 for x in s if x.get("opened_at"))
            clk = sum(1 for x in s if x.get("clicked_at"))
            rpl = sum(1 for x in s if x.get("replied"))
            steps = dict(sorted(Counter(x.get("step_n") for x in s).items(), key=lambda z: (z[0] is None, z[0])))
            line = (f"{slug:<17}{pool:>5}{ver:>5}{fn:>4}{n:>6}"
                    f"{bnc/n*100:>5.0f}%{opn/deliv*100:>5.0f}%{clk/deliv*100:>5.0f}%{rpl/deliv*100:>5.1f}%  {steps}")
        else:
            line = f"{slug:<17}{pool:>5}{ver:>5}{fn:>4}{0:>6}{'-':>6}{'-':>6}{'-':>6}{'-':>6}  (no sends)"
        print(line)
        # verification_method coverage (the lead-quality tell)
        vm = {str(k): v for k, v in vmeth.items()}
        print(f"                  verify_method: {vm}")

    print("-" * 78)
    print(f"unmatched send_log rows (no profile domain map): {unmatched}")
    print(f"total send_log rows: {len(sends)}")


if __name__ == "__main__":
    main()
