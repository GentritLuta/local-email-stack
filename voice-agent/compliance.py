# -*- coding: utf-8 -*-
"""compliance.py - the non-negotiable gate every AI voice call must pass.

An AI-cloned voice is an "artificial voice" under the TCPA (FCC ruling, 2024), so
dialing a US number with it requires prior express consent, a DNC scrub, a
recipient-local 8am-9pm calling window, and an up-front disclosure that the caller
is automated. This module is the single choke point: dial.py MUST call can_call()
and refuse anything it rejects. Do not add a bypass path - an ungated AI dialer to
non-consented numbers is $500-1500 per call in TCPA liability with no aggregate cap.

Pure logic, no I/O, so it is unit-testable without any provider or network.
"""
from __future__ import annotations

import datetime as dt

# TCPA local calling window, in the RECIPIENT's local time.
CALL_WINDOW_START = 8    # 8:00 am
CALL_WINDOW_END = 21     # 9:00 pm (21:00)

# Rough US state -> standard-time UTC offset (hours). Good enough to keep calls
# safely inside the legal window; replace with zoneinfo + real DST before scale.
_STATE_UTC_OFFSET = {
    "CT": -5, "DE": -5, "FL": -5, "GA": -5, "ME": -5, "MD": -5, "MA": -5,
    "NH": -5, "NJ": -5, "NY": -5, "NC": -5, "OH": -5, "PA": -5, "RI": -5,
    "SC": -5, "VT": -5, "VA": -5, "WV": -5, "MI": -5, "IN": -5, "KY": -5,
    "AL": -6, "AR": -6, "IL": -6, "IA": -6, "KS": -6, "LA": -6, "MN": -6,
    "MS": -6, "MO": -6, "NE": -6, "ND": -6, "OK": -6, "SD": -6, "TN": -6,
    "TX": -6, "WI": -6,
    "AZ": -7, "CO": -7, "ID": -7, "MT": -7, "NM": -7, "UT": -7, "WY": -7,
    "CA": -8, "NV": -8, "OR": -8, "WA": -8,
    "AK": -9, "HI": -10,
}
# Unknown state -> Pacific, the latest US-mainland clock, so we never dial before
# 8am somewhere by assuming an earlier zone.
_DEFAULT_OFFSET = -8

# The disclosure the agent MUST speak first (proposed 2026 FCC rule + best practice).
AI_DISCLOSURE = ("Hi, quick heads up before we go on: this is an automated "
                 "assistant calling on behalf of {agency}. Is now an okay time?")


def _local_hour(state: str | None, now_utc: dt.datetime) -> int:
    off = _STATE_UTC_OFFSET.get((state or "").strip().upper(), _DEFAULT_OFFSET)
    return (now_utc + dt.timedelta(hours=off)).hour


def can_call(lead: dict, now_utc: dt.datetime | None = None) -> tuple[bool, str]:
    """Return (allowed, reason). dial.py refuses every (False, reason).

    Required lead fields: phone, consent_to_ai_call (bool). Optional: dnc,
    unsubscribed, state. A missing consent flag is treated as NO consent.
    """
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    if not (lead.get("phone") or "").strip():
        return False, "no phone on record"
    # 1. Prior express consent to an automated/AI call is MANDATORY.
    if not lead.get("consent_to_ai_call"):
        return False, "no AI-call consent on record"
    # 2. DNC / suppression.
    if lead.get("dnc") or lead.get("unsubscribed"):
        return False, "on DNC / suppressed"
    # 3. Recipient-local calling window.
    hr = _local_hour(lead.get("state"), now_utc)
    if not (CALL_WINDOW_START <= hr < CALL_WINDOW_END):
        return False, f"outside 8am-9pm local window (local hour {hr})"
    return True, "ok"


def disclosure_line(agency: str = "Aureon") -> str:
    return AI_DISCLOSURE.format(agency=agency)


if __name__ == "__main__":
    # Smoke test the gate.
    import datetime as _dt
    noon_utc = _dt.datetime(2026, 7, 2, 17, 0, tzinfo=_dt.timezone.utc)  # ~noon ET
    cases = [
        {"phone": "+13175551234", "consent_to_ai_call": True, "state": "IN"},
        {"phone": "+13175551234", "consent_to_ai_call": False, "state": "IN"},
        {"phone": "", "consent_to_ai_call": True, "state": "IN"},
        {"phone": "+13175551234", "consent_to_ai_call": True, "dnc": True, "state": "IN"},
        {"phone": "+13105551234", "consent_to_ai_call": True, "state": "CA"},  # ~9am PT, ok
    ]
    for c in cases:
        print(can_call(c, noon_utc), c)
