"""signal_pack_lib.py — load and guard the seller-intent signal packs.

Packs live in niches/signals/<pack>.yaml. This module loads them, validates the
schema, and ENFORCES the six hard guardrails from
docs/INTENT_SIGNAL_LAYER_SPEC.md before any pack is allowed to run:

  1. Jurisdiction gate     - pack jurisdiction must match the client's geos
  2. Source allowlist      - only known public sources, valid access_method,
                             social sources never via direct public_page scrape
  3. Protected-class block - no signal defined on a protected class
  4. Channel/audience fit  - B2C packs can never route a signal to cold email
  5. (B2C) no consumer cold email - enforced by 4
  6. Tone required         - every pack carries a tone block for copy

Run directly for a self-test over all packs in the directory:
  py sequences/signal_pack_lib.py
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

import yaml

REPO = Path(__file__).resolve().parent.parent
PACKS_DIR = REPO / "niches" / "signals"

# Allowlisted public sources. Anything not here is rejected.
PUBLIC_RECORD_SOURCES = {
    "county_recorder", "county_court", "probate_court", "county_tax",
    "legal_notices", "pacer", "municipal_records", "mls_adjacent", "usps_vacancy",
}
SOCIAL_SOURCES = {"reddit", "nextdoor", "x", "twitter", "forums",
                  "youtube_comments", "review_sites"}
B2B_SOURCES = {"company_site", "public_job_boards", "press", "public_registers",
               "news", "review_platforms"}
ALLOWED_SOURCES = PUBLIC_RECORD_SOURCES | SOCIAL_SOURCES | B2B_SOURCES

VALID_ACCESS = {"api", "public_index", "public_page"}

CHANNELS_B2C = {"direct_mail", "optin_funnel", "ad_audience",
                "prioritize_existing", "agent_follow_up", "reply_or_dm"}
CHANNELS_B2B = CHANNELS_B2C | {"cold_email"}

EU_GEOS = {"DE", "AT", "CH", "EU", "FR", "NL", "ES", "IT", "BE", "IE",
           "PT", "LU", "FI", "SE", "DK", "PL", "GB"}

# Targeting on any of these is illegal (Fair Housing protected classes + health).
PROTECTED_CLASS = re.compile(
    r"\b(race|racial|ethnicit|religio|national\s+origin|gender|"
    r"sexual\s+orientation|disab|familial\s+status|pregnan|"
    r"elderly|senior\s+citizen|medical\s+condition)\b", re.I)


class SignalPackError(Exception):
    pass


def list_packs() -> list[str]:
    if not PACKS_DIR.exists():
        return []
    return sorted(p.stem for p in PACKS_DIR.glob("*.yaml"))


def load_pack(pack_id: str) -> dict:
    """Load and validate a pack by id. Raises SignalPackError on any problem."""
    path = PACKS_DIR / f"{pack_id}.yaml"
    if not path.exists():
        raise SignalPackError(f"pack not found: {path}")
    try:
        pack = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as e:
        raise SignalPackError(f"pack yaml error in {pack_id}: {e}")
    if not isinstance(pack, dict):
        raise SignalPackError(f"pack {pack_id} is not a mapping")
    validate(pack)
    return pack


def validate(pack: dict) -> dict:
    """Enforce schema + the six guardrails. Returns the pack or raises."""
    pid = pack.get("pack", "<unnamed>")

    for field in ("pack", "audience", "jurisdiction", "tone", "signals"):
        if not pack.get(field):
            raise SignalPackError(f"[{pid}] missing required field: {field}")

    audience = str(pack["audience"]).lower()
    if audience not in ("b2c", "b2b"):
        raise SignalPackError(f"[{pid}] audience must be b2c or b2b, got {audience!r}")
    allowed_channels = CHANNELS_B2C if audience == "b2c" else CHANNELS_B2B

    juris = str(pack["jurisdiction"]).upper()
    if juris not in ("US", "EU") and juris not in EU_GEOS:
        raise SignalPackError(f"[{pid}] unknown jurisdiction: {juris}")

    signals = pack["signals"]
    if not isinstance(signals, list) or not signals:
        raise SignalPackError(f"[{pid}] signals must be a non-empty list")

    seen = set()
    for sig in signals:
        sid = sig.get("id")
        if not sid:
            raise SignalPackError(f"[{pid}] a signal is missing an id")
        if sid in seen:
            raise SignalPackError(f"[{pid}] duplicate signal id: {sid}")
        seen.add(sid)
        desc = str(sig.get("description", ""))

        # Guardrail 3: protected class
        hit = PROTECTED_CLASS.search(f"{sid} {desc}")
        if hit:
            raise SignalPackError(
                f"[{pid}] signal {sid} targets a protected class ({hit.group(0)!r})")

        # required signal fields
        for field in ("query_templates", "public_sources", "access_method",
                      "confidence_weight", "channel"):
            if field not in sig:
                raise SignalPackError(f"[{pid}] signal {sid} missing {field}")

        templates = sig["query_templates"]
        if not isinstance(templates, list) or not templates:
            raise SignalPackError(f"[{pid}] signal {sid} needs query_templates")

        w = sig["confidence_weight"]
        if not isinstance(w, (int, float)) or not (0.0 <= float(w) <= 1.0):
            raise SignalPackError(f"[{pid}] signal {sid} confidence_weight must be 0..1")

        access = str(sig["access_method"])
        if access not in VALID_ACCESS:
            raise SignalPackError(f"[{pid}] signal {sid} bad access_method: {access}")

        # Guardrail 2: source allowlist + social ToS
        for src in sig["public_sources"]:
            if src not in ALLOWED_SOURCES:
                raise SignalPackError(f"[{pid}] signal {sid} source not allowlisted: {src}")
            if src in SOCIAL_SOURCES and access == "public_page":
                raise SignalPackError(
                    f"[{pid}] signal {sid}: social source {src} may not be mass-scraped "
                    f"(public_page); use api or public_index")

        # Guardrail 4/5: channel/audience fit (B2C never cold-emails consumers)
        ch = str(sig["channel"])
        if ch not in allowed_channels:
            raise SignalPackError(
                f"[{pid}] signal {sid} channel {ch!r} not allowed for {audience} "
                f"(allowed: {sorted(allowed_channels)})")

    return pack


def jurisdiction_ok(pack: dict, client_geos: Iterable[str]) -> bool:
    """True if this pack may run for a client with these geos."""
    geos = {str(g).upper() for g in (client_geos or [])}
    if not geos:
        return False
    j = str(pack["jurisdiction"]).upper()
    if j == "US":
        # US-distress packs must not run on EU-only clients
        return "US" in geos
    if j == "EU":
        return bool(geos & EU_GEOS)
    return j in geos


def assert_for_client(pack: dict, client_geos: Iterable[str]) -> None:
    """Guardrail 1: raise if the pack's jurisdiction does not match the client."""
    if not jurisdiction_ok(pack, client_geos):
        raise SignalPackError(
            f"jurisdiction gate: pack {pack.get('pack')} ({pack.get('jurisdiction')}) "
            f"may not run for client geos {list(client_geos)}")


def _selftest() -> int:
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  {'OK ' if cond else 'FAIL'} {label}")
        ok = ok and cond

    packs = list_packs()
    check(f"found packs: {packs}", len(packs) >= 2)
    for pid in packs:
        try:
            load_pack(pid)
            check(f"{pid} validates", True)
        except SignalPackError as e:
            check(f"{pid} validates ({e})", False)

    # jurisdiction gate
    try:
        us = load_pack("us_real_estate_distress")
        check("US pack ok for US client", jurisdiction_ok(us, ["US"]))
        check("US pack BLOCKED for EU client", not jurisdiction_ok(us, ["DE"]))
        eu = load_pack("eu_b2b")
        check("EU pack ok for DE client", jurisdiction_ok(eu, ["DE"]))
        check("EU pack BLOCKED for US-only client", not jurisdiction_ok(eu, ["US"]))
    except SignalPackError as e:
        check(f"jurisdiction checks ({e})", False)

    # negative cases: synthetic bad packs must be rejected
    bad_cases = {
        "protected class": {"pack": "x", "audience": "b2c", "jurisdiction": "US",
            "tone": "t", "signals": [{"id": "target_by_race", "description": "race based",
            "query_templates": ["q"], "public_sources": ["reddit"],
            "access_method": "public_index", "confidence_weight": 0.5, "channel": "direct_mail"}]},
        "b2c cold email": {"pack": "x", "audience": "b2c", "jurisdiction": "US",
            "tone": "t", "signals": [{"id": "s", "description": "d", "query_templates": ["q"],
            "public_sources": ["reddit"], "access_method": "public_index",
            "confidence_weight": 0.5, "channel": "cold_email"}]},
        "social mass scrape": {"pack": "x", "audience": "b2c", "jurisdiction": "US",
            "tone": "t", "signals": [{"id": "s", "description": "d", "query_templates": ["q"],
            "public_sources": ["reddit"], "access_method": "public_page",
            "confidence_weight": 0.5, "channel": "direct_mail"}]},
        "bad source": {"pack": "x", "audience": "b2c", "jurisdiction": "US",
            "tone": "t", "signals": [{"id": "s", "description": "d", "query_templates": ["q"],
            "public_sources": ["pegasus_spyware"], "access_method": "public_index",
            "confidence_weight": 0.5, "channel": "direct_mail"}]},
    }
    for label, bad in bad_cases.items():
        rejected = False
        try:
            validate(bad)
        except SignalPackError:
            rejected = True
        check(f"rejects {label}", rejected)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
