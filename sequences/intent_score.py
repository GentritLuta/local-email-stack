"""intent_score.py — deterministic scoring for the seller-intent engine.

Pure functions, no I/O, no randomness, no implicit clock (pass `today`), so the
same inputs always yield the same score. Used by intent_signals.py.

score = weight * confidence * recency_factor(event_date, recency_days)
A lead's overall intent is a saturating combine of its signal scores.
"""
from __future__ import annotations

import datetime as dt
from typing import Iterable, Optional, Union

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%d.%m.%Y",
                 "%Y-%m-%dT%H:%M:%S", "%Y-%m")


def parse_date(s: Union[str, dt.date, None]) -> Optional[dt.date]:
    """Best-effort parse of a free-text date into a date, else None."""
    if s is None:
        return None
    if isinstance(s, dt.date):
        return s
    s = str(s).strip()
    if not s:
        return None
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(s[:len(fmt) + 4], fmt).date()
        except Exception:
            continue
    # bare 4-digit year anywhere
    for tok in s.replace("/", " ").replace("-", " ").split():
        if len(tok) == 4 and tok.isdigit():
            y = int(tok)
            if 1990 <= y <= 2100:
                return dt.date(y, 1, 1)
    return None


def recency_factor(event_date: Union[str, dt.date, None],
                   recency_days: Optional[int],
                   today: Optional[dt.date] = None) -> float:
    """1.0 for a fresh event, decaying linearly to 0.3 at the window edge and
    0.2 beyond it. recency_days <= 0 means the signal is not time-sensitive
    (e.g. absentee owner) and always scores 1.0. An undatable event scores a
    cautious 0.6."""
    if not recency_days or recency_days <= 0:
        return 1.0
    d = parse_date(event_date)
    if d is None:
        return 0.6
    today = today or dt.date.today()
    age = max(0, (today - d).days)
    if age >= recency_days:
        return 0.2
    return round(1.0 - 0.7 * (age / recency_days), 4)


def signal_score(weight: float, confidence: float,
                 event_date: Union[str, dt.date, None] = None,
                 recency_days: Optional[int] = None,
                 today: Optional[dt.date] = None) -> float:
    """Single-signal contribution in 0..1."""
    w = max(0.0, min(1.0, float(weight or 0.0)))
    c = max(0.0, min(1.0, float(confidence if confidence is not None else 0.0)))
    return round(w * c * recency_factor(event_date, recency_days, today), 4)


def aggregate(contributions: Iterable[float]) -> float:
    """Combine several signal scores for one lead into a 0..1 intent score.
    Probabilistic-OR: multiple weak signals add up but never exceed 1, and one
    strong signal already pushes the score high."""
    s = 1.0
    for x in contributions:
        x = max(0.0, min(1.0, float(x)))
        s *= (1.0 - x)
    return round(1.0 - s, 4)


def _selftest() -> int:
    today = dt.date(2026, 6, 16)
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  {'OK ' if cond else 'FAIL'} {label}")
        ok = ok and cond

    # fresh event scores near full weight*conf
    fresh = signal_score(0.9, 1.0, "2026-06-10", 365, today)
    check(f"fresh event high ({fresh})", fresh > 0.85)
    # old event past window decays hard
    old = signal_score(0.9, 1.0, "2024-01-01", 365, today)
    check(f"stale event low ({old})", old <= 0.2)
    # non-time-sensitive ignores date
    flat = signal_score(0.55, 1.0, None, 0, today)
    check(f"non-time-sensitive full ({flat})", abs(flat - 0.55) < 1e-6)
    # undatable -> cautious 0.6 factor
    undat = signal_score(1.0, 1.0, None, 365, today)
    check(f"undatable cautious ({undat})", abs(undat - 0.6) < 1e-6)
    # aggregate saturates below 1
    agg = aggregate([0.9, 0.8, 0.5])
    check(f"aggregate < 1 ({agg})", agg < 1.0 and agg > 0.9)
    # determinism
    check("deterministic", signal_score(0.9, 1.0, "2026-06-10", 365, today) == fresh)

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
