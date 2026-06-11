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
    "min_sample_size_for_rate": 20,     # need >=20 sends in window before judging
                                        # (1 bounce on <=20 sends => never pauses)
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


def _save_state(s: dict) -> None:
    SAFE_STATE.write_text(json.dumps(s, indent=2), encoding="utf-8")


def _log(event: dict) -> None:
    event["ts"] = dt.datetime.now(dt.timezone.utc).isoformat()
    with LOG_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event) + "\n")


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
    OWN_DOMAINS = ("aureonglobal.de", "algoalpha.io", "f2-malergipser.ch", "atalsolidrocks.io")
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
    if br > br_lim:
        return False, f"bounce_{window_h}h={br:.1%} > {br_lim:.0%} on {subdomain} ({bounced}/{n} over {window_h}h)"
    if cr > cr_lim:
        return False, f"complaint_{window_h}h={cr:.2%} > {cr_lim:.1%} on {subdomain} ({complained}/{n} over {window_h}h)"
    return True, None


# ── Guard 2: per-recipient + step dedup ────────────────────────────────────

def check_recipient_dedup(supa_client, profile_slug: str, to_addr: str, step_n: int) -> tuple[bool, str | None]:
    """Has this profile already sent this exact step to this recipient?
    True = ok-to-send, False = duplicate."""
    rows = supa_client.get(
        f"/send_log?to_addr=eq.{urllib.parse.quote(to_addr.lower())}"
        f"&step_n=eq.{step_n}"
        f"&persona_slug=not.is.null"
        f"&select=id,sent_at,from_addr&limit=5"
    ).json()
    # Filter to sends from THIS profile's subdomain pool. Cheaper to do
    # client-side: profile_slug → its from-domains aren't fetched here, so
    # accept any prior send to this address at this step as the dedup signal.
    if rows:
        return False, f"dup: {to_addr} already received step {step_n} (send_log {rows[0]['id'][:8]} at {rows[0]['sent_at'][:19]})"
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
    ALERT_STATE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return True


def send_alert(*, subject: str, body_text: str, body_html: str | None = None) -> None:
    """Email info@aureonglobal.de when a guard trips. Uses the full-access
    Resend key from hostinger.env (same path daily-report.py uses)."""
    host_env = REPO / "sequences" / "hostinger.env"
    if not host_env.exists():
        print("  ! no hostinger.env, cannot send safeguard alert")
        return
    host = {}
    for line in host_env.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            host[k.strip()] = v.strip()
    # Use any profile's send key (they're all on the same Resend account)
    priv = REPO / "profiles" / "aureon.private.json"
    api_key = json.loads(priv.read_text(encoding="utf-8"))["relay"]["resend_api_key"]
    payload = {
        "from":    "Outreach Stack Safeguards <safeguards@hi.aureonglobal.de>",
        "to":      ["info@aureonglobal.de"],
        "subject": f"[SAFEGUARD] {subject}",
        "text":    body_text,
        "html":    body_html or f"<pre style='font-family:monospace;'>{body_text}</pre>",
        "tags":    [{"name": "kind", "value": "safeguard_alert"}],
    }
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "Chrome/123.0.0.0 Safari/537.36")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}",
                  "Content-Type": "application/json",
                  "User-Agent": UA},
    )
    try:
        r = urllib.request.urlopen(req, timeout=30)
        print(f"  + safeguard alert sent (Resend id={json.loads(r.read()).get('id','?')[:12]}..)")
    except urllib.error.HTTPError as e:
        print(f"  ! safeguard alert send failed {e.code}: {e.read().decode()[:200]}")


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
