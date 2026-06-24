# -*- coding: utf-8 -*-
"""_brand-bottleneck.py — read-only: for given brands, show where the funnel
narrows TODAY: eligible pool -> queued runs -> due-now runs -> sent today vs cap.
Pinpoints whether low volume is sender, enrollment, pool, or warmup. No writes.

Usage: py scripts/_brand-bottleneck.py [slug ...]   (default: the watched brands)
"""
from __future__ import annotations
import json, sys, datetime as dt, urllib.request, urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from profile_lib import load_profile, daily_target_for_domain  # noqa
try:
    from profile_lib import warmup_day  # noqa
except Exception:
    warmup_day = None
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

env = {}
for ln in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in ln and not ln.strip().startswith("#"):
        k, v = ln.split("=", 1); env[k.strip()] = v.strip()
U = env["SUPABASE_URL"].rstrip("/") + "/rest/v1/"; K = env["SUPABASE_ANON_KEY"]
H = {"apikey": K, "Authorization": "Bearer " + K}


def get(path):
    return json.loads(urllib.request.urlopen(urllib.request.Request(U + path, headers=H), timeout=90).read())


def count(path):
    req = urllib.request.Request(U + path + ("&" if "?" in path else "?") + "limit=1",
                                 headers={**H, "Prefer": "count=exact"})
    with urllib.request.urlopen(req, timeout=90) as r:
        cr = r.headers.get("content-range", "")  # e.g. 0-0/123
    return int(cr.split("/")[-1]) if "/" in cr and cr.split("/")[-1].isdigit() else 0


def dom(a):
    a = (a or "").lower(); return a.split("@", 1)[1] if "@" in a else ""


brands = sys.argv[1:] or ["mark-eting", "diraya", "energ", "lk-advertising", "aureon"]
now_iso = dt.datetime.utcnow().isoformat() + "Z"
today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")

# today's send_log once, map domain->brand for sent-today attribution
dom2brand = {}
for pj in sorted((REPO / "profiles").glob("*.json")):
    try:
        p = load_profile(pj.stem)
    except Exception:
        continue
    for d in p.get("relay", {}).get("from_domains", []):
        dom2brand[d["domain"].lower()] = pj.stem
sends = get(f"send_log?sent_at=gte.{today}T00:00:00&select=from_addr&limit=20000")
sent_today = {}
for s in sends:
    b = dom2brand.get(dom(s["from_addr"]))
    if b:
        sent_today[b] = sent_today.get(b, 0) + 1

print(f"=== brand bottleneck @ {dt.datetime.now().strftime('%H:%M:%S')} local (UTC now {now_iso}) ===\n")
hdr = f"{'brand':<16}{'pool_elig':>10}{'queued':>9}{'due_now':>9}{'sent_tod':>9}{'cap/day':>9}{'subs':>6}{'wday':>6}"
print(hdr); print("-" * len(hdr))
for slug in brands:
    try:
        p = load_profile(slug)
    except Exception as e:
        print(f"{slug:<16}  (load error: {e})"); continue
    pool = count(f"prospects?profile_slug=eq.{slug}&verified=eq.true&unsubscribed=eq.false&select=id")
    # runs joined to sequences for profile scope
    base = "runs?select=id,sequences!inner(profile_slug)&sequences.profile_slug=eq." + slug
    queued = count(base + "&status=eq.queued")
    due = count(base + "&status=eq.queued&or=(next_send_at.lte." + urllib.parse.quote(now_iso) + ",next_send_at.is.null)")
    doms = p.get("relay", {}).get("from_domains", [])
    cap = sum(daily_target_for_domain(p, d) for d in doms)
    wday = ""
    if warmup_day:
        try:
            wday = warmup_day(p)
        except Exception:
            wday = "?"
    print(f"{slug:<16}{pool:>10}{queued:>9}{due:>9}{sent_today.get(slug,0):>9}{cap:>9}{len(doms):>6}{str(wday):>6}")

print("\nReading: due_now>0 but sent_tod<<cap and no more sends => SENDER not draining due runs.")
print("         queued small / due_now 0 => ENROLLMENT under-enqueued (daily-fill).")
print("         pool_elig small => POOL/lead-supply bound. cap small => WARMUP day low.")
