# -*- coding: utf-8 -*-
"""_brand-gate-trace.py — read-only: for given brands, trace the two likely
throttles for low daily volume:
  (1) usable senders: verified+enabled subdomains, each one's per-day cap and
      how many it already sent today (headroom).
  (2) send-window gate: for a sample of DUE runs, resolve the recipient tz and
      run check_send_window — tally allowed / window-blocked / weekend, + tz mix.
No sends. Only reads DB + calls pure guard funcs (which only GET + append a log).

Usage: py scripts/_brand-gate-trace.py [slug ...]
"""
from __future__ import annotations
import json, sys, datetime as dt, urllib.request, urllib.parse
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from profile_lib import load_profile, daily_target_for_domain, iter_send_domains, warmup_day  # noqa
import safeguards  # noqa
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


def dom(a):
    a = (a or "").lower(); return a.split("@", 1)[1] if "@" in a else ""


def resolve_tz(prospect, pc):
    try:
        from prospect_timezone import resolve_timezone
        return resolve_timezone(prospect, pc)
    except Exception as e:
        return f"ERR:{e}"


brands = sys.argv[1:] or ["mark-eting", "lk-advertising", "diraya", "energ"]
today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
now_iso = dt.datetime.utcnow().isoformat() + "Z"

for slug in brands:
    try:
        p = load_profile(slug)
    except Exception as e:
        print(f"\n### {slug}: load error {e}"); continue
    pc = get(f"profiles?slug=eq.{slug}&select=config")[0]["config"]  # exact config the runner uses
    print(f"\n{'='*70}\n### {slug}")

    # (1) usable senders + headroom
    all_doms = (pc.get("relay", {}).get("from_domains") or [])
    usable = iter_send_domains(pc, only_verified=True, only_enabled=True)
    sends = get(f"send_log?sent_at=gte.{today}T00:00:00&select=from_addr&limit=20000")
    today_by_dom = Counter(dom(s["from_addr"]) for s in sends)
    cap_total = 0; head_total = 0
    print(f"  subdomains: {len(all_doms)} total, {len(usable)} verified+enabled")
    for d in usable:
        cap = daily_target_for_domain(pc, d)
        used = today_by_dom.get(d["domain"].lower(), 0)
        cap_total += cap; head_total += max(cap - used, 0)
        wd = warmup_day(d)
        if cap == 0 or used >= cap or len(usable) <= 14:
            print(f"    {d['domain']:<34} day{wd:>3} cap{cap:>4} used{used:>4} head{max(cap-used,0):>4}"
                  + ("  <FULL>" if cap and used >= cap else ("  <cap0>" if cap == 0 else "")))
    print(f"  -> usable cap/day={cap_total}  headroom_now={head_total}")

    # (2) send-window gate on a sample of DUE runs
    base = ("runs?select=prospect_id,sequences!inner(profile_slug)&sequences.profile_slug=eq." + slug
            + "&status=eq.queued&or=(next_send_at.lte." + urllib.parse.quote(now_iso) + ",next_send_at.is.null)&limit=150")
    due = get(base)
    pids = [r["prospect_id"] for r in due if r.get("prospect_id")]
    pros = {}
    for i in range(0, len(pids), 120):
        chunk = pids[i:i+120]
        if not chunk:
            continue
        idl = "(" + ",".join(chunk) + ")"
        for pr in get(f"prospects?id=in.{idl}&select=*"):
            pros[pr["id"]] = pr
    verdict = Counter(); tzc = Counter(); examples = {}
    for r in due:
        pr = pros.get(r["prospect_id"])
        if not pr:
            verdict["no_prospect"] += 1; continue
        tz = resolve_tz(pr, pc); tzc[tz] += 1
        ok, why = safeguards.check_send_window(profile_config=pc, prospect=pr)
        key = "ALLOWED" if ok else (why.split(":")[0] if why else "blocked")
        verdict[key] += 1
        if not ok and key not in examples:
            examples[key] = why
    print(f"  window gate on {len(due)} due (sampled): {dict(verdict)}")
    print(f"    tz mix: {dict(tzc.most_common(6))}")
    for k, v in examples.items():
        print(f"    e.g. {v}")
print(f"\nstamp {dt.datetime.now().strftime('%H:%M:%S')} local")
