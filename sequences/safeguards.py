"""safeguards.py - live runtime guards that prevent the autopilot from
burning the Resend subdomains.

Five guards are checked on every send (in order; first failure aborts
that send-attempt but does NOT cancel the run, so it retries next tick):

  GUARD 1 (subdomain reputation - live)
      Compute the rolling-24h bounce rate AND complaint rate for the
      sending subdomain from send_log directly. If either crosses the
      profile's auto_pause_thresholds, the subdomain is marked
      `paused_by_safeguard` in the profile JSON and skipped until
      manually reset. This replaces the cached `reputation` snapshot
      that was supposed to be filled by the (never-deployed) webhook.

  GUARD 2 (per-recipient + step dedup)
      Same (profile, recipient_email, step_n) cannot be sent twice.
      Catches double-enrollment bugs and orchestrator races.

  GUARD 3 (global daily cap - hard backstop)
      Per-profile hard ceiling so a curve/orchestrator bug can't 10x
      the daily volume. Default backstop = 2x the sum of subdomain
      caps; tunable in safeguards-config.json.

  GUARD 4 (rate limiter)
      Per-subdomain: min seconds between any two sends from the
      same subdomain. Default 8s = max ~7 sends/min/subdomain. Avoids
      Gmail/Outlook burst-pattern penalization.

  GUARD 5 (quiet hours)
      No sends between QUIET_START and QUIET_END (server-local time).
      Default 21:00 - 07:00. Cold sends at 3am scream spammer.

  GUARD 6 (reply-to deliverable)
      The bound persona's reply_to domain must publish an MX (or an
      A record usable as implicit MX). A reply address that bounces
      means the client never receives the lead, and provisioning only
      ever verifies the SENDING domain, so nothing else catches it.

If ANY guard fails for >= ALERT_THRESHOLD distinct subdomains in a
single tick, send_alert() ships an email to info@aureonglobal.de via
the same path daily-report.py uses (Resend, reports@hi.aureonglobal.de).
Idempotent: re-tripping the same guard within the alert-cooldown
window does not re-spam.
"""
from __future__ import annotations
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SAFE_STATE = REPO / "warmup-state" / "safeguards.state.json"
SAFE_STATE.parent.mkdir(exist_ok=True)
LOG_FILE   = REPO / "warmup-state" / "safeguards.log.jsonl"

# ── Thresholds (override via warmup-state/safeguards-config.json) ──
DEFAULT_CONFIG = {
    # Bounce/complaint reputation guard. Computed as a ROLLING AVERAGE over
    # `bounce_window_hours` (3 days), not instantly — a single bounce on a
    # tiny warmup day (1/15 = 6.7%) must not pause a subdomain. The sample
    # floor enforces that: with limit 5% we need >=20 sends in the window
    # before the rate can pause anything, so 1 bounce never trips during ramp.
    "bounce_window_hours":      72,     # 3-day rolling window for the rate
    "bounce_rate_limit":        0.05,   # 5% rolling bounce -> pause subdomain
    "complaint_rate_limit":     0.001,  # 0.1% rolling complaint -> pause
    "min_sample_size_for_rate": 30,     # need >=30 sends in window before judging a rate
    "min_bounces_to_block":     4,      # AND >=4 absolute bounces before the rate can pause.
                                        # Without this, 2 bounces in the first 20 warmup sends
                                        # (=10%) lock a subdomain, and a locked subdomain can
                                        # never send enough to dilute them -> permanent deadlock.
                                        # 1-3 bounces is warmup noise; 4+ at >5% is a real list problem.
    # Legacy keys (still honored as fallback if an old override file sets them)
    "bounce_rate_24h_limit":    0.05,
    "complaint_rate_24h_limit": 0.001,
    "global_daily_cap_multiplier": 2.0, # backstop = 2x sum-of-curve
    "min_seconds_between_subdomain_sends": 8,
    "quiet_hour_start": 21,             # 21:00 local
    "quiet_hour_end":   7,              # 07:00 local
    "alert_cooldown_minutes": 60,       # don't re-alert same guard inside this
}


def _load_config() -> dict:
    """Merge defaults with optional override file."""
    cfg = dict(DEFAULT_CONFIG)
    override = SAFE_STATE.parent / "safeguards-config.json"
    if override.exists():
        try:
            cfg.update(json.loads(override.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"  ! safeguards-config.json parse error: {e}")
    return cfg


def _load_state() -> dict:
    if not SAFE_STATE.exists(): return {}
    try:
        return json.loads(SAFE_STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _atomic_write_text(path: Path, text: str) -> None:
    """Write via a per-process temp file + os.replace (atomic on the same volume),
    so concurrent per-brand runners sharing this file can never read a half-written,
    corrupt JSON. The PID-suffixed temp avoids cross-process temp collisions.
    2026-06-16 (per-brand runner cutover)."""
    tmp = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _save_state(s: dict) -> None:
    _atomic_write_text(SAFE_STATE, json.dumps(s, indent=2))


_LOG_MAX_BYTES = 20 * 1024 * 1024  # rotate at 20MB (was unbounded -> grew to 271MB)


def _rotate_log_if_big() -> None:
    """Size-cap the guard log so it can't grow without bound (it was 271MB).
    Rotate to a single .1 backup. Best-effort + race-tolerant: under the
    per-brand runner cutover several processes append concurrently, so the
    os.replace may already have been done by a peer — that's fine."""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > _LOG_MAX_BYTES:
            os.replace(LOG_FILE, LOG_FILE.with_suffix(".jsonl.1"))
    except Exception:
        pass


def _log(event: dict) -> None:
    event["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()
    _rotate_log_if_big()
    try:
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass  # diagnostic log must never break a send


# ── Guard 1: live subdomain reputation ────────────────────────────────────

def check_subdomain_reputation(supa_client, subdomain: str, cfg: dict | None = None) -> tuple[bool, str | None]:
    """Live ROLLING-AVERAGE reputation check for ONE subdomain over
    `bounce_window_hours` (default 72h = 3 days), not instant. Returns
    (ok, reason_if_blocked). Reads send_log directly so it does not depend
    on the Resend webhook (which is not deployed).

    The 3-day window + sample floor exist so a single bounce on a low-volume
    warmup day (e.g. 1/15 = 6.7%) cannot pause a subdomain — the rate only
    pauses sending once it stays elevated across a meaningful sample."""
    cfg = cfg or _load_config()
    window_h = int(cfg.get("bounce_window_hours", 72))
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=window_h)).isoformat()
    rows = supa_client.get(
        f"/send_log?from_addr=ilike.*@{subdomain}&sent_at=gte.{urllib.parse.quote(since)}"
        f"&select=delivered,bounced,complained,to_addr&limit=1000"
    ).json()
    # Exclude self-test sends (to our own infra domains) from the reputation
    # calc — a test send to info+livetest@aureonglobal.de that bounces is OUR
    # SMTP not accepting a plus-alias, not a real-recipient deliverability
    # signal. Including those poisons rep and stalls real outreach.
    OWN_DOMAINS = ("aureonglobal.de", "algoalpha.io", "atalsolidrocks.io")
    rows = [r for r in rows
            if not any((r.get("to_addr") or "").lower().endswith("@" + d)
                       or d in (r.get("to_addr") or "").lower()
                       for d in OWN_DOMAINS)]
    n = len(rows)
    if n < cfg["min_sample_size_for_rate"]:
        return True, None  # too little data to judge
    bounced    = sum(1 for r in rows if r.get("bounced"))
    complained = sum(1 for r in rows if r.get("complained"))
    br = bounced / n
    cr = complained / n
    # New keys win; fall back to the legacy *_24h_limit names for old overrides.
    br_lim = float(cfg.get("bounce_rate_limit", cfg.get("bounce_rate_24h_limit", 0.05)))
    cr_lim = float(cfg.get("complaint_rate_limit", cfg.get("complaint_rate_24h_limit", 0.001)))
    min_bounces = int(cfg.get("min_bounces_to_block", 4))
    if br > br_lim and bounced >= min_bounces:
        return False, f"bounce_{window_h}h={br:.1%} > {br_lim:.0%} on {subdomain} ({bounced}/{n} over {window_h}h)"
    if cr > cr_lim:
        return False, f"complaint_{window_h}h={cr:.2%} > {cr_lim:.1%} on {subdomain} ({complained}/{n} over {window_h}h)"
    return True, None


# ── Guard 2: per-recipient + step dedup ────────────────────────────────────

_PROFILE_ROOT_CACHE: dict[str, str] = {}


def _profile_sending_root(profile_slug: str) -> str | None:
    """The registered sending domain for a profile (e.g. lk-advertising.site),
    derived from its from_domains. Cached. Used to scope recipient dedup to THIS
    profile's own sends so independent brands can each reach a shared ICP."""
    if profile_slug in _PROFILE_ROOT_CACHE:
        return _PROFILE_ROOT_CACHE[profile_slug] or None
    root = ""
    try:
        pp = REPO / "profiles" / f"{profile_slug}.json"
        if pp.exists():
            cfg = json.loads(pp.read_text(encoding="utf-8"))
            fds = [d.get("domain", "") for d in (cfg.get("relay", {}).get("from_domains") or [])]
            if fds:
                root = ".".join(fds[0].split(".")[1:])  # strip the subdomain label
    except Exception:
        root = ""
    _PROFILE_ROOT_CACHE[profile_slug] = root
    return root or None


def check_recipient_dedup(supa_client, profile_slug: str, to_addr: str, step_n: int) -> tuple[bool, str | None]:
    """Has THIS profile already sent this exact step to this recipient?
    True = ok-to-send, False = duplicate.

    Scoped to the profile's OWN sending domains so independent brands can each
    contact a shared ICP — a recipient emailed by brand A is NOT blocked for
    brand B. (Previously this matched ANY prior send to the address, which
    starved brands sharing an ICP, e.g. two real-estate campaigns.)"""
    root = _profile_sending_root(profile_slug)
    q = (f"/send_log?to_addr=eq.{urllib.parse.quote(to_addr.lower())}"
         f"&step_n=eq.{step_n}"
         f"&persona_slug=not.is.null"
         f"&select=id,sent_at,from_addr&limit=5")
    if root:
        q += f"&from_addr=ilike.*{root}"   # only THIS profile's subdomains
    rows = supa_client.get(q).json()
    if rows:
        return False, f"dup: {to_addr} already received step {step_n} from {profile_slug} (send_log {rows[0]['id'][:8]} at {rows[0]['sent_at'][:19]})"
    return True, None


# ── Guard 3: global daily cap (backstop) ──────────────────────────────────

def check_global_daily_cap(supa_client, profile_slug: str, profile_config: dict, cfg: dict | None = None) -> tuple[bool, str | None]:
    """Hard backstop on per-profile daily volume. Sums today's sends for
    every subdomain belonging to this profile, compares against
    multiplier * sum-of-curve-caps."""
    cfg = cfg or _load_config()
    multiplier = float(cfg["global_daily_cap_multiplier"])
    sds = [d["domain"] for d in (profile_config.get("relay", {}).get("from_domains") or [])
           if d.get("verified_at")]
    if not sds: return True, None
    # Sum-of-curve-caps for today
    from profile_lib import daily_target_for_domain
    sum_caps = sum(
        daily_target_for_domain(profile_config, d)
        for d in (profile_config.get("relay", {}).get("from_domains") or [])
        if d.get("verified_at")
    )
    if sum_caps == 0:
        return True, None
    backstop = int(sum_caps * multiplier)
    # Today's send count
    today_start = dt.datetime.now(dt.timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    or_clause = ",".join(f"from_addr.ilike.*@{s}" for s in sds)
    rows = supa_client.get(
        f"/send_log?sent_at=gte.{urllib.parse.quote(today_start)}"
        f"&or=({or_clause})&select=id&limit=2000"
    ).json()
    n = len(rows)
    if n >= backstop:
        return False, f"global_cap: {n} sends today >= {backstop} ({multiplier}x curve-sum) for {profile_slug}"
    return True, None


# ── Guard 4: rate limiter ──────────────────────────────────────────────────

def check_rate_limit(supa_client, subdomain: str, cfg: dict | None = None) -> tuple[bool, str | None]:
    """Min seconds between two sends from the same subdomain. Prevents
    burst-pattern penalization at Gmail/Outlook."""
    cfg = cfg or _load_config()
    min_gap = int(cfg["min_seconds_between_subdomain_sends"])
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=min_gap)).isoformat()
    rows = supa_client.get(
        f"/send_log?from_addr=ilike.*@{subdomain}&sent_at=gte.{urllib.parse.quote(since)}"
        f"&select=sent_at&order=sent_at.desc&limit=1"
    ).json()
    if rows:
        return False, f"rate_limit: last send on {subdomain} at {rows[0]['sent_at'][:19]} (<{min_gap}s ago)"
    return True, None


# ── Guard 5: send window (recipient-LOCAL hours + weekday-only) ────────────
#
# Hard rule: only send between 08:00-17:00 in the RECIPIENT'S local time,
# Monday-Friday in their local week. Resolved per prospect via
# prospect_timezone.resolve_timezone() so a Texas agent gets sent at her
# 8 AM CDT (= 15:00 CEST server) while a Bern manager gets sent at his
# 8 AM CET (= 8:00 CEST server) — same code, different local clocks.
#
# The profile.send_window block now holds DEFAULTS (used when the
# prospect's timezone can't be resolved):
#   - local_hour_start: 8
#   - local_hour_end:   17
#   - weekdays_only:    true
#   - default_timezone: "America/New_York" / "Europe/Zurich" / ...
#
# The legacy hour_start_server_local / hour_end_server_local fields are
# IGNORED — they assumed all prospects shared one timezone, which is
# wrong for any client with geographically-spread targets.

try:
    from zoneinfo import ZoneInfo
    _ZONEINFO_OK = True
except ImportError:  # Python < 3.9 fallback — should not happen on this stack
    ZoneInfo = None  # type: ignore
    _ZONEINFO_OK = False

WEEKDAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def check_send_window(profile_config: dict | None = None,
                       prospect: dict | None = None,
                       cfg: dict | None = None) -> tuple[bool, str | None]:
    """Block sends unless current time, in the RECIPIENT's local timezone,
    is a weekday 08:00-17:00.

    Falls back to server-local time if zoneinfo unavailable. Profile
    config supplies the hour-window defaults (overridable per profile)
    and a default_timezone used when the prospect's timezone can't be
    resolved (no city, unknown TLD, etc)."""
    cfg = cfg or _load_config()
    win = (profile_config or {}).get("send_window") or {}

    # Per-profile window OR system-wide defaults
    start = int(win.get("local_hour_start", 8))
    end   = int(win.get("local_hour_end",   17))
    weekdays_only = bool(win.get("weekdays_only", True))

    # Resolve recipient timezone. Lazy import to avoid hard dep at module load.
    tz_name = "UTC"
    if _ZONEINFO_OK and prospect:
        try:
            from prospect_timezone import resolve_timezone
            tz_name = resolve_timezone(prospect, profile_config or {})
        except Exception as e:
            print(f"  ! tz resolution failed: {e} - using server-local")
            tz_name = None  # signal to fall back below

    if _ZONEINFO_OK and tz_name and tz_name != "UTC":
        try:
            now_local = dt.datetime.now(ZoneInfo(tz_name))
        except Exception:
            now_local = dt.datetime.now()
            tz_name = "server-local"
    else:
        now_local = dt.datetime.now()
        tz_name = tz_name or "server-local"

    wd = now_local.weekday()
    h = now_local.hour

    # Weekday gate (recipient's local week)
    if weekdays_only and wd >= 5:
        return False, (f"weekend_off: recipient-local {WEEKDAY_NAMES[wd]} "
                       f"in {tz_name}, sends restricted to Mon-Fri")

    # Hour gate (recipient's local clock)
    in_window = (start <= h < end) if start <= end else (h >= start or h < end)
    if not in_window:
        return False, (f"out_of_window: recipient-local {h:02d}:00 "
                       f"in {tz_name} outside [{start:02d}-{end:02d}]")
    return True, None


# Back-compat alias for any legacy caller. With no profile passed it does
# server-local 8-17, which matches the new semantics for prospects whose
# timezone couldn't be resolved.
def check_quiet_hours(cfg: dict | None = None) -> tuple[bool, str | None]:
    return check_send_window(cfg=cfg)


# ── Guard 0: no-solicitation (recipient's site forbids marketing/outreach) ──

def check_no_solicitation(prospect: dict | None = None) -> tuple[bool, str | None]:
    """Block the send if this prospect's website declared it does not accept
    unsolicited marketing / outreach email (EN notices or the German Impressum
    anti-Werbung clause). The flag is set at scrape time (compliance.forbids_outreach)
    into prospects.custom_fields.no_solicitation; this is the send-time backstop so
    a flagged prospect can never be emailed even if it was enrolled before the gate."""
    cf = ((prospect or {}).get("custom_fields") or {})
    if cf.get("no_solicitation"):
        who = (prospect or {}).get("email", "?")
        label = cf.get("no_solicitation_label", "flagged")
        return False, f"no_solicitation: {who} site forbids marketing email ({label})"
    return True, None


# ── Guard 6: reply-to deliverability (the reply address must accept mail) ──
#
# A persona whose reply_to domain has no MX (and no implicit-MX A record) sends
# prospects a Reply-To that bounces, so the client never gets the lead. Caught
# live on atalsolidrocks 2026-07-27: 12 personas replied to info@atalsolidrocks.io,
# a domain with no MX and no A record at all. Nothing had shipped yet, but the
# profile was one activation away from mailing 320 prospects an unreachable
# reply address. Provisioning verifies the SENDING domain at Resend and never
# checks the RECEIVING one, so this class of bug is invisible until a lead is lost.
#
# Fails CLOSED on a definitive "domain accepts no mail" answer (NXDOMAIN, or
# NoAnswer for both MX and A) and OPEN on resolver trouble (timeout, servfail) —
# a flaky resolver must not halt every brand's sending.

_REPLYTO_MX_CACHE: dict[str, tuple[float, bool, str]] = {}   # domain -> (checked_ts, ok, detail)
_REPLYTO_TTL_OK   = 6 * 3600   # a working MX rarely disappears; re-check every 6h
_REPLYTO_TTL_BAD  = 900        # re-check a broken one every 15min so a fix unblocks fast


def _domain_accepts_mail(domain: str) -> tuple[bool, str]:
    """True if `domain` publishes an MX, or an A/AAAA usable as implicit MX
    (RFC 5321 §5.1). Cached; see TTLs above."""
    now = time.time()
    hit = _REPLYTO_MX_CACHE.get(domain)
    if hit and (now - hit[0]) < (_REPLYTO_TTL_OK if hit[1] else _REPLYTO_TTL_BAD):
        return hit[1], hit[2]

    import dns.resolver  # local import: never break module load if absent
    res = dns.resolver.Resolver()
    res.lifetime = res.timeout = 5.0
    try:
        if res.resolve(domain, "MX"):
            out = (True, "MX present")
    except dns.resolver.NoAnswer:
        try:
            res.resolve(domain, "A")
            out = (True, "no MX, implicit-MX A record")
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            out = (False, "no MX and no A record")
        except Exception as e:
            # The A lookup failed without answering (timeout/servfail). We know
            # there is no MX but NOT that there is no A, so this is not a verdict.
            return True, f"dns inconclusive on A ({type(e).__name__}) - allowing"
    except dns.resolver.NXDOMAIN:
        out = (False, "domain does not exist")
    except Exception as e:
        # Resolver trouble, not a verdict — fail OPEN and do not cache.
        return True, f"dns inconclusive ({type(e).__name__}) - allowing"

    _REPLYTO_MX_CACHE[domain] = (now, out[0], out[1])
    return out


def check_reply_to_deliverable(profile_config: dict | None = None,
                               subdomain: str | None = None) -> tuple[bool, str | None]:
    """Block the send if the bound persona's reply_to domain cannot receive mail.

    The persona is derived from `subdomain` using the same 1:1 binding the
    rotation enforces (a subdomain's persona is the one whose from_addr lives
    on it), so this needs no new argument threaded through check_all()."""
    if not profile_config or not subdomain:
        return True, None
    persona = next((p for p in profile_config.get("personas", [])
                    if (p.get("from_addr", "").split("@")[-1].lower() == subdomain.lower())), None)
    if not persona:
        return True, None
    reply_to = (persona.get("reply_to") or "").strip()
    if "@" not in reply_to:
        return True, None
    domain = reply_to.rsplit("@", 1)[1].lower()
    ok, detail = _domain_accepts_mail(domain)
    if not ok:
        return False, (f"dead_reply_to: persona {persona.get('slug')} replies to "
                       f"{reply_to} but {domain} {detail} - the client would never "
                       f"receive this lead")
    return True, None


# ── Unified check ──────────────────────────────────────────────────────────

def check_all(*, supa_client, profile_slug: str, profile_config: dict,
              subdomain: str, to_addr: str, step_n: int,
              prospect: dict | None = None) -> tuple[bool, str | None, str | None]:
    """Run all five guards in order; return (ok, reason, guard_name).
    First failure wins. The guard_name is returned separately so the
    caller can route alerts without parsing the reason string.

    `prospect` is required for accurate per-recipient-timezone enforcement
    of the 08:00-17:00 local-time send window; without it the send-window
    guard falls back to server-local time."""
    cfg = _load_config()
    for guard, args in [
        (check_no_solicitation,       {"prospect": prospect}),
        (check_reply_to_deliverable,  {"profile_config": profile_config, "subdomain": subdomain}),
        (check_send_window,           {"profile_config": profile_config, "prospect": prospect, "cfg": cfg}),
        (check_subdomain_reputation,  {"supa_client": supa_client, "subdomain": subdomain, "cfg": cfg}),
        (check_global_daily_cap,      {"supa_client": supa_client, "profile_slug": profile_slug, "profile_config": profile_config, "cfg": cfg}),
        (check_rate_limit,            {"supa_client": supa_client, "subdomain": subdomain, "cfg": cfg}),
        (check_recipient_dedup,       {"supa_client": supa_client, "profile_slug": profile_slug, "to_addr": to_addr, "step_n": step_n}),
    ]:
        try:
            ok, reason = guard(**args)
        except Exception as e:
            ok, reason = True, None  # never crash the runner on a guard exception
            print(f"  ! safeguard {guard.__name__} crashed: {e} - allowing send through")
        if not ok:
            _log({"event": "guard_blocked", "guard": guard.__name__,
                  "profile": profile_slug, "subdomain": subdomain,
                  "to_addr": to_addr, "step_n": step_n, "reason": reason})
            return False, reason, guard.__name__
    return True, None, None


# ── Alert sender (reuses Resend infra) ────────────────────────────────────

ALERT_STATE = SAFE_STATE.parent / "safeguards.alerts.state.json"


def _should_alert(guard_key: str, cooldown_min: int) -> bool:
    """Cooldown: don't re-alert the same guard inside the window."""
    state = {}
    if ALERT_STATE.exists():
        try: state = json.loads(ALERT_STATE.read_text(encoding="utf-8"))
        except Exception: state = {}
    now = dt.datetime.now(dt.timezone.utc)
    last = state.get(guard_key)
    if last:
        try:
            last_dt = dt.datetime.fromisoformat(last)
            if (now - last_dt).total_seconds() < cooldown_min * 60:
                return False
        except Exception:
            pass
    state[guard_key] = now.isoformat()
    _atomic_write_text(ALERT_STATE, json.dumps(state, indent=2))
    return True


def send_alert(*, subject: str, body_text: str, body_html: str | None = None) -> None:
    """CONSOLIDATED 2026-06-16: no longer emails per event. Safeguard trips were
    flooding info@; they now go into the ops_digest buffer and surface as ONE
    "System events" section in the daily report. The guard still BLOCKS the send
    in real time — only the notification is consolidated. (Signature unchanged so
    alert_on_block / domain-check callers keep working.)"""
    try:
        import ops_digest
        ops_digest.record(source="safeguard", subject=subject, detail=body_text,
                          severity="warn")
    except Exception as e:
        print(f"  ! ops_digest.record failed (safeguard): {e}")


def alert_on_block(*, guard_name: str, profile_slug: str, subdomain: str,
                    reason: str) -> None:
    """Convenience: cooldown-aware alert for a tripped guard."""
    cfg = _load_config()
    # Only alert on the high-severity guards. Rate-limit and quiet-hours
    # are normal operating behavior and would spam the inbox.
    if guard_name not in ("check_subdomain_reputation", "check_global_daily_cap"):
        return
    key = f"{guard_name}:{profile_slug}:{subdomain}"
    if not _should_alert(key, cfg["alert_cooldown_minutes"]):
        return
    send_alert(
        subject=f"{guard_name.replace('check_', '')} on {subdomain}",
        body_text=(f"A runtime safeguard tripped while sending.\n\n"
                   f"profile     = {profile_slug}\n"
                   f"subdomain   = {subdomain}\n"
                   f"guard       = {guard_name}\n"
                   f"reason      = {reason}\n\n"
                   f"The runner has paused this send-attempt. If the guard keeps "
                   f"firing for the same subdomain, investigate the bounce/complaint "
                   f"signal at the Resend dashboard and pause the subdomain manually "
                   f"in profiles/{profile_slug}.json relay.from_domains[*].warmup.enabled = false."),
    )
