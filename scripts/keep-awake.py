"""keep-awake.py — daemon that prevents Windows from sleeping while it runs.

Uses Win32 `SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` so
the OS treats this process as actively needing the system awake. No admin
rights needed. Works even when the laptop lid is closed (on most hardware;
some BIOSes override).

Restoring on exit: when this process is killed, the flag clears and Windows
resumes normal sleep policy.

Run as a per-user startup scheduled task (LES-keep-awake) so it boots on
login and survives until logoff. Manual run:
    py scripts/keep-awake.py
"""
from __future__ import annotations
import ctypes
import sys
import time
from datetime import datetime
from pathlib import Path

# Force UTF-8 stdout on Windows
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Win32 SetThreadExecutionState flags
ES_CONTINUOUS       = 0x80000000
ES_SYSTEM_REQUIRED  = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002
ES_AWAYMODE_REQUIRED = 0x00000040  # keeps machine "fully on" not just background-awake

REPO = Path(__file__).resolve().parent.parent
LOG_FILE = REPO / "warmup-state" / "keep-awake.log"


def log(msg: str) -> None:
    LOG_FILE.parent.mkdir(exist_ok=True)
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def main() -> int:
    if not sys.platform.startswith("win"):
        log("non-windows platform — SetThreadExecutionState unavailable, exiting")
        return 0
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_AWAYMODE_REQUIRED
    prev = ctypes.windll.kernel32.SetThreadExecutionState(flags)
    log(f"keep-awake daemon started (prev flags=0x{prev:x}, new=0x{flags:x})")
    # Re-issue the call periodically. ES_CONTINUOUS is sticky for the thread
    # lifetime, but re-calling guards against subtle bugs in some Windows
    # versions where the flag gets cleared after long uptime.
    try:
        while True:
            time.sleep(60)
            ctypes.windll.kernel32.SetThreadExecutionState(flags)
    except KeyboardInterrupt:
        log("interrupted — clearing flags")
    finally:
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
