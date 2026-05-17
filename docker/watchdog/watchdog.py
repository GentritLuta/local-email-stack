"""watchdog.py — innovation #9, self-healing service supervisor.

Subscribes to Docker events. When a container restarts > 3 times in 10 min,
performs a targeted recovery action specific to that service. Only pages a
human (via Alertmanager → Telegram/Discord) if auto-recovery fails.

Recovery playbook is per-service. Default is "let Docker restart-policy handle
it"; only special-cases get explicit handlers.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections import defaultdict, deque
from datetime import datetime, timezone

import docker
import httpx
import paramiko

ALERTMANAGER_URL = os.environ.get("ALERTMANAGER_URL", "http://alertmanager:9093/api/v1/alerts")
ORACLE_SSH_HOST = os.environ.get("ORACLE_SSH_HOST", "")
ORACLE_SSH_USER = os.environ.get("ORACLE_SSH_USER", "ubuntu")
ORACLE_SSH_KEY = os.environ.get("ORACLE_SSH_KEY", "/keys/oracle_postal_rsa")
LITELLM_CONFIG_PATH = os.environ.get("LITELLM_CONFIG_PATH", "/litellm/config.yaml")
ROUTE_PICKER_URL = os.environ.get("ROUTE_PICKER_URL", "http://route-picker:8000")

WINDOW_SECONDS = 600
RESTART_THRESHOLD = 3


# ─── Recovery actions ──────────────────────────────────────────────────────

async def recover_ollama(client: docker.DockerClient) -> bool:
    """Switch LiteLLM to the smaller Qwen 14B model and force-reload config.
    Stack keeps working at degraded quality until Ollama stabilizes.
    """
    try:
        with open(LITELLM_CONFIG_PATH, "r") as f:
            content = f.read()
        if "qwen2.5:14b" in content:
            return True  # already on fallback
        content = content.replace(
            "qwen2.5:32b-instruct-q4_K_M",
            "qwen2.5:14b-instruct-q4_K_M",
        )
        with open(LITELLM_CONFIG_PATH, "w") as f:
            f.write(content)
        litellm = client.containers.get("docker-litellm-1")
        litellm.restart()
        return True
    except Exception as e:
        print(f"recover_ollama failed: {e}")
        return False


async def recover_browserless(client: docker.DockerClient) -> bool:
    """Browserless is stateless — a full container recreate usually resolves it."""
    try:
        client.containers.get("docker-browserless-1").remove(force=True)
        # Compose will recreate via restart-policy.
        await asyncio.sleep(15)
        return True
    except Exception as e:
        print(f"recover_browserless failed: {e}")
        return False


async def recover_oracle_postal() -> bool:
    """SSH to the Oracle VM and restart Postal + Tailscale. Last resort:
    disable POSTAL_ORACLE route so other free-tier routes take over.
    """
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ORACLE_SSH_HOST, username=ORACLE_SSH_USER,
                    key_filename=ORACLE_SSH_KEY, timeout=20)
        ssh.exec_command("sudo systemctl restart postal && sudo systemctl restart tailscaled")
        ssh.close()
        return True
    except Exception as e:
        print(f"recover_oracle_postal SSH failed: {e}")
        # Fallback: tell route-picker to disable POSTAL_ORACLE
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                await c.post(f"{ROUTE_PICKER_URL}/route/disable",
                             json={"route": "POSTAL_ORACLE"})
            return True
        except Exception:
            return False


HANDLERS = {
    "docker-ollama-1":      lambda c: recover_ollama(c),
    "docker-browserless-1": lambda c: recover_browserless(c),
}

# Special-case: the Oracle VM doesn't appear in local Docker events, but the
# route-picker reports POSTAL_ORACLE failures via /route/health.


# ─── Event loop ────────────────────────────────────────────────────────────

async def main() -> None:
    client = docker.from_env()
    history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=20))

    print("watchdog: starting Docker event loop")

    loop = asyncio.get_running_loop()

    def events_iter():
        for event in client.events(decode=True):
            yield event

    # Run blocking events iterator in a thread
    queue: asyncio.Queue = asyncio.Queue(maxsize=100)

    def feeder():
        for ev in events_iter():
            loop.call_soon_threadsafe(queue.put_nowait, ev)

    feeder_task = loop.run_in_executor(None, feeder)

    # Periodically poll Oracle Postal health
    async def poll_oracle():
        while True:
            try:
                async with httpx.AsyncClient(timeout=5) as c:
                    r = await c.get(f"{ROUTE_PICKER_URL}/route/health/POSTAL_ORACLE")
                if r.status_code == 200 and r.json().get("healthy") is False:
                    print("watchdog: POSTAL_ORACLE unhealthy, attempting SSH recovery")
                    ok = await recover_oracle_postal()
                    if not ok:
                        await page_human("POSTAL_ORACLE down; auto-recovery failed")
            except Exception:
                pass
            await asyncio.sleep(60)

    asyncio.create_task(poll_oracle())

    while True:
        ev = await queue.get()
        if ev.get("Type") != "container":
            continue
        action = ev.get("Action")
        name = (ev.get("Actor", {}).get("Attributes", {}) or {}).get("name", "")
        if not name or action not in ("die", "restart", "oom"):
            continue
        now = time.time()
        history[name].append(now)
        cutoff = now - WINDOW_SECONDS
        recent = [t for t in history[name] if t >= cutoff]
        if len(recent) < RESTART_THRESHOLD:
            continue

        print(f"watchdog: {name} restarted {len(recent)}x in {WINDOW_SECONDS}s — attempting recovery")
        handler = HANDLERS.get(name)
        if handler:
            ok = await handler(client)
            if ok:
                print(f"watchdog: {name} recovery completed; clearing history")
                history[name].clear()
            else:
                await page_human(f"{name} auto-recovery failed after {len(recent)} restarts")
        else:
            # No special handler — let Docker keep retrying but page after threshold * 2
            if len(recent) >= RESTART_THRESHOLD * 2:
                await page_human(f"{name} restarting in tight loop; no auto-recovery defined")
                history[name].clear()


async def page_human(message: str) -> None:
    alert = [{
        "labels": {"alertname": "WatchdogRecoveryFailed", "severity": "critical"},
        "annotations": {"summary": message},
        "startsAt": datetime.now(timezone.utc).isoformat(),
    }]
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.post(ALERTMANAGER_URL, json=alert)
    except Exception as e:
        print(f"watchdog: failed to page human: {e}")


if __name__ == "__main__":
    asyncio.run(main())
