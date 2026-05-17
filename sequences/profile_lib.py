"""profile_lib.py — shared helpers used by every sequence/warmup script.

Loads a profile from profiles/<slug>.json, merges in the .private.json overlay
(holds Resend API key etc., gitignored), persists changes atomically, and
computes ramp + mix from the profile's config.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
PROFILES_DIR = REPO_ROOT / "profiles"
PROFILES_PUBLIC_DIR = REPO_ROOT / "desktop" / "frontend" / "public" / "profiles"


def load_profile(slug: str) -> dict:
    main_path = PROFILES_DIR / f"{slug}.json"
    if not main_path.exists():
        raise FileNotFoundError(f"no profile at {main_path}")
    data = json.loads(main_path.read_text(encoding="utf-8"))
    priv_path = PROFILES_DIR / f"{slug}.private.json"
    if priv_path.exists():
        priv = json.loads(priv_path.read_text(encoding="utf-8"))
        data = _deep_merge(data, priv)
    _ensure_multi_domain_relay(data)
    return data


def _ensure_multi_domain_relay(data: dict) -> None:
    """Backward-compat shim: synthesize relay.from_domains[] from the older
    relay.from_domain (single string) so every reader downstream can treat
    sending as a pool of independently-warmed subdomains. Idempotent."""
    relay = data.setdefault("relay", {})
    if relay.get("from_domains"):
        return
    legacy_domain = relay.get("from_domain")
    if not legacy_domain:
        return
    # Inherit profile-level warmup as the single-domain warmup state. This
    # keeps existing send caps intact for the first run after migration.
    inherited = json.loads(json.dumps(data.get("warmup", {})))
    inherited.pop("warmup_targets", None)
    inherited.pop("real_send_mix", None)
    inherited.pop("auto_pause_thresholds", None)
    inherited.setdefault("enabled", True)
    inherited.setdefault("current_day", 0)
    inherited.setdefault("started_at", None)
    inherited.setdefault("ramp_curve", "snowball_v1")
    relay["from_domains"] = [{
        "domain":            legacy_domain,
        "resend_domain_id":  relay.get("resend_domain_id"),
        "verified_at":       relay.get("domain_verified_at"),
        "warmup":            inherited,
    }]


def iter_send_domains(profile: dict, *, only_verified: bool = True, only_enabled: bool = True) -> list[dict]:
    """All sending subdomains in this profile's pool. By default returns only
    domains that are verified at Resend AND have warmup enabled — exactly
    what the rotation should pick from."""
    relay = profile.get("relay") or {}
    out = list(relay.get("from_domains") or [])
    if only_verified: out = [d for d in out if d.get("verified_at")]
    if only_enabled:  out = [d for d in out if (d.get("warmup") or {}).get("enabled", True)]
    return out


def daily_target_for_domain(profile: dict, domain_entry: dict) -> int:
    """Per-domain daily ceiling using the domain's current_day and either its
    own warmup.ramp_curve or the profile's default snowball curve."""
    w = (domain_entry or {}).get("warmup") or {}
    day = int(w.get("current_day", 0))
    if day < 1: return 0
    curve_id = w.get("ramp_curve") or "snowball_v1"
    curve = profile.get(f"ramp_curve_{curve_id}", profile.get("ramp_curve_snowball_v1", []))
    target = 0
    for row in sorted(curve, key=lambda r: r["from_day"]):
        if day >= row["from_day"]: target = row["daily"]
    cap = int(w.get("max_daily_sends", target))
    return min(target, cap)


def current_warmup_day_for_domain(domain_entry: dict) -> int:
    return int(((domain_entry or {}).get("warmup") or {}).get("current_day", 0))


def reputation_exceeded_for_domain(profile: dict, domain_entry: dict) -> tuple[bool, str | None]:
    """Per-domain bounce/complaint check against profile-level auto-pause thresholds."""
    rep = ((domain_entry or {}).get("warmup") or {}).get("reputation", {})
    th  = (profile.get("warmup") or {}).get("auto_pause_thresholds", {})
    br_lim = th.get("bounce_rate", 0.05)
    cr_lim = th.get("complaint_rate", 0.001)
    if rep.get("bounce_rate_7d", 0.0) > br_lim:
        return True, f"{domain_entry.get('domain')}: bounce_rate_7d={rep['bounce_rate_7d']:.3f} > {br_lim:.3f}"
    if rep.get("complaint_rate_7d", 0.0) > cr_lim:
        return True, f"{domain_entry.get('domain')}: complaint_rate_7d={rep['complaint_rate_7d']:.4f} > {cr_lim:.4f}"
    return False, None


def materialize_persona(persona: dict, domain_entry: dict) -> dict:
    """Return a copy of a persona with from_addr/reply_to bound to a specific
    domain from the pool. Lets one persona slug 'daniel' send from any of
    daniel@<sub>.aureonglobal.de in the pool."""
    p = dict(persona)
    domain = domain_entry["domain"]
    p["from_addr"] = f'{persona["slug"]}@{domain}'
    # Reply-To stays on the canonical mailbox (info@<root>) so replies converge.
    return p


def save_profile(profile: dict, *, write_public: bool = True) -> None:
    """Atomic write of the main profile JSON. The in-memory `profile` dict is
    the merged view of <slug>.json + <slug>.private.json. We MUST strip
    secrets before writing the main file, otherwise the API key in
    .private.json leaks into git-tracked .json on every save.

    The .private.json file is the canonical home for secrets — load_profile
    re-merges it on every load, so stripping here is lossless."""
    slug = profile["slug"]
    safe = _strip_secrets(profile)
    _atomic_write(PROFILES_DIR / f"{slug}.json", safe)
    if write_public:
        PROFILES_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
        _atomic_write(PROFILES_PUBLIC_DIR / f"{slug}.json", safe)


def save_private(slug: str, fragment: dict) -> None:
    """Persist secrets (API keys, etc.) into <slug>.private.json. Merged on load."""
    priv_path = PROFILES_DIR / f"{slug}.private.json"
    existing = {}
    if priv_path.exists():
        existing = json.loads(priv_path.read_text(encoding="utf-8"))
    merged = _deep_merge(existing, fragment)
    _atomic_write(priv_path, merged)


def list_profiles() -> list[dict]:
    out = []
    if not PROFILES_DIR.exists():
        return out
    for p in PROFILES_DIR.glob("*.json"):
        if p.stem.endswith(".private"):
            continue
        try:
            out.append(load_profile(p.stem))
        except Exception:
            pass
    return sorted(out, key=lambda x: x.get("name", x["slug"]))


def daily_target_for(profile: dict, day: int) -> int:
    """Step function on the snowball ramp. day < 1 → 0."""
    if day < 1:
        return 0
    curve = profile.get("ramp_curve_snowball_v1", [])
    if not curve:
        return 0
    target = 0
    for row in sorted(curve, key=lambda r: r["from_day"]):
        if day >= row["from_day"]:
            target = row["daily"]
    return min(target, profile.get("warmup", {}).get("max_daily_sends", target))


def warmup_pct_for(profile: dict, day: int) -> float:
    """Returns 0.0 – 1.0 representing the share of today's sends that should be
    warmup-targeted vs real prospects."""
    mix = profile.get("warmup", {}).get("real_send_mix", [])
    for row in sorted(mix, key=lambda r: r["until_day"]):
        if day <= row["until_day"]:
            return row["warmup_pct"] / 100.0
    return 0.05


def current_warmup_day(profile: dict) -> int:
    """current_day stored in profile is the authoritative ramp position.
    The scheduler bumps it; this is just a getter."""
    return int(profile.get("warmup", {}).get("current_day", 0))


def reputation_exceeded(profile: dict) -> tuple[bool, str | None]:
    rep = profile.get("warmup", {}).get("reputation", {})
    th  = profile.get("warmup", {}).get("auto_pause_thresholds", {})
    if rep.get("bounce_rate_7d", 0.0) > th.get("bounce_rate", 0.05):
        return True, f"bounce_rate_7d={rep['bounce_rate_7d']:.3f} > {th['bounce_rate']:.3f}"
    if rep.get("complaint_rate_7d", 0.0) > th.get("complaint_rate", 0.001):
        return True, f"complaint_rate_7d={rep['complaint_rate_7d']:.4f} > {th['complaint_rate']:.4f}"
    return False, None


def today_iso() -> str:
    return dt.date.today().isoformat()


# ─── Helpers ───────────────────────────────────────────────────────────────

def _atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except Exception:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
        raise


def _deep_merge(a: dict, b: dict) -> dict:
    out = dict(a)
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _strip_secrets(profile: dict) -> dict:
    """Remove every value that lives in <slug>.private.json from the dict
    before persisting it to the git-tracked main file. Lossless because
    load_profile re-merges .private.json on every load."""
    p = json.loads(json.dumps(profile))  # deep copy
    r = p.get("relay", {})
    if "resend_api_key" in r:
        r["resend_api_key"] = ""        # placeholder; real value lives in .private.json
    return p
