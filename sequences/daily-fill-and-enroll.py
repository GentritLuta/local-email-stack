"""daily-fill-and-enroll.py — auto-fill the verified-prospect pool per
profile each day, then enroll new eligible prospects up to that day's
warmup cap.

This is the orchestrator that runs the full daily pipeline so each
profile auto-produces enough verified leads for the day. Designed to be
the single scheduled task that ties scrape -> context -> backfill ->
enroll -> tick together. Idempotent.

PIPELINE (per profile, in order):
  1. Run that profile's lead_scrape (re-walks team-page seeds)
  2. If profile has creator niches, run youtube + tradingview scrape
  3. Run the per-profile name-derivation backfill so first_name +
     company exist on as many newly-scraped rows as possible
  4. Compute the day's effective cap from the warmup curve:
        cap = sum_per_subdomain( daily_target_for_domain ) - sent_today
  5. Pick eligible unenrolled prospects (verified, not unsub, has
     first_name + company + city-if-required), enroll up to `cap`
  6. Tick sequence-runner once so newly-enrolled fire today

Each profile loops scrape -> backfill -> count up to MAX_PASSES times
to give the scrapers a chance to fill the pool (e.g. lead_verify SMTP
delays). If two passes in a row produce no net new eligible prospects,
the profile is considered exhausted for the day and the orchestrator
moves on without retrying further.

Usage:
    py sequences/daily-fill-and-enroll.py            # all profiles
    py sequences/daily-fill-and-enroll.py --profile aureon
    py sequences/daily-fill-and-enroll.py --no-scrape  # skip scraping (debug)
    py sequences/daily-fill-and-enroll.py --dry        # plan, no enroll/tick

Scheduled task: LES-daily-fill-and-enroll runs daily after the
LES-lead-scrape-* tasks complete (recommended 09:30 local).
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import subprocess
import sys
import urllib.parse
import urllib.request
import urllib.error
from collections import Counter
from pathlib import Path

import suppress  # global do-not-contact list (repliers, opt-outs, blocked domains)

REPO = Path(__file__).resolve().parent.parent
ENV  = REPO / "sequences" / "supabase.env"

env = {}
for line in ENV.read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H_R = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}
H_W = {**H_R, "Content-Type": "application/json"}

# Per-profile pipeline config
# - niche_slug: argument to lead_scrape.py run <slug>
# - backfill_script: path to the profile-specific backfill (relative to repo)
# - creator_scrapers: extra scrapers to run before backfill (algoalpha only)
# - requires_city: True iff first_name+company+city are all in required_merges
PROFILE_CFG = {
    "aureon": {
        "niche_slug":      "real_estate_us",
        "backfill_script": "scripts/backfill-aureon-prospects.py",
        "creator_scrapers": [],
        "requires_city":   False,
        # Real-estate copy now greets "{greeting}" (first name when known, else
        # "{company} team"), so a brokerage lead with a company but no parseable
        # personal name — incl. front-desk info@/office@ inboxes — is a valid
        # target. Named leads are still enrolled first (see enroll_up_to).
        "requires_first_name": False,
        # SOURCE DENYLIST (2026-07-16, measured on 7335 lifetime sends).
        # Every aureon reply ever (18) came from a cross-brokerage agent
        # DIRECTORY — whitestagrealty 14, fastexpert 3 (0.45% pooled). The
        # sources below are SINGLE-brokerage staff rosters: salaried agents
        # who don't buy seller leads. Together 0 replies on 960 sends; at the
        # directory rate we'd have expected ~13 (p ~ 1e-6). See _source_ok.
        # corcoranperry (24 sends) and cwbr.org (61) are NOT listed — too
        # little data to condemn; they stay in and get measured.
        "source_deny": ["blairrg.com", "compass.com",
                        "ascendgroupre.com", "jenniferlandro.com"],
        # Work the sources that actually reply first (measured, see above).
        "source_prefer": ["whitestagrealty.com", "fastexpert.com"],
        # E1 guard (2026-07-16): don't enroll a lead until {company} renders a
        # real name — see _renders_ok. 589 of 1006 eligible are waiting on a
        # company backfill from their website; they are held, not dropped.
        "require_real_company": True,
        # CROSS-BRAND (2026-07-16). lk-advertising has had this since 06-13, but
        # aureon never did, so the guard was one-way: LK stayed out of aureon's
        # leads while aureon freely re-mailed LK's. 84 humans got cold email from
        # both brands, 73 of them after 06-19 and 13 on 07-15 alone. The
        # send-time check in safeguards.check_recipient_dedup is scoped to each
        # profile's own sending root ON PURPOSE (a blanket block once starved LK),
        # so enroll-time is the right layer. Costs aureon 66 of 400 eligible.
        # NOTE: this makes the two brands race for shared directory leads rather
        # than giving aureon first claim — that allocation call is the user's,
        # since LK is a paying client.
        "dedupe_cross_brand": True,
    },
    "algoalpha": {
        # 2026-07-07: was "crypto_influencer" (team_pages niche) which scraped crypto
        # NEWSROOM team/speaker pages (decrypt.co/team, coindesk speakers) = media
        # outlets and companies, NOT individual creators = off-ICP. Set to None so
        # daily-fill skips team-page sourcing and uses only the creator_scrapers
        # (YouTube + TradingView), which yield real individual crypto/trading creators.
        "niche_slug":      None,
        "backfill_script": "scripts/backfill-algoalpha-prospects.py",
        "creator_scrapers": [
            # (script, args)
            ("sequences/youtube_scraper.py",     ["run", "crypto_influencer",
                                                  "niches/crypto_youtube_channels.txt",
                                                  "--no-smtp"]),
            ("sequences/tradingview_scrape.py",  ["run", "crypto_influencer",
                                                  "niches/tv_handles.txt",
                                                  "--no-smtp", "--limit", "50"]),
        ],
        "requires_city":   False,
        # crypto copy greets "{greeting}" (company fallback), so leads with a
        # company but no parseable first name are still enrollable.
        "requires_first_name": False,
    },
    "atalsolidrocks": {
        "niche_slug":      "atal_dach_b2b",
        # Uses the aureon-style backfill which handles email-local-part name
        # parsing + free-mail filtering (English/DACH name patterns are similar
        # enough until an atal-specific backfill is written).
        "backfill_script": "scripts/backfill-aureon-prospects.py",
        "creator_scrapers": [],
        "requires_city":   True,
    },
    "diraya": {
        # WIDENED 2026-06-14: ICP broadened from seed-Series-B AI founders (YC
        # published-email ceiling ~100) to ALL B2B SaaS/tech/software companies via
        # the diraya_b2b_saas team_pages niche, so the pool can feed real volume.
        # Copy is now name-optional ({greeting}), so role inboxes (info@/contact@)
        # enroll. The YC published-email harvest (diraya-nightly-grow) still runs as
        # a second, higher-quality named-founder source. Sends on the Pro Resend
        # account (key in profiles/diraya.private.json).
        # REVERTED 2026-07-07: the diraya_b2b_saas widening pulled IT dev-shops /
        # consultancies / "logistics software" industry pages (computools, edvantis,
        # eliftech) that are NOT venture-stage software-product startups = off-ICP.
        # diraya's real ICP is venture AI/SaaS startups; those come from the YC
        # published-email harvest (diraya-nightly-grow -> yc_ai csv_import). Fit
        # over volume: use only that source, stop scraping the broad junk niche.
        "niche_slug":      None,
        "backfill_script": None,
        "creator_scrapers": [],
        "requires_city":   False,
        "requires_first_name": False,  # name-optional ({greeting}); role inboxes OK
        "import_only":     True,       # YC-imported venture startups only, no broad scrape
    },
    "energ": {
        # Energy-intensive German KMU/Gewerbe in NRW. Leads come from German
        # Impressum/Kontakt pages (energ_gewerbe_nrw niche). ENER-G copy was
        # rewritten to a name-optional Sie-Anrede ("Guten Tag,") keyed on
        # {company}, so a role inbox (info@/kontakt@) with a company but no
        # parseable first name is a valid target. lead_scrape already sets
        # company + verifies the address, and the aureon backfill is hardcoded
        # to profile_slug=aureon (would no-op here), so skip the backfill phase.
        "niche_slug":      "energ_gewerbe_nrw",
        "backfill_script": None,
        "creator_scrapers": [],
        "requires_city":   False,
        "requires_first_name": False,
    },
    "lk-advertising": {
        # Performance media for US REAL ESTATE AGENTS (repointed 2026-06-10 per
        # Lukas Koehler's onboarding form; was German Maklerbueros). Leads come
        # from the real_estate_us_lk niche — the same proven US-brokerage
        # team-page source as Aureon's real_estate_us, bound to lk-advertising
        # with LK's own English sequence. Copy is name-optional ({greeting}), so
        # first name is NOT required. No aureon backfill (no-op here), skip it.
        # Senders: lk-advertising.site subdomains once DNS verifies on Lukas's
        # Hostinger (collaboration invite -> publish records via hPanel); the
        # aureonglobal.de connect./partners. subs are the fallback meanwhile.
        "niche_slug":      "real_estate_us_lk",
        "backfill_script": None,
        "creator_scrapers": [],
        "requires_city":   False,
        "requires_first_name": False,
        # OWN-LANE (2026-06-13): LK shares aureon's real-estate source, so 61-86%
        # of its leads were ALREADY emailed by aureon. The send-time anti-double-
        # email guard correctly blocked them, leaving 287 runs stuck queued and
        # ~0 sends. dedupe_cross_brand makes LK enroll ONLY leads no other brand
        # has emailed (checked against send_log), so it stops colliding with aureon
        # and only works fresh prospects. Flag is read by count_eligible_unenrolled
        # + enroll_up_to; absent/false for every other brand so they are unchanged.
        "dedupe_cross_brand": True,
    },
    "mark-eting": {
        # Mark-eting B.V. (Mark Eizema) — SEO / online visibility for US service
        # businesses (trades + professional services). team_pages scrape of US
        # service-business sites; name-optional ({greeting}). Compliance no-solicitation
        # gate + SMTP/MX verify apply automatically. Sends once getmark-eting.com DNS verifies.
        "niche_slug":      "mark_eting_us_service",
        "backfill_script": None,
        "creator_scrapers": [],
        "requires_city":   False,
        "requires_first_name": False,
    },
    "dorian": {
        # Mercury Scales (Dorian Skiljo): client acquisition for self-made B2B
        # founders (AI/automation agencies, sales/closing coaches, high-ticket
        # offer owners) in English-speaking markets + Germany. This ICP is NOT
        # website-team-page scrapeable (targets are individuals on social, not
        # firms with a /team page), so niche_slug stays None (steps 1+2 skip)
        # and sourcing runs via creator_scrapers (wired 2026-06-10):
        #   a. youtube discover — grows niches/dorian_yt_channels.txt from the
        #      ICP search terms (100 quota units/query/page, shared YT key).
        #   b. youtube run — pulls business emails from channel About text.
        #   c+d. social_scrape instagram/twitter — bio emails from the
        #      hand-curated niches/dorian_social_handles.txt (no-op while empty).
        # CSV import via scripts/import-prospects-csv.py dorian <file.csv> still
        # works on top. Sends from mercuryscales.com subdomains on the
        # full-access Resend key. The dorian-default variant only needs
        # {first_name} (company is optional — many targets are personal brands).
        "niche_slug":      None,
        "backfill_script": None,
        "creator_scrapers": [
            ("sequences/youtube_scraper.py", ["discover",
                                              "niches/dorian_social_yt_search_terms.txt",
                                              "--out", "niches/dorian_yt_channels.txt",
                                              "--pages", "1"]),
            ("sequences/youtube_scraper.py", ["run", "dorian_social",
                                              "niches/dorian_yt_channels.txt",
                                              "--no-smtp"]),
            ("sequences/social_scrape.py",   ["instagram", "dorian_social",
                                              "niches/dorian_social_handles.txt",
                                              "--no-smtp", "--limit", "50"]),
            ("sequences/social_scrape.py",   ["twitter", "dorian_social",
                                              "niches/dorian_social_handles.txt",
                                              "--no-smtp", "--limit", "50"]),
        ],
        "requires_city":   False,
        # Name-optional 2026-06-11: Dorian copy now greets "{greeting}" (first_name
        # when known, else a neutral fallback), so role-mailbox founder leads
        # (info@, hello@) enroll. Matches energ/lk/algoalpha.
        "requires_first_name": False,
        "import_only":     False,
    },
}

MAX_PASSES = 4  # scrape passes per profile to reach the buffer target
SUBPROCESS_TIMEOUT = 600  # seconds
BUFFER_DAYS = 3  # keep the eligible-lead pool stocked to 3x the daily send need


def http_get(path: str) -> list:
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H_R)
    return json.loads(urllib.request.urlopen(req, timeout=60).read())


def http_get_all(path: str) -> list:
    """http_get, paged past PostgREST's server-side row cap.

    The server caps a response at 1000 rows no matter how big the client's
    `limit` is, and returns 200 — so a bare `limit=2000` silently truncates.
    That made enroll_up_to blind to prospects beyond the first 1000 AND gave
    it a short `enrolled` set, so already-enrolled leads looked eligible,
    consumed the day's target, then 409'd on the (sequence_id, prospect_id)
    unique key. Page until a short chunk comes back.
    """
    out, step, start = [], 1000, 0
    sep = "&" if "?" in path else "?"
    while True:
        chunk = http_get(f"{path}{sep}limit={step}&offset={start}")
        out.extend(chunk)
        if len(chunk) < step:
            return out
        start += step


def http_post(path: str, body: dict) -> None:
    req = urllib.request.Request(
        f"{URL}/rest/v1/{path}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={**H_W, "Prefer": "return=minimal"},
    )
    urllib.request.urlopen(req, timeout=60)


def run_subprocess(script: str, args: list[str]) -> tuple[int, str]:
    """Run a Python script in a subprocess from the repo root. Capture
    output. Return (exit_code, last 30 lines of stdout+stderr)."""
    cmd = ["py", script, *args]
    try:
        p = subprocess.run(
            cmd, cwd=str(REPO), capture_output=True, text=True,
            timeout=SUBPROCESS_TIMEOUT, encoding="utf-8", errors="replace",
            # Parent runs under pythonw (no console); a py.exe child would
            # allocate and FLASH a new console window per step without this.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        out = (p.stdout or "") + (p.stderr or "")
        tail = "\n".join(out.splitlines()[-30:])
        return p.returncode, tail
    except subprocess.TimeoutExpired:
        return -1, f"  ! TIMEOUT after {SUBPROCESS_TIMEOUT}s"
    except Exception as e:
        return -1, f"  ! exception: {e}"


def get_sequence_id(profile_slug: str) -> str | None:
    rows = http_get(f"sequences?profile_slug=eq.{profile_slug}&select=id")
    return rows[0]["id"] if rows else None


def _warmup_day(w: dict) -> int:
    """Warmup day (1-based) derived from warmup.started_at as CALENDAR days.

    Calendar-based on purpose: the old stored `current_day` counter relied on a
    daily advance tick that silently stalled, freezing every subdomain at the
    week-1 cap (15) forever. Deriving from started_at means the ramp advances on
    its own (15 -> 25 -> 35 -> 50) and can never get stuck. Falls back to the
    stored current_day only when started_at is missing."""
    w = w or {}
    sa = w.get("started_at")
    if sa:
        try:
            start = dt.date.fromisoformat(str(sa)[:10])
            return (dt.date.today() - start).days + 1
        except ValueError:
            pass
    return int(w.get("current_day", 0))


def cap_target_for_profile(profile_slug: str) -> tuple[int, dict[str, int]]:
    """Today's room across all subdomains in this profile = sum(
    daily_target - sent_today ) per from_domain.

    Reads the DB `profiles.config`, NOT profiles/<slug>.json, because the
    sequence-runner sends off the DB config (fetch_profile_config) — budgeting
    against the local file over-enrolls whenever the two have drifted. They
    HAD drifted badly for aureon (2026-07-16): the file listed 12 subdomains
    on a 15/25/35/50 curve (up to 600/day) while the DB had 6 subdomains on a
    17/21/25 curve (150/day), so enrollment bought ~4x the capacity that could
    actually send. The surplus sat queued, aged into follow-up steps, and ate
    the cap that new step-1 sends needed. Falls back to the file only if the
    DB has no config for this profile.
    """
    d = None
    try:
        rows = http_get(f"profiles?slug=eq.{profile_slug}&select=config")
        if rows and rows[0].get("config"):
            d = rows[0]["config"]
    except Exception as e:
        print(f"  ! {profile_slug}: DB config unavailable ({e}); falling back to profile JSON")
    if d is None:
        pf = REPO / "profiles" / f"{profile_slug}.json"
        if not pf.exists(): return 0, {}
        d = json.loads(pf.read_text(encoding="utf-8"))
    curve = d.get("ramp_curve_snowball_v1", [])
    # Today's send_log for THIS profile's subdomains. Scoped + paged: the old
    # query was op-wide with limit=500, so once the whole operation passed 500
    # sends in a day it silently under-counted sent_today and over-enrolled.
    own = {fd["domain"].lower() for fd in d.get("relay", {}).get("from_domains", [])}
    today_iso = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT00:00:00Z")
    rows = http_get_all(f"send_log?sent_at=gte.{urllib.parse.quote(today_iso)}&select=from_addr")
    sent_by_sub = Counter(
        dom for r in rows
        if (dom := (r.get("from_addr") or "").split("@")[-1].lower()) in own)

    room_by_sub: dict[str, int] = {}
    total_room = 0
    for fd in d.get("relay", {}).get("from_domains", []):
        # Profile JSONs store the verification status as a `verified_at`
        # timestamp (set by Resend onboarding), not as a `verified` bool.
        # Treat any non-empty verified_at as verified.
        if not (fd.get("verified") or fd.get("verified_at")): continue
        w = fd.get("warmup", {})
        day = _warmup_day(w)
        # Look up daily cap from curve
        cap = 0
        for row in sorted(curve, key=lambda r: r["from_day"]):
            if day >= row["from_day"]: cap = row["daily"]
        cap = min(cap, int(w.get("max_daily_sends", cap)))
        sub = fd["domain"]
        sent_today = sent_by_sub.get(sub, 0)
        room = max(0, cap - sent_today)
        room_by_sub[sub] = room
        total_room += room
    return total_room, room_by_sub


def daily_need_for_profile(profile_slug: str) -> int:
    """Gross daily send capacity = sum of per-subdomain warmup caps (NOT
    reduced by what's already been sent today). This is 'the daily need' the
    lead-pool buffer is sized against (BUFFER_DAYS x this). Grows on its own as
    the calendar-based warmup ramp climbs 15 -> 25 -> 35 -> 50."""
    pf = REPO / "profiles" / f"{profile_slug}.json"
    if not pf.exists(): return 0
    d = json.loads(pf.read_text(encoding="utf-8"))
    curve = d.get("ramp_curve_snowball_v1", [])
    total = 0
    for fd in d.get("relay", {}).get("from_domains", []):
        if not (fd.get("verified") or fd.get("verified_at")): continue
        w = fd.get("warmup", {})
        day = _warmup_day(w)
        cap = 0
        for row in sorted(curve, key=lambda r: r["from_day"]):
            if day >= row["from_day"]: cap = row["daily"]
        cap = min(cap, int(w.get("max_daily_sends", cap)))
        total += cap
    return total


def _emails_touched_by_other_brands(profile_slug: str) -> set[str]:
    """Recipient emails that SOME OTHER profile has already emailed (matched via
    send_log.from_addr domain not in this profile's own sending domains).

    Used only by dedupe_cross_brand profiles (lk-advertising): LK shares aureon's
    real-estate source, so most of its leads were already emailed by aureon and the
    send-time anti-double-email guard blocked them. Excluding them at ENROLL time
    gives LK its own lane (only fresh, never-contacted prospects)."""
    try:
        d = json.loads((REPO / "profiles" / f"{profile_slug}.json").read_text(encoding="utf-8"))
        own = {fd["domain"].lower() for fd in d.get("relay", {}).get("from_domains", [])}
    except Exception:
        own = set()
    touched: set[str] = set()
    step, off = 1000, 0
    while True:
        rows = http_get(f"send_log?select=to_addr,from_addr&limit={step}&offset={off}")
        for r in rows:
            fa = (r.get("from_addr") or "").lower()
            dom = fa.split("@")[-1] if "@" in fa else ""
            if dom and dom not in own:
                ta = (r.get("to_addr") or "").lower()
                if ta:
                    touched.add(ta)
        if len(rows) < step:
            break
        off += step
    return touched


def _avg_views_ok(profile_slug: str, p: dict) -> bool:
    """AlgoAlpha only: a creator is enrollable only if their last-10-video average views
    (enriched_context.avg_views_10) is inside the auto-offer window 3,000..100,000.
    Unknown counts as not-ok (never enroll a creator we cannot confirm qualifies).
    Above the window = whale: excluded from auto-enroll, handled as a manual negotiated
    deal (the 35 USD/1k rate would over-commit there). Every other profile is unaffected."""
    if profile_slug != "algoalpha":
        return True
    av = (p.get("enriched_context") or {}).get("avg_views_10")
    try:
        return av not in (None, "") and 3000 <= float(av) <= 100_000
    except (TypeError, ValueError):
        return False


def _runner():
    """Load sequence-runner.py (hyphen in the name blocks a plain import).

    Reused so this script's enrollment gate uses the SAME _clean_company the
    runner uses at send time — a local copy would drift and re-open E1.
    """
    global _RUNNER
    try:
        return _RUNNER
    except NameError:
        pass
    import importlib.util
    spec = importlib.util.spec_from_file_location("_sr", REPO / "sequences" / "sequence-runner.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    _RUNNER = mod
    return mod


def _renders_ok(profile_slug: str, p: dict) -> bool:
    """Only enroll a lead whose {company} will render as a REAL name.

    2026-07-16: _clean_company() (sequence-runner.py:483) blanks any
    single-token company equal to the email domain — 'Firstweber' from
    firstweber.com, 'Isellwausau' from isellwausau.com — and :586 then falls
    back to 'your business', so the subject ships as "a seller test for your
    business". That was 40 of the 57 queued step-1 runs (70%). The copy's whole
    edge is the personalised subject ("a seller test for Keller Williams"
    replied at 5.88%), so send those leads only once `company` is backfilled
    into a real name — do NOT widen the fallback and do NOT edit the copy
    (editing step-1 copy changes the clarity_checks hash, and with the local
    Claude CLI at 401 the judge cannot re-issue a verdict -> every step-1 send
    would be held). All 589 currently-blocked leads have a `website` set, so
    they are recoverable by a backfill, not lost.
    Only gates profiles that opt in via require_real_company.
    """
    if not PROFILE_CFG.get(profile_slug, {}).get("require_real_company"):
        return True
    return bool(_runner()._clean_company(p))


def _source_ok(profile_slug: str, p: dict) -> bool:
    """Drop prospects from lead sources this profile has measured as dead.

    Aureon's replies come only from cross-brokerage agent DIRECTORIES
    (whitestagrealty, fastexpert: 18 replies / 4027 sends = 0.45%). Sources
    that are a SINGLE brokerage's staff roster are salaried agents who never
    reply — blairrg + compass + ascendgroupre + jenniferlandro together are
    0 replies on 960 sends (expected ~13 at the directory rate). A denylist,
    not an allowlist: an unknown new source should still flow through and get
    a fair measurement rather than silently starving enrollment to zero.
    """
    deny = PROFILE_CFG.get(profile_slug, {}).get("source_deny") or []
    src = (p.get("source") or "").lower()
    return not any(d in src for d in deny)


def count_eligible_unenrolled(profile_slug: str, requires_city: bool,
                              requires_first_name: bool = True) -> int:
    SID = get_sequence_id(profile_slug)
    if not SID: return 0
    # Only count active enrollments — cancelled runs from a prior cleanup
    # pass shouldn't block a clean re-enrollment.
    enrolled = {r["prospect_id"] for r in
                http_get_all(f"runs?sequence_id=eq.{SID}&status=in.(queued,running,paused_replied,paused_bounced,completed)&select=prospect_id")}
    rows = http_get_all(
        f"prospects?profile_slug=eq.{profile_slug}&verified=eq.true&unsubscribed=eq.false"
        f"&select=id,email,first_name,company,city,enriched_context,source"
    )
    cross = (_emails_touched_by_other_brands(profile_slug)
             if PROFILE_CFG.get(profile_slug, {}).get("dedupe_cross_brand") else None)
    sup = suppress.load_suppressed()
    n = 0
    for p in rows:
        if p["id"] in enrolled: continue
        if not p.get("company"): continue
        if requires_first_name and not p.get("first_name"): continue
        if requires_city and not p.get("city"): continue
        if cross is not None and (p.get("email") or "").lower() in cross: continue
        if suppress.is_suppressed(p.get("email"), sup): continue
        if not _source_ok(profile_slug, p): continue
        if not _renders_ok(profile_slug, p): continue
        if not _avg_views_ok(profile_slug, p): continue
        n += 1
    return n


def enroll_up_to(profile_slug: str, target: int, requires_city: bool,
                 requires_first_name: bool = True) -> int:
    """Insert run rows for up to `target` eligible unenrolled prospects.
    Returns how many were inserted."""
    if target <= 0: return 0
    SID = get_sequence_id(profile_slug)
    if not SID: return 0
    # Only count active enrollments — cancelled runs from a prior cleanup
    # pass shouldn't block a clean re-enrollment.
    enrolled = {r["prospect_id"] for r in
                http_get_all(f"runs?sequence_id=eq.{SID}&status=in.(queued,running,paused_replied,paused_bounced,completed)&select=prospect_id")}
    rows = http_get_all(
        f"prospects?profile_slug=eq.{profile_slug}&verified=eq.true&unsubscribed=eq.false"
        f"&select=id,email,first_name,company,city,enriched_context,source"
    )
    cross = (_emails_touched_by_other_brands(profile_slug)
             if PROFILE_CFG.get(profile_slug, {}).get("dedupe_cross_brand") else None)
    sup = suppress.load_suppressed()
    eligible = [p for p in rows
                if p["id"] not in enrolled
                and p.get("company")
                and (p.get("first_name") or not requires_first_name)
                and (not requires_city or p.get("city"))
                and (cross is None or (p.get("email") or "").lower() not in cross)
                and not suppress.is_suppressed(p.get("email"), sup)
                and _source_ok(profile_slug, p)
                and _renders_ok(profile_slug, p)
                and _avg_views_ok(profile_slug, p)]
    # Order: proven lead SOURCE first, then leads we can personalize by NAME —
    # send to the best prospects first, leaving company-only / front-desk
    # (info@) leads as overflow. Stable sort keeps prior ordering within a tier.
    # source_prefer is exploitation of what the reply data actually shows
    # (whitestagrealty 1.4%, fastexpert 0.7%); everything not listed still gets
    # enrolled behind them, so untested sources keep being measured rather than
    # frozen out. Profiles with no source_prefer sort exactly as before.
    prefer = PROFILE_CFG.get(profile_slug, {}).get("source_prefer") or []

    def _src_rank(p: dict) -> int:
        src = (p.get("source") or "").lower()
        return next((i for i, s in enumerate(prefer) if s in src), len(prefer))

    eligible.sort(key=lambda p: (_src_rank(p), 0 if (p.get("first_name") or "").strip() else 1))
    # Per-domain cap: don't let one recipient domain dominate a day's enrollment.
    # A single brokerage/firm team page can list 100s of agents; hammering one
    # domain looks like spam and lets one bad domain (a server that rejects us)
    # tank the pool's bounce rate. Spread across domains, named-first preserved.
    # Free/shared providers (gmail etc.) are exempt — they are not a single org.
    _FREE = {"gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com",
             "outlook.com", "live.com", "msn.com", "aol.com", "icloud.com", "me.com",
             "gmx.com", "gmx.net", "gmx.de", "web.de", "t-online.de", "mail.com",
             "protonmail.com", "proton.me", "comcast.net", "verizon.net", "att.net"}
    MAX_PER_DOMAIN = 5
    picked, per_dom = [], {}
    for p in eligible:
        d = (p.get("email") or "").split("@")[-1].lower()
        if d not in _FREE and per_dom.get(d, 0) >= MAX_PER_DOMAIN:
            continue
        picked.append(p)
        per_dom[d] = per_dom.get(d, 0) + 1
        if len(picked) >= target:
            break
    eligible = picked
    # Find any prior cancelled runs for these prospects — we'll PATCH those
    # back to queued instead of INSERTing (the runs table has a unique key
    # on (sequence_id, prospect_id) that doesn't care about status).
    eligible_ids = [p["id"] for p in eligible]
    cancelled_run_by_pid: dict[str, str] = {}
    for i in range(0, len(eligible_ids), 50):
        batch = ",".join(eligible_ids[i:i+50])
        for r in http_get(
            f"runs?sequence_id=eq.{SID}&status=eq.cancelled"
            f"&prospect_id=in.({batch})&select=id,prospect_id"
        ):
            cancelled_run_by_pid[r["prospect_id"]] = r["id"]
    # If we're resurrecting, the recipient may already have received some
    # steps before the cancel. Look up max(step_n) in send_log scoped to
    # THIS run_id (not by to_addr, which could pick up cross-profile sends
    # if the same email ever existed in another profile's send_log) so we
    # resume at last_sent_step + 1 instead of restarting at step 1 (which
    # would just bounce off check_recipient_dedup forever).
    resume_step_by_pid: dict[str, int] = {}
    for pid, rid in cancelled_run_by_pid.items():
        rows = http_get(
            f"send_log?run_id=eq.{rid}"
            f"&order=step_n.desc&select=step_n&limit=1"
        )
        if rows and rows[0].get("step_n"):
            resume_step_by_pid[pid] = int(rows[0]["step_n"])
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    n = 0
    for p in eligible:
        try:
            if p["id"] in cancelled_run_by_pid:
                # Resurrect the cancelled run instead of inserting a duplicate.
                # Resume at next-step-after-last-send so we don't re-fire a
                # step the recipient already received.
                rid = cancelled_run_by_pid[p["id"]]
                last_sent = resume_step_by_pid.get(p["id"], 0)
                resume_step = min(last_sent + 1, 7)  # variants top out at step 7
                if last_sent >= 7:
                    # Already finished the sequence — mark completed, skip.
                    urllib.request.urlopen(urllib.request.Request(
                        f"{URL}/rest/v1/runs?id=eq.{rid}", method="PATCH",
                        data=json.dumps({"status": "completed"}).encode(),
                        headers={**H_W, "Prefer": "return=minimal"},
                    ), timeout=60)
                    continue
                req = urllib.request.Request(
                    f"{URL}/rest/v1/runs?id=eq.{rid}",
                    method="PATCH",
                    data=json.dumps({
                        "status": "queued",
                        "current_step": resume_step,
                        "next_send_at": now,
                    }).encode(),
                    headers={**H_W, "Prefer": "return=minimal"},
                )
                urllib.request.urlopen(req, timeout=60)
            else:
                http_post("runs", {
                    "sequence_id":  SID,
                    "prospect_id":  p["id"],
                    "status":       "queued",
                    "current_step": 1,
                    "next_send_at": now,
                })
            n += 1
        except urllib.error.HTTPError as e:
            print(f"  ! enroll error for {p['email']}: {e.code} {e.read().decode()[:200]}")
    return n


def fill_profile(profile_slug: str, *, do_scrape: bool, dry: bool) -> dict:
    cfg = PROFILE_CFG.get(profile_slug)
    if not cfg:
        print(f"  ! {profile_slug}: no PROFILE_CFG entry")
        return {"profile": profile_slug, "skipped": "no_cfg"}

    # Skip profiles deactivated in their profile JSON (e.g. subdomains
    # reallocated to another profile). Reversible: set active=true to revive.
    pf = REPO / "profiles" / f"{profile_slug}.json"
    try:
        if pf.exists() and json.loads(pf.read_text(encoding="utf-8")).get("active") is False:
            print(f"\n=== {profile_slug} === (inactive — skipped)")
            return {"profile": profile_slug, "skipped": "inactive"}
    except Exception:
        pass

    print(f"\n=== {profile_slug} ===")
    total_room, room_by_sub = cap_target_for_profile(profile_slug)
    daily_need = daily_need_for_profile(profile_slug)
    buffer_target = BUFFER_DAYS * daily_need
    eligible_start = count_eligible_unenrolled(profile_slug, cfg["requires_city"], cfg.get("requires_first_name", True))
    print(f"  today room across sds : {total_room}  ({room_by_sub})")
    print(f"  daily need / buffer    : {daily_need} / {buffer_target}  ({BUFFER_DAYS}x)")
    print(f"  eligible unenrolled   : {eligible_start}")
    # Scrape to keep the pool stocked to BUFFER_DAYS x the daily need, so it
    # never starves as the warmup ramp raises the daily cap. Enrollment below
    # still only consumes today's room — the rest stays as a ready buffer.
    needed = max(0, buffer_target - eligible_start)
    print(f"  scrape target shortfall: {needed}  (to {buffer_target})")

    if needed > 0 and do_scrape and not cfg.get("import_only"):
        last_eligible = eligible_start
        for pass_n in range(1, MAX_PASSES + 1):
            print(f"  -- scrape pass {pass_n}/{MAX_PASSES}")
            # Steps 1+2 are team-page sourcing and need a niche_slug; profiles
            # whose sourcing is creator_scrapers-only (dorian) set niche_slug
            # None and skip straight to step 3.
            if cfg["niche_slug"]:
                # 1. Seed-discovery first so lead_scrape sees fresh URLs this pass.
                #    Uses ddgs multi-engine search + playwright_stealth fallback.
                #    No-op if the niche has no search_queries block.
                rc, _ = run_subprocess(
                    "sequences/seed_discover.py",
                    ["--niche", cfg["niche_slug"], "--max-per-query", "5"],
                )
                print(f"     seed_discover rc={rc}")
                # 2. Team-page scrape over the (now possibly grown) seeds list.
                rc, tail = run_subprocess(
                    "sequences/lead_scrape.py", ["run", cfg["niche_slug"]]
                )
                print(f"     lead_scrape rc={rc}")
            for s, args in cfg["creator_scrapers"]:
                rc, _ = run_subprocess(s, args)
                print(f"     {Path(s).name} rc={rc}")
            # Creator scrapers run --no-smtp (fast, unverified). The VPS has port 25
            # blocked so no live SMTP RCPT is possible; MX-verify the fresh creator
            # leads (MX + heuristics, no port 25) so they become eligible. Same
            # confidence tier the team-page brands already send on.
            if cfg["creator_scrapers"]:
                rc, _ = run_subprocess("sequences/promote_mx.py",
                                       ["--profile", profile_slug, "--creators-only"])
                print(f"     promote_mx rc={rc}")
            if cfg["backfill_script"]:
                rc, _ = run_subprocess(cfg["backfill_script"], cfg.get("backfill_args", []))
                print(f"     {Path(cfg['backfill_script']).name} rc={rc}")
            new_eligible = count_eligible_unenrolled(profile_slug, cfg["requires_city"], cfg.get("requires_first_name", True))
            delta = new_eligible - last_eligible
            print(f"     eligible now = {new_eligible}  (delta {delta:+d}, target {buffer_target})")
            last_eligible = new_eligible
            if new_eligible >= buffer_target: break
            if delta <= 0:
                print(f"     no progress, stopping early")
                break

    final_eligible = count_eligible_unenrolled(profile_slug, cfg["requires_city"], cfg.get("requires_first_name", True))
    enrolled = 0
    if not dry:
        enrolled = enroll_up_to(profile_slug, total_room, cfg["requires_city"], cfg.get("requires_first_name", True))
    print(f"  enrolled now           : {enrolled}")
    return {
        "profile": profile_slug,
        "room_target":  total_room,
        "eligible_start": eligible_start,
        "eligible_final": final_eligible,
        "enrolled":     enrolled,
    }


def _per_brand_sender_tasks() -> list[str]:
    """Names of the per-brand sender tasks (LES-sequence-runner-<brand>).
    Empty pre-cutover / non-Windows."""
    if not sys.platform.startswith("win"):
        return []
    try:
        out = subprocess.check_output(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-ScheduledTask -TaskName 'LES-sequence-runner-*' "
             "-ErrorAction SilentlyContinue).TaskName"],
            text=True, stderr=subprocess.DEVNULL, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except Exception:
        return []


def trigger_senders(profiles: list[str]) -> None:
    """Fire the sender(s) so newly-enrolled runs go out promptly.

    Per-brand cutover (2026-06-16): each active brand runs its OWN always-on
    LES-sequence-runner-<brand> task. We must NOT run a bare global
    `sequence-runner.py tick` here — that would double-process the same due runs
    alongside those tasks and DOUBLE-SEND. Instead Start each brand's own task
    (Start-ScheduledTask respects MultipleInstances=IgnoreNew, so a brand already
    mid-tick is not double-started). Falls back to ONE global tick only when no
    per-brand tasks exist (pre-cutover / non-Windows / VPS)."""
    tasks = set(_per_brand_sender_tasks())
    if tasks:
        for slug in profiles:
            tn = f"LES-sequence-runner-{slug}"
            if tn in tasks:
                try:
                    subprocess.run(
                        ["powershell.exe", "-NoProfile", "-Command",
                         f"Start-ScheduledTask -TaskName '{tn}'"],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                        timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                    print(f"  triggered {tn}")
                except Exception as e:
                    print(f"  ! trigger {tn} failed: {e}")
    else:
        rc, _ = run_subprocess("sequences/sequence-runner.py", ["tick"])
        print(f"  global runner rc={rc}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", help="only run for one profile")
    ap.add_argument("--no-scrape", action="store_true",
                    help="skip scraping; only backfill+enroll")
    ap.add_argument("--dry", action="store_true",
                    help="plan only; do not enroll or tick")
    args = ap.parse_args()

    profiles = [args.profile] if args.profile else list(PROFILE_CFG.keys())

    # Phase 1 — enroll from the already-eligible pool + tick FIRST, before any
    # scraping. Root cause of past "0 enrolled" days: the slow scrape phase ate
    # the scheduled task's 15-min budget and the task was killed (0x41306)
    # before enroll/tick ever ran. Front-loading the fast, essential work
    # guarantees the daily enrollment lands even if Phase 2 runs long or is
    # killed. Skipped when --no-scrape (Phase 2 already does enroll-only then).
    if not args.dry and not args.no_scrape:
        print("=== phase 1: enroll from existing pool (no scrape) ===")
        for p in profiles:
            fill_profile(p, do_scrape=False, dry=False)
        print("\n=== phase 1: fire per-brand senders ===")
        trigger_senders(profiles)

    # Phase 2 — scrape to top the pool up for next time, enrolling new finds.
    results = []
    for p in profiles:
        results.append(fill_profile(p, do_scrape=not args.no_scrape, dry=args.dry))

    # Fire senders so anything newly enrolled goes out promptly (per-brand tasks,
    # IgnoreNew-safe; NOT a global tick that would double-process post-cutover).
    if not args.dry:
        print("\n=== fire per-brand senders ===")
        trigger_senders(profiles)

    print("\n=== SUMMARY ===")
    for r in results:
        print(f"  {r['profile']:18s} room={r.get('room_target','?'):3} "
              f"eligible {r.get('eligible_start','?')} -> {r.get('eligible_final','?')}  "
              f"enrolled={r.get('enrolled','?')}")

    # Persist a one-line-per-profile audit trail so the user can review
    # daily history without grepping the scheduled-task transcript.
    log_dir = REPO / "warmup-state"
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / "daily-fill-and-enroll.jsonl"
    stamp = dt.datetime.now(dt.timezone.utc).isoformat()
    with log_file.open("a", encoding="utf-8") as f:
        for r in results:
            row = {"ts": stamp, **r}
            f.write(json.dumps(row) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
