# -*- coding: utf-8 -*-
"""send_throttle.py — cross-process global rate limiter for the shared Resend key.

All brands send on ONE Resend account key, which has a per-account request rate
limit (~2 req/s on the default plan). A single runner process serialised every
send so it never tripped that limit. Once we run one runner PER BRAND (each
`sequence-runner.py tick --profile <slug>`), N processes send concurrently
against the same account and would hit 429s and drop sends.

This module enforces a GLOBAL minimum interval between sends across every runner
process on this machine, using a file-lock-protected "next free slot" timestamp.
Each caller reserves the next slot (advancing it by the interval) under a short
exclusive lock, then sleeps until its slot OUTSIDE the lock — so processes never
block each other for longer than the tiny critical section, and the combined
send rate across all processes stays under the cap.

No dependencies, no paid services. Windows uses msvcrt; POSIX uses fcntl; if
neither is available it degrades to a best-effort read-modify-write (small race
window, still mostly paced).

Usage (in the runner, right before each Resend call):
    import send_throttle
    send_throttle.acquire()        # blocks just long enough to honour the rate

Tune via env RESEND_MIN_INTERVAL_S (seconds, default 0.6 = ~1.6 req/s, safely
under a 2 req/s account cap).
"""
from __future__ import annotations

import os
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_STATE = _REPO / "warmup-state" / "resend_throttle.lock"

try:
    import msvcrt  # Windows
    _LOCK_KIND = "msvcrt"
except ImportError:  # pragma: no cover - POSIX
    msvcrt = None
    try:
        import fcntl
        _LOCK_KIND = "fcntl"
    except ImportError:
        fcntl = None
        _LOCK_KIND = "none"


def _default_interval() -> float:
    try:
        return max(0.0, float(os.environ.get("RESEND_MIN_INTERVAL_S", "0.6")))
    except (TypeError, ValueError):
        return 0.6


def _lock(f) -> None:
    if _LOCK_KIND == "msvcrt":
        while True:
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.005)
    elif _LOCK_KIND == "fcntl":
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)


def _unlock(f) -> None:
    if _LOCK_KIND == "msvcrt":
        try:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    elif _LOCK_KIND == "fcntl":
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def acquire(min_interval_s: float | None = None) -> float:
    """Block until it is this caller's turn to make one Resend request. Returns
    the number of seconds it waited (0.0 if it was immediately free)."""
    interval = _default_interval() if min_interval_s is None else max(0.0, min_interval_s)
    if interval <= 0:
        return 0.0
    _STATE.parent.mkdir(parents=True, exist_ok=True)
    # a+ so the file is created if missing and we can read+write it
    with open(_STATE, "a+", encoding="utf-8") as f:
        # msvcrt locks a byte range from the current position; lock byte 0
        if _LOCK_KIND == "msvcrt":
            f.seek(0)
        _lock(f)
        try:
            f.seek(0)
            raw = f.read().strip()
            try:
                next_slot = float(raw) if raw else 0.0
            except ValueError:
                next_slot = 0.0
            now = time.time()
            my_slot = now if next_slot < now else next_slot
            f.seek(0)
            f.truncate()
            f.write(f"{my_slot + interval:.6f}")
            f.flush()
            os.fsync(f.fileno())
        finally:
            _unlock(f)
    wait = my_slot - time.time()
    if wait > 0:
        time.sleep(wait)
        return wait
    return 0.0


if __name__ == "__main__":
    # selftest: time N back-to-back acquires; total should be ~ (N-1)*interval
    import sys
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    iv = float(sys.argv[2]) if len(sys.argv) > 2 else 0.6
    t0 = time.time()
    waited = 0.0
    for i in range(n):
        waited += acquire(iv)
        print(f"  acquire {i+1}/{n} at +{time.time()-t0:.3f}s")
    total = time.time() - t0
    print(f"lock_kind={_LOCK_KIND} interval={iv}s  total={total:.3f}s "
          f"(expected ~{(n-1)*iv:.3f}s)  cumulative_wait={waited:.3f}s")
