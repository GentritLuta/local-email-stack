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
    return data


def save_profile(profile: dict, *, write_public: bool = True) -> None:
    """Atomic write of the main profile JSON. Optionally also writes a sanitized
    copy to the frontend's public dir so the desktop app sees the change.
    Never writes secrets (API keys) to the public copy."""
    slug = profile["slug"]
    _atomic_write(PROFILES_DIR / f"{slug}.json", profile)
    if write_public:
        pub = _strip_secrets(profile)
        PROFILES_PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
        _atomic_write(PROFILES_PUBLIC_DIR / f"{slug}.json", pub)


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
    p = json.loads(json.dumps(profile))  # deep copy
    r = p.get("relay", {})
    if "resend_api_key" in r:
        r["resend_api_key"] = "***" if r["resend_api_key"] else ""
    return p
