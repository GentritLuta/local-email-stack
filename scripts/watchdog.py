"""watchdog.py — hourly silent health check.

Runs every hour via LES-watchdog. Detects and remediates:

  1. SEQUENCE-RUNNER STUCK
     If no send_log row in the last 75 min during a working window
     (08-17 in any active profile's recipient timezone, weekday) AND
     there are queued runs with next_send_at <= now, then either:
       - the scheduled task isn't firing → revive by running a manual tick
       - the previous tick is hung → kill it then revive

  2. SCHEDULED TASK DISABLED OR ERRORING
     If LES-sequence-runner / LES-pool-monitor / LES-imap-poll show
     LastResult != 0 (and != STILL_RUNNING) for the last 3 firings, log
     a warning. We don't try to re-enable disabled tasks (admin needed).

  3. POOL EXHAUSTED
     If actual_pool < 10 across all profiles AND no lead_scrape is
     currently running, kick off pool-monitor.

Idempotent. Logs every run to warmup-state/watchdog.log so you can audit
what fired and when. Sends a [WATCHDOG] alert via Resend if it had to
take any remediation action.
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
LOG_FILE = REPO / "warmup-state" / "watchdog.log"

# This script runs under pythonw (no console). Every console-subsystem child
# (powershell.exe, taskkill) would otherwise allocate a VISIBLE console window
# per call — the hourly desktop popups. Same pattern as pool-monitor.py.
_NOWINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

env = {}
for line in (REPO / "sequences" / "supabase.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
SB_URL = env["SUPABASE_URL"]
SB_KEY = env["SUPABASE_ANON_KEY"]
SB_H = {"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"}

henv = {}
for line in (REPO / "sequences" / "hostinger.env").read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); henv[k.strip()] = v.strip()
RESEND_KEY = henv.get("RESEND_FULL_ACCESS_API_KEY")


def log(msg: str) -> None:
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(exist_ok=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def supa(path: str) -> list:
    req = urllib.request.Request(f"{SB_URL}/rest/v1/{path}", headers=SB_H)
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def send_alert(title: str, body_lines: list[str]) -> None:
    """CONSOLIDATED 2026-06-16: no longer emails per event. Watchdog remediations
    were flooding info@; they now go into the ops_digest buffer and surface as ONE
    "System events" section in the daily report. The watchdog still ACTS in real
    time (re-enables tasks, revives the runner) — only the notification is
    consolidated."""
    try:
        sys.path.insert(0, str(REPO / "sequences"))
        import ops_digest
        ops_digest.record(source="watchdog", subject=title,
                          detail="\n".join(body_lines), severity="warn")
        log(f"  recorded to ops digest: {title}")
    except Exception as e:
        log(f"  ! ops_digest.record failed: {e}")


def is_process_running(name_substr: str) -> list[int]:
    """Returns PIDs of python.exe processes whose command line contains
    `name_substr`. Empty list if none. Cross-platform best-effort: uses
    PowerShell on Windows, psutil/ps on Unix."""
    try:
        if sys.platform.startswith("win"):
            out = subprocess.check_output(
                ["powershell.exe", "-Command",
                 f"Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='pythonw.exe'\" | "
                 f"Where-Object {{ $_.CommandLine -like '*{name_substr}*' }} | "
                 f"Select-Object -ExpandProperty ProcessId"],
                text=True, stderr=subprocess.DEVNULL, timeout=10,
                creationflags=_NOWINDOW)
            return [int(p) for p in out.strip().splitlines() if p.strip().isdigit()]
        else:
            out = subprocess.check_output(["pgrep", "-f", name_substr],
                                          text=True, stderr=subprocess.DEVNULL, timeout=10)
            return [int(p) for p in out.strip().splitlines() if p.strip().isdigit()]
    except Exception:
        return []


def process_age_seconds(pid: int) -> float | None:
    """Approximate process age in seconds. Returns None if PID gone."""
    try:
        if sys.platform.startswith("win"):
            out = subprocess.check_output(
                ["powershell.exe", "-Command",
                 f"$p = Get-Process -Id {pid} -ErrorAction SilentlyContinue; "
                 f"if ($p) {{ (New-TimeSpan -Start $p.StartTime -End (Get-Date)).TotalSeconds }}"],
                text=True, stderr=subprocess.DEVNULL, timeout=10,
                creationflags=_NOWINDOW)
            t = out.strip()
            return float(t) if t else None
        else:
            out = subprocess.check_output(["ps", "-o", "etimes=", "-p", str(pid)],
                                          text=True, stderr=subprocess.DEVNULL, timeout=10)
            return float(out.strip())
    except Exception:
        return None


def kill_pid(pid: int) -> None:
    try:
        if sys.platform.startswith("win"):
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           creationflags=_NOWINDOW)
        else:
            subprocess.run(["kill", "-9", str(pid)], timeout=10,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


PROTECTED_TASKS = [
    "LES-lead-scrape-crypto_influencer",
    "LES-lead-scrape-real_estate_us",
    "LES-source-atal",
]


def per_brand_runner_tasks() -> list[str]:
    """The LES-sequence-runner-<brand> tasks — the SINGLE SOURCE OF TRUTH for the
    per-brand sender fleet. Empty before the per-brand cutover (then the single
    global LES-sequence-runner is in charge). Windows-only."""
    if not sys.platform.startswith("win"):
        return []
    try:
        out = subprocess.check_output(
            ["powershell.exe", "-NoProfile", "-Command",
             "(Get-ScheduledTask -TaskName 'LES-sequence-runner-*' "
             "-ErrorAction SilentlyContinue).TaskName"],
            text=True, stderr=subprocess.DEVNULL, timeout=15,
            creationflags=_NOWINDOW)
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except Exception:
        return []


def ensure_tasks_enabled() -> list[str]:
    """Re-enable protected scheduled tasks if anything disabled them.
    These lead-scrape tasks refill the prospect pool; a disabled scraper
    silently starves the senders, so the watchdog keeps them on. Also keeps
    every per-brand sender task (LES-sequence-runner-<brand>) enabled so a
    stopped brand can't go silently dark. The tasks run as the interactive
    user (LeastPrivilege), so no elevation needed. Windows-only; no-op elsewhere."""
    done: list[str] = []
    if not sys.platform.startswith("win"):
        return done
    for t in PROTECTED_TASKS + per_brand_runner_tasks():
        try:
            state = subprocess.check_output(
                ["powershell.exe", "-NoProfile", "-Command",
                 f"(Get-ScheduledTask -TaskName '{t}' -ErrorAction SilentlyContinue).State"],
                text=True, stderr=subprocess.DEVNULL, timeout=15,
                creationflags=_NOWINDOW).strip()
            if state.lower() == "disabled":
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command",
                     f"Enable-ScheduledTask -TaskName '{t}'"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15,
                    creationflags=_NOWINDOW)
                done.append(f"re-enabled disabled task {t}")
                log(f"  re-enabled protected task {t}")
        except Exception as e:
            log(f"  ! task-guard {t} failed: {e}")
    return done


def revive_sequence_runner() -> bool:
    """Revive the sender. Returns True if something was spawned/started.

    POST-CUTOVER (per-brand fleet exists): re-enable and Start each
    LES-sequence-runner-<brand> task. We must NOT spawn a bare global
    `sequence-runner.py tick` here — the global task is retired after the
    cutover, and a global tick running alongside the per-brand tasks would
    DOUBLE-PROCESS the same due runs and double-send. Start-ScheduledTask
    respects each task's MultipleInstances=IgnoreNew, so a brand already
    running is not double-started.

    PRE-CUTOVER (no per-brand tasks): fall back to a single detached global
    tick, exactly as before — keeps this watchdog correct either way."""
    tasks = per_brand_runner_tasks()
    if tasks:
        revived = False
        for t in tasks:
            try:
                subprocess.run(
                    ["powershell.exe", "-NoProfile", "-Command",
                     f"Enable-ScheduledTask -TaskName '{t}'; Start-ScheduledTask -TaskName '{t}'"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20,
                    creationflags=_NOWINDOW)
                revived = True
            except Exception as e:
                log(f"  ! revive {t} failed: {e}")
        return revived
    # Pre-cutover fallback: single global runner.
    try:
        kwargs = {}
        if sys.platform.startswith("win"):
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
        subprocess.Popen(
            ["py", str(REPO / "sequences" / "sequence-runner.py"), "tick"],
            cwd=str(REPO),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **kwargs,
        )
        return True
    except Exception as e:
        log(f"  ! revive spawn failed: {e}")
        return False


def main() -> int:
    log(f"=== watchdog tick ===")
    actions: list[str] = []
    now = datetime.now(timezone.utc)

    # --- Check 0: protected lead-scrape tasks must stay enabled ---
    actions += ensure_tasks_enabled()

    # --- Check 1: stuck sequence-runner ---
    # Look for the most recent send. If older than 75 min AND we're in
    # business hours (≥1 active profile's TZ is in window AND it's a weekday),
    # something is wrong.
    weekday = now.weekday() < 5
    recent = supa("send_log?order=sent_at.desc&select=sent_at&limit=1")
    last_send = None
    age_min = None
    if recent and recent[0].get("sent_at"):
        last_send = datetime.fromisoformat(recent[0]["sent_at"].replace("Z", "+00:00"))
        age_min = (now - last_send).total_seconds() / 60
    log(f"  last send: {last_send.isoformat() if last_send else 'NEVER'}  age_min={age_min:.0f}" if age_min is not None else f"  last send: NEVER")

    # CEST is currently in the 08-17 window if 06:00 <= UTC <= 15:00. EDT in 12-21 UTC.
    # Approximate: if it's a weekday and UTC hour in [6, 20], we expect activity.
    in_send_window = weekday and (6 <= now.hour <= 20)
    log(f"  weekday={weekday}  hour_utc={now.hour}  in_send_window={in_send_window}")

    # Queued + overdue?
    qruns = supa("runs?status=eq.queued&select=id,next_send_at&order=next_send_at.asc&limit=2000")
    overdue = [r for r in qruns
               if r.get("next_send_at")
               and datetime.fromisoformat(r["next_send_at"].replace("Z", "+00:00")) <= now]
    log(f"  queued runs: {len(qruns)}  overdue: {len(overdue)}")

    if in_send_window and len(overdue) > 0 and (age_min is None or age_min > 75):
        # Sender appears stuck. Step 1: kill any hung sequence-runner pids > 15min.
        for pid in is_process_running("sequence-runner.py"):
            age = process_age_seconds(pid)
            if age and age > 900:
                kill_pid(pid)
                actions.append(f"killed hung sequence-runner pid={pid} (age {age:.0f}s)")
                log(f"  killed hung pid={pid} (age {age:.0f}s)")
        # Step 2: revive
        if revive_sequence_runner():
            actions.append("spawned sequence-runner tick")
            log("  revived sequence-runner")
    elif not in_send_window:
        log("  outside send window — no remediation needed")
    elif len(overdue) == 0:
        log("  no overdue runs — system healthy or pool exhausted")
    else:
        log(f"  send activity recent ({age_min:.0f}min ago) — healthy")

    # --- Check 2: pool exhaustion across all profiles ---
    enrolled = {r["prospect_id"] for r in
                supa("runs?status=in.(queued,running,paused_replied,paused_bounced)&select=prospect_id&limit=5000")
                if r.get("prospect_id")}
    total_real_pool = 0
    for slug, requires_city in (("aureon", False), ("algoalpha", False), ("atalsolidrocks", True)):
        prosp = supa(f"prospects?profile_slug=eq.{slug}&verified=eq.true&unsubscribed=eq.false"
                     "&select=id,first_name,company,city&limit=10000")
        real = [p for p in prosp
                if p["id"] not in enrolled
                and p.get("first_name") and p.get("company")
                and (not requires_city or p.get("city"))]
        total_real_pool += len(real)
    log(f"  real enrollable pool across all 4 profiles: {total_real_pool}")
    if total_real_pool < 10:
        if not is_process_running("pool-monitor.py") and not is_process_running("lead_scrape.py"):
            try:
                kwargs = {}
                if sys.platform.startswith("win"):
                    kwargs["creationflags"] = subprocess.DETACHED_PROCESS  # type: ignore[attr-defined]
                subprocess.Popen(["py", str(REPO / "scripts" / "pool-monitor.py")],
                                 cwd=str(REPO),
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 **kwargs)
                actions.append(f"spawned pool-monitor (pool depth = {total_real_pool})")
                log("  spawned pool-monitor to refill")
            except Exception as e:
                log(f"  ! pool-monitor spawn failed: {e}")

    # --- Check 3: keep-awake daemon running? ---
    ka_pids = is_process_running("keep-awake.py")
    if not ka_pids:
        log("  keep-awake daemon NOT running — will rely on next logon trigger")
        actions.append("keep-awake daemon was not running (relies on next logon)")
    else:
        log(f"  keep-awake daemon: pids={ka_pids}")

    # Final: alert if any action was taken
    if actions:
        send_alert(
            f"watchdog took {len(actions)} remediation action(s)",
            [
                f"timestamp: {now.isoformat(timespec='seconds')}",
                f"last_send: {last_send.isoformat() if last_send else 'NEVER'}  age={age_min:.0f}min" if age_min is not None else f"last_send: NEVER",
                f"queued: {len(qruns)}  overdue: {len(overdue)}",
                f"real_pool: {total_real_pool}",
                "",
                "actions taken:",
                *[f"  - {a}" for a in actions],
            ],
        )
    log(f"=== watchdog done ({len(actions)} action(s)) ===\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
