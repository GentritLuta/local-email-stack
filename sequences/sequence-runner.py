"""sequence-runner.py — picks up due steps from runs in Supabase and sends them.

The brain that ties variants, sequences, and the rotating persona pool together.
Reads pending runs from Supabase, finds the right step + variant, picks an
eligible persona via rotation, sends via Resend, logs the outcome back to
Supabase, and advances the run to the next step (or pauses if reply/bounce).

Designed to run as a cron tick every 5 minutes:
    schtasks /Create /TN "LES-sequence-runner" /TR "py C:\\...\\sequence-runner.py tick" /SC MINUTE /MO 5

CLI:
    py sequence-runner.py tick                          # advance all due runs
    py sequence-runner.py enqueue <sequence_slug> <prospect_email>  # add a run
    py sequence-runner.py status                        # show queued/running counts
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import sys
import time
import uuid
from pathlib import Path

import httpx

# Force UTF-8 console output on Windows scheduled-task context so logging
# international characters (umlauts, dashes, checkmarks) doesn't crash the
# script with charmap codec errors. Without this, ANY print() containing
# non-ASCII unwinds the tick and yields exit code 1 to the scheduler.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Silence non-fatal DeprecationWarnings (datetime.utcnow). Some scheduled-
# task configurations interpret warnings-on-stderr as non-success exit and
# show LastTaskResult=1 even though main() returns 0. Belt-and-braces fix:
# we use timezone-naive UTC intentionally for Supabase compat; the warning
# is noise.
import warnings as _warnings
_warnings.filterwarnings("ignore", category=DeprecationWarning)

from profile_lib import (
    load_profile,
    iter_send_domains,
    daily_target_for_domain,
    reputation_exceeded_for_domain,
    materialize_persona,
)
from email_render import build_payload
import algoalpha_offer

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE  = REPO_ROOT / "sequences" / "supabase.env"
RESEND_API = "https://api.resend.com/emails"

# Self-hosted open/click tracker. Resend's domain-level open_tracking flag
# is set true on all subdomains but their pipeline does not actually inject
# the pixel — verified empirically. We inject our own pixel pointing at
# this URL; the PHP handler on the Hostinger account patches send_log via
# PostgREST. The tracker is deployed on the user's free Hostinger subdomain
# (zero additional infra). If AUREON_TRACKER_BASE is set, it overrides.
import os as _os
TRACKER_BASE = (
    _os.environ.get("AUREON_TRACKER_BASE")
    or "https://darkturquoise-mouse-998841.hostingersite.com"
)


def load_supabase() -> tuple[str, str]:
    env = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    url = env.get("SUPABASE_URL", "")
    key = env.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        sys.exit(f"missing SUPABASE_URL / SUPABASE_ANON_KEY in {ENV_FILE}")
    return url.rstrip("/"), key


def supa(url: str, key: str) -> httpx.Client:
    return httpx.Client(
        base_url=f"{url}/rest/v1", timeout=20,
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Prefer": "return=representation"},
    )


# ─── (persona, domain) rotation — mirrors resend-pool-send.py ───────────────

def _domain_of(from_addr: str) -> str:
    return (from_addr or "").split("@", 1)[-1].strip().lower()


def _per_persona_quota_for_today(profile_config: dict) -> int | None:
    """Read the send_ramp curve and compute today's per-persona send cap.

    Returns None if no ramp is configured (caller falls back to the static
    rotation.max_sends_per_persona_per_day). Returns the curve's last-tier
    value once `from_day` >= the ramp's tail, meaning "ramp complete, use
    full rate".

    `started_at` is stamped on the first call so day 1 = today, not the
    profile creation date.
    """
    ramp = profile_config.get("send_ramp") or {}
    curve = ramp.get("curve") or []
    if not curve:
        return None
    started_at = ramp.get("started_at")
    if not started_at:
        # First call — stamp today's date so we can compute "days since start"
        try:
            REPO_ROOT2 = Path(__file__).resolve().parent.parent
            slug = profile_config.get("slug")
            if slug:
                pp = REPO_ROOT2 / "profiles" / f"{slug}.json"
                if pp.exists():
                    cfg = json.loads(pp.read_text(encoding="utf-8"))
                    cfg.setdefault("send_ramp", {})["started_at"] = dt.date.today().isoformat()
                    pp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
                    started_at = cfg["send_ramp"]["started_at"]
        except Exception:
            pass
        if not started_at:
            return int(curve[0].get("per_persona", 1))

    try:
        start_d = dt.date.fromisoformat(started_at)
    except Exception:
        return int(curve[0].get("per_persona", 1))
    days = max(1, (dt.date.today() - start_d).days + 1)

    # Walk curve and pick highest tier whose from_day <= days
    sorted_curve = sorted(curve, key=lambda r: int(r.get("from_day", 0)))
    quota = int(sorted_curve[0].get("per_persona", 1))
    for tier in sorted_curve:
        if days >= int(tier.get("from_day", 0)):
            quota = int(tier.get("per_persona", quota))
    return quota


def pick_persona_and_domain(profile_config: dict, send_log_rows: list[dict]) -> tuple[dict | None, dict | None]:
    """Pick the (persona, domain) pair with most quota left today, computed
    from the live send_log we just pulled. Each subdomain in the pool warms
    independently — this spreads tick traffic across the warmed pool so no
    single subdomain spikes."""
    personas = profile_config.get("personas", [])
    domains  = iter_send_domains(profile_config)
    if not personas or not domains:
        return None, None

    rot     = profile_config.get("rotation", {})
    # Per-profile send_ramp overrides the static quota during the first ~30
    # days of a new client. The ramp protects new from-addresses (even on
    # mature shared subdomains) from looking like spam-blast. Once the
    # ramp completes, the static rotation value takes over.
    quota   = _per_persona_quota_for_today(profile_config) or int(rot.get("max_sends_per_persona_per_day", 30))
    min_gap = int(rot.get("min_seconds_between_sends_same_persona", 60))
    now_ts  = time.time()
    today_start = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()

    pair_usage: dict[tuple[str, str], dict] = {}
    domain_total_today: dict[str, int] = {d["domain"]: 0 for d in domains}
    for row in send_log_rows:
        slug   = row.get("persona_slug") or ""
        domain = _domain_of(row.get("from_addr", ""))
        try:
            ts = dt.datetime.fromisoformat(row["sent_at"].replace("Z", "+00:00")).timestamp()
        except Exception:
            continue
        key = (slug, domain)
        u = pair_usage.setdefault(key, {"count_today": 0, "last_ts": 0.0})
        if ts >= today_start:
            u["count_today"] += 1
            if domain in domain_total_today: domain_total_today[domain] += 1
        u["last_ts"] = max(u["last_ts"], ts)

    eligible = []
    for d in domains:
        blocked, _ = reputation_exceeded_for_domain(profile_config, d)
        if blocked: continue
        ceiling = daily_target_for_domain(profile_config, d) or quota
        room = max(0, ceiling - domain_total_today.get(d["domain"], 0))
        if room <= 0: continue
        eligible.append((room, d))
    if not eligible: return None, None
    eligible.sort(key=lambda t: -t[0])

    for _, d in eligible:
        cands = []
        for p in personas:
            u = pair_usage.get((p["slug"], d["domain"]), {"count_today": 0, "last_ts": 0.0})
            if u["count_today"] >= quota: continue
            if (now_ts - u["last_ts"]) < min_gap: continue
            cands.append((u["count_today"], u["last_ts"], p))
        if cands:
            cands.sort(key=lambda x: (x[0], x[1]))
            return cands[0][2], d
    return None, None


# Backwards-compat shim for the existing tick() — returns just the persona.
def pick_persona(profile_config: dict, send_log_rows: list[dict]) -> dict | None:
    persona, _ = pick_persona_and_domain(profile_config, send_log_rows)
    return persona


# ─── Step lookup ───────────────────────────────────────────────────────────

def fetch_due_runs(c: httpx.Client) -> list[dict]:
    """Pull runs where status='queued' and (next_send_at <= now OR next_send_at IS NULL)."""
    now_iso = dt.datetime.utcnow().isoformat() + "Z"
    r = c.get(f"/runs?status=eq.queued&or=(next_send_at.lte.{now_iso},next_send_at.is.null)&select=*")
    r.raise_for_status()
    return r.json()


def fetch_sequence_step(c: httpx.Client, sequence_id: str, step_n: int) -> dict | None:
    r = c.get(f"/sequence_steps?sequence_id=eq.{sequence_id}&step_n=eq.{step_n}"
              f"&select=*,variants(subject,body)")
    r.raise_for_status()
    rows = r.json()
    return rows[0] if rows else None


def fetch_max_step(c: httpx.Client, sequence_id: str) -> int:
    r = c.get(f"/sequence_steps?sequence_id=eq.{sequence_id}&select=step_n&order=step_n.desc&limit=1")
    r.raise_for_status()
    rows = r.json()
    return rows[0]["step_n"] if rows else 0


def fetch_prospect(c: httpx.Client, prospect_id: str) -> dict:
    r = c.get(f"/prospects?id=eq.{prospect_id}&select=*")
    r.raise_for_status()
    return r.json()[0]


def fetch_profile_config(c: httpx.Client, profile_slug: str) -> dict:
    r = c.get(f"/profiles?slug=eq.{profile_slug}&select=config")
    r.raise_for_status()
    return r.json()[0]["config"]


def fetch_today_log(c: httpx.Client, profile_slug: str) -> list[dict]:
    """Today's send_log rows for this profile (for rotation quota). Now also
    pulls from_addr so the rotation can attribute each send to its sending
    subdomain when picking the next (persona, domain) pair."""
    today = dt.date.today().isoformat()
    r = c.get(f"/send_log?sent_at=gte.{today}T00:00:00&select=persona_slug,from_addr,sent_at"
              f"&order=sent_at.desc&limit=500")
    r.raise_for_status()
    # Filter to this profile's personas (we don't have a profile_slug column on send_log;
    # this can be improved later. For now, all sends from same Supabase = same operator.)
    return r.json()


def get_api_key(profile_slug: str) -> str:
    priv = REPO_ROOT / "profiles" / f"{profile_slug}.private.json"
    if not priv.exists():
        sys.exit(f"missing {priv}")
    return json.loads(priv.read_text(encoding="utf-8")).get("relay", {}).get("resend_api_key", "")


# ─── Send + log ────────────────────────────────────────────────────────────

_MERGE_TAG_RE = re.compile(r"\{(\w+)\}")

# Required merge fields — the strict gate cancels the send if any of these are
# missing on the prospect. No generic fallbacks.
_REQUIRED_MERGE_FIELDS = ("first_name", "company", "personal_hook")

# Optional merge fields — derived per-prospect at send time. Always substituted
# (with empty string when data is missing), never cancel the send. These let
# the variant body weave in personalization that gracefully no-ops when the
# data isn't there for this prospect.
_OPTIONAL_MERGE_FIELDS = (
    "last_name", "city", "state", "title", "website", "email",
    "geo_clause",     # " in {city}, {state}" or " in {city}" or ""
    "team_phrase",    # "{company}'s {team_size} agent team" or "{company}"
    "team_size",      # int as string, "" if unknown
    "first_name_v",   # second-mention soft hook in body
    "greeting",       # first_name when known, else "{company} team", else "there"
    "proof_line",     # optional social-proof sentence (empty until you have one)
    "retainer_quote", # algoalpha: "a flat 1,600 USD per video" (from audience_size)
    "retainer_math",  # algoalpha: worked retainer math paragraph for step 3
)

_KNOWN_MERGE_FIELDS = _REQUIRED_MERGE_FIELDS + _OPTIONAL_MERGE_FIELDS

# Free-mail domains where multiple prospects share the same domain but are
# NOT colleagues — team_size derivation from email-domain count is invalid.
_FREE_MAIL_DOMAINS = frozenset({
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com",
    "icloud.com", "web.de", "gmx.de", "gmx.net", "protonmail.com",
    "proton.me", "live.com", "msn.com",
})

# Big-brokerage domains where the agents we scraped are 0.01% of the firm's
# headcount — the team_size signal is misleading. Default to no team claim.
_BIG_BROKERAGE_DOMAINS = frozenset({
    "compass.com", "kw.com", "remax.com", "exprealty.net", "sothebys.com",
    "cbhomes.com", "c21.com", "douglaselliman.com", "berkshirehathaway.com",
})


def synthesize_optional_merges(prospect: dict, team_size_lookup: dict | None = None) -> dict:
    """Return a dict of optional/derived merge fields, every key always set to
    a string (possibly empty). The strict gate ignores these, the variant body
    can reference them safely.

    team_size_lookup: optional dict of email-domain → count of prospects we've
    scraped from that domain. Used to claim accurate team size only when both
    (a) the count is >= 3 and (b) the domain isn't free-mail or a big-brokerage
    franchise where the count is meaningless.
    """
    syn: dict[str, str] = {}
    # last_name passthrough
    syn["last_name"] = (prospect.get("last_name") or "").strip()
    # geo_clause: " in {city}, {state}" / " in {city}" / ""
    city  = (prospect.get("city") or "").strip()
    state = (prospect.get("state") or "").strip()
    if city and state:    syn["geo_clause"] = f" in {city}, {state}"
    elif city:            syn["geo_clause"] = f" in {city}"
    else:                 syn["geo_clause"] = ""
    # team_phrase + team_size
    company = (prospect.get("company") or "").strip()
    email   = (prospect.get("email") or "").lower()
    domain  = email.split("@", 1)[1] if "@" in email else ""
    team_size = 1
    if (team_size_lookup and domain
            and domain not in _FREE_MAIL_DOMAINS
            and domain not in _BIG_BROKERAGE_DOMAINS):
        team_size = int(team_size_lookup.get(domain) or 1)
    syn["team_size"] = str(team_size) if team_size > 1 else ""
    if team_size >= 3 and company:
        syn["team_phrase"] = f"{company} and your {team_size} agent team"
    else:
        syn["team_phrase"] = company
    # first_name_v: second-mention shorthand (lets variants reuse the name
    # naturally without re-typing the merge tag)
    syn["first_name_v"] = (prospect.get("first_name") or "").strip()
    # greeting: name-optional salutation. Uses the real first name when we have
    # one (best personalization), else the company/channel name as a team
    # greeting, else a neutral fallback. Lets a campaign target leads whose
    # email carries no parseable name (e.g. crypto creators on brand-handle
    # gmails) without ever rendering "Hey ,".
    fn = (prospect.get("first_name") or "").strip()
    if fn:
        syn["greeting"] = fn
    elif company:
        # "{company} team" — but don't double up ("Scheetz Team team") when the
        # company name already ends in team/group.
        syn["greeting"] = company if company.lower().rstrip().endswith(("team", "group")) else f"{company} team"
    else:
        syn["greeting"] = "there"
    # proof_line: a social-proof sentence woven into E3/E4 of the aureon copy.
    # Empty until there is a REAL beta result to cite. When you have one, set it
    # here, e.g.:
    #   syn["proof_line"] = "Our first beta brokerage booked 14 listing appointments in 30 days."
    # Leaving it empty renders cleanly (the surrounding copy reads fine without it).
    syn["proof_line"] = ""
    # AlgoAlpha creator-offer merges: per-video retainer personalized from the
    # prospect's scraped audience_size, generic range fallback when unknown.
    # Always non-empty; only algoalpha copy references them.
    syn["retainer_quote"] = algoalpha_offer.retainer_quote(prospect.get("audience_size"))
    syn["retainer_math"]  = algoalpha_offer.retainer_math(prospect.get("audience_size"))
    return syn


def find_merge_tags(text: str) -> set[str]:
    """Return all `{tag}` patterns where tag is a known prospect field."""
    return {t for t in _MERGE_TAG_RE.findall(text) if t in _KNOWN_MERGE_FIELDS}


def missing_merge_data(text: str, prospect: dict) -> set[str]:
    """Tags referenced in `text` whose prospect value is null/empty/whitespace.
    Only REQUIRED fields can trip the gate. Optional/derived fields are always
    treated as present (the synthesize step gives them at least an empty string)."""
    missing = set()
    for tag in find_merge_tags(text):
        if tag in _OPTIONAL_MERGE_FIELDS:
            continue
        val = prospect.get(tag)
        if val is None or not str(val).strip():
            missing.add(tag)
    return missing


def _render_merge(template: str, prospect: dict) -> str:
    """Substitute every known `{tag}` with prospect data. The caller already
    ran missing_merge_data() to verify REQUIRED tags are set; this just
    substitutes everything we know (empty string for unknown optional)."""
    out = template
    for tag in _KNOWN_MERGE_FIELDS:
        out = out.replace("{" + tag + "}", str(prospect.get(tag) or ""))
    return out


def send_via_resend(api_key: str, persona: dict, prospect: dict, subject: str, body: str,
                    brand: dict | None = None, step_n: int = 1,
                    tracker_base: str | None = None) -> dict:
    # Caller is responsible for rendering merge tags (so the same rendered
    # values can be sent AND logged). We no longer re-render here.
    payload, msg_id = build_payload(
        persona=persona,
        to_addr=prospect["email"],
        subject=subject,
        body=body,
        unsubscribe_token=prospect.get("unsubscribe_token"),
        brand=brand,
        tags=[{"name": "persona", "value": persona["slug"]},
              {"name": "prospect_id", "value": str(prospect.get("id", ""))},
              {"name": "step_n", "value": str(step_n)}],
        step_n=step_n,
        tracker_base=tracker_base,
    )
    try:
        with httpx.Client(timeout=20) as r:
            resp = r.post(RESEND_API,
                          headers={"Authorization": f"Bearer {api_key}"},
                          json=payload)
        if resp.status_code in (200, 202):
            return {"ok": True, "resend_id": resp.json().get("id"), "message_id": msg_id}
        return {"ok": False, "error": f"{resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def log_send(c: httpx.Client, run: dict, step_n: int, persona: dict, prospect: dict,
             subject: str, outcome: dict) -> None:
    row = {
        "run_id":       run["id"],
        "step_n":       step_n,
        "persona_slug": persona["slug"],
        "from_addr":    persona["from_addr"],
        "to_addr":      prospect["email"],
        "subject":      subject,
        "resend_id":    outcome.get("resend_id"),
        "message_id":   outcome.get("message_id"),
        "delivered":    bool(outcome.get("ok")),
        "error":        outcome.get("error"),
    }
    c.post("/send_log", json=row)


def advance_run(c: httpx.Client, run: dict, step_completed: int,
                next_step_delay_days: int | None) -> None:
    if next_step_delay_days is None:
        # No more steps
        c.patch(f"/runs?id=eq.{run['id']}",
                json={"status": "completed", "current_step": step_completed})
        return
    next_at = dt.datetime.utcnow() + dt.timedelta(days=next_step_delay_days)
    # Jitter ±2h to avoid clock-aligned bursts
    next_at += dt.timedelta(minutes=random.randint(-120, 120))
    c.patch(f"/runs?id=eq.{run['id']}",
            json={"current_step": step_completed + 1,
                  "next_send_at": next_at.isoformat() + "Z"})


# ─── tick / enqueue / status ───────────────────────────────────────────────

def tick() -> None:
    url, key = load_supabase()
    with supa(url, key) as c:
        runs = fetch_due_runs(c)
        if not runs:
            print("no due runs")
            return
        # Cache per-profile config + today's send log to avoid re-fetching per run
        profile_cache: dict[str, dict] = {}
        today_log_cache: list[dict] | None = None
        for run in runs:
            # Pull the sequence (to learn the profile + step structure)
            seq_id = run["sequence_id"]
            seq_resp = c.get(f"/sequences?id=eq.{seq_id}&select=profile_slug,name").json()
            if not seq_resp:
                continue
            profile_slug = seq_resp[0]["profile_slug"]
            if profile_slug not in profile_cache:
                profile_cache[profile_slug] = fetch_profile_config(c, profile_slug)
            profile_config = profile_cache[profile_slug]

            step_n = run["current_step"]
            step = fetch_sequence_step(c, seq_id, step_n)
            if not step:
                # No step at this n → done
                c.patch(f"/runs?id=eq.{run['id']}", json={"status": "completed"})
                continue
            # E1 A/B: a step carrying BOTH inline copy AND a linked variant is an
            # A/B test. Split by prospect_id so each lead always gets the same
            # side (stable split). inline = variant B, linked variant = variant A.
            # The two sides use different subjects, so send_log distinguishes them
            # for measuring reply rates. Steps with only one source are unaffected.
            _v = step.get("variants") or {}
            _inl_s, _inl_b = step.get("inline_subject"), step.get("inline_body")
            _var_s, _var_b = _v.get("subject"), _v.get("body")
            if _inl_s and _inl_b and _var_s and _var_b:
                import hashlib
                _even = int(hashlib.md5(str(run.get("prospect_id")).encode()).hexdigest(), 16) % 2 == 0
                subject, body = (_inl_s, _inl_b) if _even else (_var_s, _var_b)
            else:
                subject = _inl_s or _var_s
                body    = _inl_b or _var_b
            if not subject or not body:
                print(f"  ! run {run['id']} step {step_n}: no subject/body")
                continue

            if today_log_cache is None:
                today_log_cache = fetch_today_log(c, profile_slug)

            # ── Sender stickiness ────────────────────────────────────────
            # A lead must be worked end-to-end by the SAME (persona,
            # subdomain) pair so the recipient sees one consistent thread
            # in their inbox. On step 1 we pick fresh and assign for the
            # run's lifetime. On step 2+ we look up the run's first
            # send_log row and reuse its sender. If that subdomain is at
            # cap or paused today, we SKIP this tick (don't drift to a
            # different sender mid-conversation — that breaks the thread
            # in the recipient's inbox). The run retries next tick.
            sticky_persona, sticky_domain = None, None
            if step_n > 1:
                prior = c.get(
                    f"/send_log?run_id=eq.{run['id']}&order=step_n.asc&select=persona_slug,from_addr&limit=1"
                ).json()
                if prior:
                    prior_persona_slug = prior[0].get("persona_slug")
                    prior_from = (prior[0].get("from_addr") or "").lower()
                    prior_subdomain = prior_from.split("@", 1)[1] if "@" in prior_from else ""
                    sticky_persona = next(
                        (p for p in profile_config["personas"]
                         if p["slug"] == prior_persona_slug), None)
                    sticky_domain = next(
                        (d for d in profile_config.get("relay", {}).get("from_domains", [])
                         if d.get("domain") == prior_subdomain), None)

            if step.get("forced_persona"):
                persona = next((p for p in profile_config["personas"]
                                if p["slug"] == step["forced_persona"]), None)
                _, domain = pick_persona_and_domain(profile_config, today_log_cache)
            elif sticky_persona and sticky_domain:
                # Check that the sticky subdomain still has room today
                # (cap, reputation, enabled). If not, SKIP this tick —
                # do not silently switch senders mid-thread.
                today_count_on_sticky = sum(
                    1 for row in today_log_cache
                    if _domain_of(row.get("from_addr", "")) == sticky_domain["domain"]
                )
                ceiling = daily_target_for_domain(profile_config, sticky_domain) or 0
                blocked, why = reputation_exceeded_for_domain(profile_config, sticky_domain)
                if blocked:
                    print(f"  ~ run {run['id'][:8]} step {step_n}: sticky subdomain "
                          f"{sticky_domain['domain']} reputation-paused ({why}) - skipping tick")
                    continue
                if today_count_on_sticky >= ceiling:
                    print(f"  ~ run {run['id'][:8]} step {step_n}: sticky subdomain "
                          f"{sticky_domain['domain']} at cap ({today_count_on_sticky}/{ceiling}) - skipping tick")
                    continue
                # Sticky sender available + has room
                persona, domain = sticky_persona, sticky_domain
                print(f"  ~ run {run['id'][:8]} step {step_n}: sticky sender "
                      f"{persona['slug']}@{domain['domain']}")
            else:
                # Step 1 OR orphan (sticky data missing) - pick fresh
                if step_n > 1:
                    print(f"  ! run {run['id'][:8]} step {step_n}: sticky lookup failed "
                          f"(orphan?), falling back to fresh pick")
                persona, domain = pick_persona_and_domain(profile_config, today_log_cache)
            if not persona or not domain:
                print(f"  ! run {run['id']} step {step_n}: no (persona, domain) available "
                      f"(over quota, cooldown, or pool exhausted for today)")
                continue
            persona = materialize_persona(persona, domain)

            prospect = fetch_prospect(c, run["prospect_id"])
            # Enrich the prospect with synthesized optional merge fields
            # (geo_clause, team_phrase, etc) so personalization tags in the
            # variant body always have a value, even when underlying data
            # like city/state is missing for this prospect.
            if "_team_size_cache" not in profile_cache:
                # Build email-domain -> count of prospects we've scraped from
                # that domain. Used by synthesize_optional_merges to claim a
                # team_size only when the count is meaningful.
                from collections import Counter
                all_emails = c.get(
                    f"/prospects?profile_slug=eq.{profile_slug}&select=email&limit=2000"
                ).json()
                profile_cache["_team_size_cache"] = Counter(
                    (p.get("email") or "").lower().split("@")[-1]
                    for p in all_emails if p.get("email") and "@" in p["email"]
                )
            team_size_lookup = profile_cache["_team_size_cache"]
            prospect.update(synthesize_optional_merges(prospect, team_size_lookup))
            # Verification gate: never send to an unverified prospect. Lead-scrape
            # writes verified=true only when MX/SMTP/syntax checks all pass.
            if not prospect.get("verified"):
                print(f"  ! run {run['id']} skipped: prospect {prospect.get('email')} "
                      f"is unverified (method={prospect.get('verification_method')}, "
                      f"error={prospect.get('verification_error')})")
                c.patch(f"/runs?id=eq.{run['id']}",
                        json={"status": "cancelled"})
                continue
            # Unsubscribe gate: stops further sends to anyone who clicked the
            # button in a prior email. We pause-cancel rather than skip-and-
            # retry so the run never resurfaces.
            if prospect.get("unsubscribed"):
                print(f"  ! run {run['id']} cancelled: prospect {prospect.get('email')} unsubscribed")
                c.patch(f"/runs?id=eq.{run['id']}",
                        json={"status": "cancelled"})
                continue
            api_key  = get_api_key(profile_slug)
            if not api_key:
                print(f"  ! no Resend key for {profile_slug}")
                continue

            # Personalization gate: every {tag} in subject+body must resolve
            # to non-empty prospect data. Skip-and-cancel (don't resurface)
            # if any tag is missing — operator wants no generic fallbacks.
            missing = missing_merge_data(subject, prospect) | missing_merge_data(body, prospect)
            if missing:
                print(f"  ! run {run['id']} skipped: prospect {prospect.get('email')} "
                      f"missing merge data for tags: {sorted(missing)}")
                c.patch(f"/runs?id=eq.{run['id']}",
                        json={"status": "cancelled"})
                continue

            # ─── Runtime safeguards ────────────────────────────────────────
            # Five live guards (subdomain reputation, dedup, daily cap,
            # rate-limit, quiet-hours) protect domain reputation against
            # autopilot accidents. A guard failure SKIPS this send-attempt
            # but does not cancel the run — it retries next tick.
            try:
                from safeguards import check_all, alert_on_block
                ok, reason, guard_name = check_all(
                    supa_client=c, profile_slug=profile_slug,
                    profile_config=profile_config, subdomain=domain["domain"],
                    to_addr=prospect["email"], step_n=step_n,
                    prospect=prospect,  # for per-recipient-timezone window check
                )
                if not ok:
                    print(f"  ! run {run['id']} blocked by safeguard {guard_name}: {reason}")
                    # Surface high-severity guards via email (cooldown-aware
                    # so quiet-hours + rate-limit hits do not spam).
                    alert_on_block(
                        guard_name=guard_name or "unknown",
                        profile_slug=profile_slug, subdomain=domain["domain"],
                        reason=reason or "(no reason)",
                    )
                    continue
            except ImportError:
                # safeguards module unavailable — log and proceed (don't block sends)
                print(f"  ! safeguards module not importable, proceeding without runtime guards")

            # Render merge tags ONCE so the rendered subject/body get both
            # sent to Resend AND logged to send_log (previously the
            # rendering happened inside send_via_resend and the unrendered
            # template was logged, breaking analytics + reply matching).
            rendered_subject = _render_merge(subject, prospect)
            rendered_body    = _render_merge(body,    prospect)
            outcome = send_via_resend(api_key, persona, prospect,
                                      rendered_subject, rendered_body,
                                      brand=profile_config.get("brand"),
                                      step_n=step_n,
                                      tracker_base=TRACKER_BASE)
            log_send(c, run, step_n, persona, prospect, rendered_subject, outcome)

            print(f"  [{persona['slug']:7}] step {step_n} -> {prospect['email']:30}"
                  f"  {'SENT '+(outcome.get('resend_id') or '') if outcome['ok'] else 'FAIL '+outcome.get('error','')}")

            # Track in cache so the next pick respects BOTH per-persona
            # cooldown AND per-domain ceiling for the rest of this tick.
            today_log_cache.append({"persona_slug": persona["slug"],
                                    "from_addr":   persona["from_addr"],
                                    "sent_at":     dt.datetime.utcnow().isoformat() + "Z"})

            if outcome["ok"]:
                max_step = fetch_max_step(c, seq_id)
                if step_n >= max_step:
                    advance_run(c, run, step_n, None)
                else:
                    # Next step's delay
                    next_step = fetch_sequence_step(c, seq_id, step_n + 1)
                    delay = next_step.get("delay_days", 3) if next_step else 3
                    advance_run(c, run, step_n, delay)


def enqueue(sequence_slug: str, prospect_email: str) -> None:
    """Queue a sequence for a single existing prospect. Refuses unverified prospects."""
    url, key = load_supabase()
    with supa(url, key) as c:
        r = c.get(f"/sequences?slug=eq.{sequence_slug}&select=id,profile_slug")
        rows = r.json()
        if not rows:
            sys.exit(f"sequence '{sequence_slug}' not found")
        seq = rows[0]
        # The prospect must already exist AND be verified. We do NOT auto-create
        # a row from a bare email — lead-scrape is the source of truth.
        # URL-encode the email so '+' aliases (info+livetest@...) aren't read
        # as spaces by the form-encoded query string.
        import urllib.parse as _up
        r = c.get(f"/prospects?profile_slug=eq.{seq['profile_slug']}&email=eq.{_up.quote(prospect_email, safe='@.')}&select=*")
        prospects = r.json()
        if not prospects:
            sys.exit(f"prospect {prospect_email!r} not found. Scrape it first with lead_scrape.py, "
                     f"or insert it manually with verified=true.")
        prospect = prospects[0]
        if not prospect.get("verified"):
            sys.exit(f"refusing to enqueue {prospect_email}: unverified "
                     f"(method={prospect.get('verification_method')}, "
                     f"error={prospect.get('verification_error')})")
        r = c.post("/runs?on_conflict=sequence_id,prospect_id",
                   json={"sequence_id": seq["id"], "prospect_id": prospect["id"],
                         "status": "queued", "current_step": 1,
                         "next_send_at": dt.datetime.utcnow().isoformat() + "Z"})
        print(f"queued run for {prospect_email}: {r.json()[0]['id']}")


def enqueue_niche(sequence_slug: str, niche_slug: str, limit: int | None = None) -> None:
    """Bulk-enqueue every verified prospect from a niche into a sequence.
    Skips prospects without a first_name (we can't personalize) and prospects
    already enrolled in this sequence (the on_conflict clause is a safety net)."""
    url, key = load_supabase()
    with supa(url, key) as c:
        r = c.get(f"/sequences?slug=eq.{sequence_slug}&select=id,profile_slug")
        rows = r.json()
        if not rows:
            sys.exit(f"sequence '{sequence_slug}' not found")
        seq = rows[0]
        q = (f"/prospects?niche_slug=eq.{niche_slug}&verified=eq.true"
             f"&first_name=not.is.null&profile_slug=eq.{seq['profile_slug']}"
             f"&select=id,email,first_name")
        if limit:
            q += f"&limit={limit}"
        r = c.get(q)
        prospects = r.json()
        print(f"found {len(prospects)} verified prospects in niche {niche_slug}")
        queued = 0
        for p in prospects:
            resp = c.post("/runs?on_conflict=sequence_id,prospect_id",
                          json={"sequence_id": seq["id"], "prospect_id": p["id"],
                                "status": "queued", "current_step": 1,
                                "next_send_at": dt.datetime.utcnow().isoformat() + "Z"})
            if resp.status_code in (200, 201):
                queued += 1
        print(f"queued {queued} runs")


def status_cmd() -> None:
    url, key = load_supabase()
    with supa(url, key) as c:
        for stat in ("queued", "running", "paused_replied", "paused_bounced", "completed", "cancelled"):
            r = c.get(f"/runs?status=eq.{stat}&select=count", headers={"Prefer": "count=exact"})
            cnt = r.headers.get("content-range", "?/?").split("/")[-1]
            print(f"  runs · {stat:18} {cnt}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tick")
    p_eq = sub.add_parser("enqueue"); p_eq.add_argument("sequence_slug"); p_eq.add_argument("prospect_email")
    p_en = sub.add_parser("enqueue-niche")
    p_en.add_argument("sequence_slug")
    p_en.add_argument("niche_slug")
    p_en.add_argument("--limit", type=int, default=None)
    sub.add_parser("status")
    args = ap.parse_args()
    if args.cmd == "tick":              tick()
    elif args.cmd == "enqueue":         enqueue(args.sequence_slug, args.prospect_email)
    elif args.cmd == "enqueue-niche":   enqueue_niche(args.sequence_slug, args.niche_slug, args.limit)
    elif args.cmd == "status":          status_cmd()
    return 0


if __name__ == "__main__":
    sys.exit(main())
