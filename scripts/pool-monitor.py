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

# Spawn scrapers WINDOWLESS so they never pop a console window on the user's
# desktop. pythonw.exe + CREATE_NO_WINDOW = fully silent background work.
import sys as _sys
PYW = str(Path(_sys.executable).with_name("pythonw.exe"))
if not Path(PYW).exists():
    PYW = "pythonw"
_NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
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
     # Google Places: brokerages live on Maps, not "team pages" — far higher yield
     # for this local ICP, and returns company + city for free.
     "extra_scrapers": [
         ("sequences/places_scrape.py", ["run", "real_estate_us"]),
     ]},
    {"slug": "algoalpha",      "niche": "crypto_influencer",         "json": "algoalpha.json",      "requires_city": False,
     # AlgoAlpha-specific: crypto-creator scrapers find emails the generic
     # lead_scrape can't reach. Runs sequentially so we don't blow YT quota.
     "extra_scrapers": [
         ("sequences/youtube_scraper.py",    ["run", "crypto_influencer",
                                              "niches/crypto_youtube_channels.txt", "--no-smtp"]),
         ("sequences/tradingview_scrape.py", ["run", "crypto_influencer",
                                              "niches/tv_handles.txt", "--no-smtp", "--limit", "50"]),
     ]},
    {"slug": "atalsolidrocks", "niche": "atal_dach_b2b", "json": "atalsolidrocks.json", "requires_city": True,
     "extra_scrapers": [
         ("sequences/places_scrape.py", ["run", "atal_dach_b2b"]),
     ]},
    # diraya/energ/lk are name-optional ({greeting}) — their variant templates do
    # NOT require first_name, so the pool count must not require it either, or it
    # under-reads the pool and scrapes forever. requires_first_name=False mirrors
    # daily-fill-and-enroll.PROFILE_CFG.
    {"slug": "diraya",         "niche": "diraya_b2b_saas",           "json": "diraya.json",         "requires_city": False,
     # Places is supplementary for diraya (B2B SaaS is not Maps-native); the
     # team-page scrape stays primary and a paid bulk source is the real volume
     # lever. Places still adds real tech/agency companies at no extra spend.
     "requires_first_name": False, "extra_scrapers": [
         ("sequences/places_scrape.py", ["run", "diraya_b2b_saas"]),
     ]},
    {"slug": "energ",          "niche": "energ_gewerbe_nrw",         "json": "energ.json",          "requires_city": False,
     "requires_first_name": False, "extra_scrapers": [
         ("sequences/places_scrape.py", ["run", "energ_gewerbe_nrw"]),
     ]},
    {"slug": "lk-advertising", "niche": "real_estate_us_lk",         "json": "lk-advertising.json", "requires_city": False,
     "requires_first_name": False, "extra_scrapers": [
         ("sequences/places_scrape.py", ["run", "real_estate_us_lk"]),
     ]},
    # dorian sources purely via creator scrapers (B2B founders on YouTube/social),
    # so niche is None — pool-monitor skips the team-page scrape and just runs the
    # creator scrapers when the pool is below buffer. Mirrors daily-fill PROFILE_CFG.
    {"slug": "dorian",         "niche": None,                        "json": "dorian.json",         "requires_city": False,
     "requires_first_name": False, "extra_scrapers": [
         ("sequences/youtube_scraper.py", ["discover", "niches/dorian_social_yt_search_terms.txt",
                                           "--out", "niches/dorian_yt_channels.txt", "--pages", "1"]),
         ("sequences/youtube_scraper.py", ["run", "dorian_social", "niches/dorian_yt_channels.txt", "--no-smtp"]),
         ("sequences/social_scrape.py",   ["instagram", "dorian_social", "niches/dorian_social_handles.txt", "--no-smtp", "--limit", "50"]),
         ("sequences/social_scrape.py",   ["twitter", "dorian_social", "niches/dorian_social_handles.txt", "--no-smtp", "--limit", "50"]),
     ]},
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
            text=True, stderr=subprocess.DEVNULL, timeout=10,
            creationflags=_NOWINDOW)
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
        requires_first_name = p.get("requires_first_name", True)
        unenrolled = [
            e for e in eligible
            if e["id"] not in enrolled
            and e.get("company")
            and (e.get("first_name") or not requires_first_name)
            and (not requires_city or e.get("city"))
        ]
        pool = len(unenrolled)

        gap = max(0, target - pool)
        below = pool < target
        action = "SCRAPE" if (below or args.force) else "ok"
        if args.dry:
            action = "[dry] " + action

        print(f"  {p['slug']:18}  warmup_day={(profile.get('warmup',{}).get('current_day') or '?'):>2}  "
              f"per_sub={per_sub:>2}  subs={n_subs}  daily_need={daily_need:>3}  "
              f"target_pool={target:>3}  actual_pool={pool:>3}  gap={gap:>3}  -> {action}")

        if (below or args.force) and not args.dry:
            # Team-page scrape. Skipped for creator-only profiles whose niche is
            # None (dorian sources purely via creator_scrapers).
            niche = p.get("niche")
            if niche:
                if is_scrape_running(niche):
                    print(f"      [skip] scrape for {niche} already running")
                else:
                    print(f"      [spawn] pythonw sequences/lead_scrape.py run {niche} --no-smtp")
                    subprocess.Popen(
                        [PYW, str(REPO / "sequences" / "lead_scrape.py"), "run", niche, "--no-smtp"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        creationflags=_NOWINDOW, cwd=str(REPO),
                    )
            # Extra scrapers (Google Places + creator platforms). Always run,
            # ALONGSIDE any team-page scrape, each with its own niche-specific
            # running check — so a brand's Places/creator refill is never blocked
            # by its (or another brand's) team-page scrape still running.
            for script_rel, sargs in p.get("extra_scrapers", []):
                script_abs = str(REPO / script_rel)
                # Is-running check by script path AND niche arg. Several brands
                # share one scraper script (e.g. places_scrape.py runs for aureon,
                # energ AND lk with different niche args); matching on script name
                # alone would let the first brand's run block all the others in the
                # same tick, so we also require the niche token (sargs[1]).
                name_tok = Path(script_rel).name
                niche_tok = sargs[1] if len(sargs) >= 2 else ""
                filt = f"$_.CommandLine -like '*{name_tok}*'"
                if niche_tok:
                    filt += f" -and $_.CommandLine -like '*{niche_tok}*'"
                try:
                    out = subprocess.check_output(
                        ["powershell.exe", "-Command",
                         f"Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
                         f"Where-Object {{ {filt} }} | "
                         f"Select-Object -ExpandProperty ProcessId"],
                        text=True, stderr=subprocess.DEVNULL, timeout=10,
                        creationflags=_NOWINDOW)
                    if out.strip():
                        print(f"      [skip] {name_tok} {niche_tok} already running")
                        continue
                except Exception:
                    pass
                print(f"      [spawn] pythonw {script_rel} {' '.join(sargs)}")
                subprocess.Popen(
                    [PYW, script_abs, *sargs],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=_NOWINDOW, cwd=str(REPO),
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
