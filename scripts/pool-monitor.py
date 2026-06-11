"""pool-monitor.py — guarantee a 2x prospect buffer for every active profile.

Runs hourly. For each active profile, computes how many step-1 enrollments
the warmup curve will consume today (per-subdomain ramp × subdomain count),
then checks the eligible-unenrolled pool depth in Supabase. If the pool is
below 2x the daily consumption, it triggers `lead_scrape.py run <niche>`
in the background to refill.

Idempotent: skips a profile if a scrape for its niche is already running.

Run:
    py scripts/pool-monitor.py            # do the check, scrape if low
    py scripts/pool-monitor.py --dry      # print what it would do, no scrape
    py scripts/pool-monitor.py --force    # scrape regardless of pool depth

Designed to be scheduled every 1-4 hours via Task Scheduler. Combined with
the daily LES-lead-scrape-* tasks at 08:30, this keeps the pool well above
the consumption floor so the sequence-runner never runs out of step-1
prospects to fire on.
"""
from __future__ import annotations
import argparse
import json
import os
import subprocess
import sys
import urllib.parse
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

# Each active profile + its niche slug + the lead_scrape niche argument.
# Daily TARGET = per-subdomain ramp × subdomain count × 2 (buffer multiplier).
# requires_city mirrors daily-fill-and-enroll.PROFILE_CFG — only F2's variant
# template requires {city}, so a prospect missing city is unsendable there.
PROFILES = [
    {"slug": "aureon",         "niche": "real_estate_us",            "json": "aureon.json",         "requires_city": False,
     "extra_scrapers": []},
    {"slug": "algoalpha",      "niche": "crypto_influencer",         "json": "algoalpha.json",      "requires_city": False,
     # AlgoAlpha-specific: crypto-creator scrapers find emails the generic
     # lead_scrape can't reach. Runs sequentially so we don't blow YT quota.
     "extra_scrapers": [
         ("sequences/youtube_scraper.py",    ["run", "crypto_influencer",
                                              "niches/crypto_youtube_channels.txt", "--no-smtp"]),
         ("sequences/tradingview_scrape.py", ["run", "crypto_influencer",
                                              "niches/tv_handles.txt", "--no-smtp", "--limit", "50"]),
     ]},
    {"slug": "f2-malergipser", "niche": "liegenschaftsverwalter_be", "json": "f2-malergipser.json", "requires_city": True,
     "extra_scrapers": []},
    {"slug": "atalsolidrocks", "niche": "atal_dach_b2b", "json": "atalsolidrocks.json", "requires_city": True,
     "extra_scrapers": []},
]
BUFFER_MULTIPLIER = 2  # always keep 2x daily consumption available


def supa(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def per_subdomain_daily(profile: dict, fd: dict | None = None) -> int:
    """Step on the snowball curve for today's warmup day.

    Each subdomain (fd) has its OWN `warmup.current_day` that drifts ahead of
    the profile-level day as warmup advances. Always prefer the subdomain's
    own day so capacity math matches what daily-fill-and-enroll uses.
    """
    sub_w = (fd or {}).get("warmup") or {}
    prof_w = profile.get("warmup") or {}
    day = int(sub_w.get("current_day") or prof_w.get("current_day") or 1)
    curve = profile.get("ramp_curve_snowball_v1") or [
        {"from_day": 1, "daily": 15}, {"from_day": 8, "daily": 25},
        {"from_day": 15, "daily": 35}, {"from_day": 22, "daily": 50},
    ]
    daily = 0
    for row in sorted(curve, key=lambda r: r["from_day"]):
        if day >= row["from_day"]:
            daily = row["daily"]
    return daily


def is_scrape_running(niche: str) -> bool:
    """Does a lead_scrape for this niche already have a running python.exe?"""
    try:
        out = subprocess.check_output(
            ["powershell.exe", "-Command",
             f"Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object {{ $_.CommandLine -like '*lead_scrape*{niche}*' }} | Select-Object -ExpandProperty ProcessId"],
            text=True, stderr=subprocess.DEVNULL, timeout=10)
        return bool(out.strip())
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="print intent, do not scrape")
    ap.add_argument("--force", action="store_true", help="scrape regardless of pool depth")
    args = ap.parse_args()

    print(f"=== pool-monitor  buffer={BUFFER_MULTIPLIER}x ===")
    for p in PROFILES:
        prof_path = REPO / "profiles" / p["json"]
        if not prof_path.exists():
            print(f"  {p['slug']:18}  ! profile JSON missing")
            continue
        profile = json.loads(prof_path.read_text(encoding="utf-8"))
        subdomains = profile.get("relay", {}).get("from_domains", [])
        verified_subs = [d for d in subdomains if d.get("verified_at")]
        n_subs = len(verified_subs)
        # Sum capacity across subdomains using each subdomain's own warmup day
        # so we match what daily-fill-and-enroll actually consumes per day.
        daily_need = sum(per_subdomain_daily(profile, fd) for fd in verified_subs)
        per_sub = daily_need // n_subs if n_subs else 0  # display only
        target = daily_need * BUFFER_MULTIPLIER

        # Pool: prospects.verified=true AND unsubscribed=false AND not in any
        # active run AND has the merge fields daily-fill-and-enroll requires
        # (first_name + company, plus city iff the variant template needs it).
        # Counting raw verified prospects overstates the pool because lead_scrape
        # often produces rows missing first_name/company that enrollment skips.
        eligible = supa(
            f"prospects?profile_slug=eq.{p['slug']}&verified=eq.true&unsubscribed=eq.false"
            "&select=id,first_name,company,city&limit=10000"
        )
        active_runs = supa(
            f"runs?status=in.(queued,running,paused_replied,paused_bounced)&select=prospect_id&limit=10000"
        )
        enrolled = {r.get("prospect_id") for r in active_runs if r.get("prospect_id")}
        requires_city = p.get("requires_city", False)
        unenrolled = [
            e for e in eligible
            if e["id"] not in enrolled
            and e.get("first_name") and e.get("company")
            and (not requires_city or e.get("city"))
        ]
        pool = len(unenrolled)

        gap = max(0, target - pool)
        below = pool < target
        action = "SCRAPE" if (below or args.force) else "ok"
        if args.dry:
            action = "[dry] " + action

        print(f"  {p['slug']:18}  warmup_day={profile['warmup']['current_day']:>2}  "
              f"per_sub={per_sub:>2}  subs={n_subs}  daily_need={daily_need:>3}  "
              f"target_pool={target:>3}  actual_pool={pool:>3}  gap={gap:>3}  -> {action}")

        if (below or args.force) and not args.dry:
            if is_scrape_running(p["niche"]):
                print(f"      [skip] scrape for {p['niche']} already running")
                continue
            print(f"      [spawn] py sequences/lead_scrape.py run {p['niche']} --no-smtp")
            subprocess.Popen(
                ["py", str(REPO / "sequences" / "lead_scrape.py"), "run", p["niche"], "--no-smtp"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.DETACHED_PROCESS if hasattr(subprocess, "DETACHED_PROCESS") else 0,
                cwd=str(REPO),
            )
            # Profile-specific creator scrapers (AlgoAlpha: youtube + tradingview).
            # Spawned detached so they run alongside lead_scrape, not in series.
            for script_rel, sargs in p.get("extra_scrapers", []):
                script_abs = str(REPO / script_rel)
                # Crude is-running check by script path
                try:
                    out = subprocess.check_output(
                        ["powershell.exe", "-Command",
                         f"Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                         f"Where-Object {{ $_.CommandLine -like '*{Path(script_rel).name}*' }} | "
                         f"Select-Object -ExpandProperty ProcessId"],
                        text=True, stderr=subprocess.DEVNULL, timeout=10)
                    if out.strip():
                        print(f"      [skip] {Path(script_rel).name} already running")
                        continue
                except Exception:
                    pass
                print(f"      [spawn] py {script_rel} {' '.join(sargs)}")
                subprocess.Popen(
                    ["py", script_abs, *sargs],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.DETACHED_PROCESS if hasattr(subprocess, "DETACHED_PROCESS") else 0,
                    cwd=str(REPO),
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
