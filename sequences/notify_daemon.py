"""notify_daemon.py — Windows system-tray daemon that fires native toast
notifications when new replies, bounces, or unsubscribes land in Supabase,
even when the desktop app is closed.

How it works:
  * pystray draws a gold-on-black "A" icon in the system tray.
  * A worker thread polls Supabase REST every POLL_SECONDS:
      - new rows in `replies`   → toast (different copy by class)
      - rows in `prospects` newly flipped to unsubscribed=true → toast
  * State (last-seen timestamps) lives in warmup-state/notify-state.json so a
    restart never re-fires old events.
  * Right-click menu: Pause, Resume, Mark all seen, Open dashboard, Quit.
  * Clicking the toast opens the local dashboard. Toast also includes an
    "Open" action button when winotify supports it.

Run once to test:
    py sequences/notify_daemon.py

Run on every Windows login (the install script ships a scheduled task):
    schtasks /Create /TN "LES-notify-daemon" /SC ONLOGON ^
      /TR "pythonw C:\\Users\\bernh\\local-email-stack\\sequences\\notify_daemon.py" /F
    (pythonw, not py — so it stays silent without a console window)

No new background services, no servers, no extra cost. Polls Supabase REST
~120 times/hour with conditional filters; well inside the free tier.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import httpx
import pystray
from PIL import Image, ImageDraw, ImageFont
from winotify import Notification, audio

REPO_ROOT     = Path(__file__).resolve().parent.parent
ENV_FILE      = REPO_ROOT / "sequences" / "supabase.env"
STATE_DIR     = REPO_ROOT / "warmup-state"
STATE_FILE    = STATE_DIR / "notify-state.json"
DASHBOARD_URL = "http://127.0.0.1:5173"           # local Tauri dev server
POLL_SECONDS  = 30
APP_ID        = "LocalEmailStack.NotifyDaemon"     # how Windows groups toasts

STATE_DIR.mkdir(exist_ok=True)


# ─── State ──────────────────────────────────────────────────────────────────

def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_reply_at": None, "last_unsub_at": None, "paused": False}


def _save_state(s: dict) -> None:
    STATE_FILE.write_text(json.dumps(s, indent=2), encoding="utf-8")


def _now_iso() -> str:
    return dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"


# ─── Supabase config ────────────────────────────────────────────────────────

def _load_env() -> tuple[str, str]:
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    url, key = env.get("SUPABASE_URL", "").rstrip("/"), env.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        raise SystemExit(f"missing SUPABASE_URL / SUPABASE_ANON_KEY in {ENV_FILE}")
    return url, key


# ─── Polling ────────────────────────────────────────────────────────────────

class Poller(threading.Thread):
    def __init__(self, on_event):
        super().__init__(daemon=True)
        self.on_event = on_event
        self.url, self.key = _load_env()
        self.headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}"}
        self.state = _load_state()
        self._stop = threading.Event()

    def stop(self): self._stop.set()

    def _seed_if_first_run(self) -> None:
        """On a fresh install we don't want to flood the user with every
        historical reply ever. So if state is empty, anchor to 'now' and
        only notify on events after this moment."""
        if not self.state.get("last_reply_at"):
            self.state["last_reply_at"] = _now_iso()
        if not self.state.get("last_unsub_at"):
            self.state["last_unsub_at"] = _now_iso()
        _save_state(self.state)

    def _poll_replies(self, c: httpx.Client) -> None:
        last = self.state["last_reply_at"]
        r = c.get(f"{self.url}/rest/v1/replies",
                  params={"received_at": f"gt.{last}",
                          "select": "id,from_addr,subject,class,body_snippet,received_at",
                          "order":  "received_at.asc",
                          "limit":  "20"},
                  headers=self.headers)
        if r.status_code != 200: return
        rows = r.json()
        if not rows: return
        for row in rows:
            self.on_event("reply", row)
            self.state["last_reply_at"] = row["received_at"]
        _save_state(self.state)

    def _poll_unsubs(self, c: httpx.Client) -> None:
        last = self.state["last_unsub_at"]
        r = c.get(f"{self.url}/rest/v1/prospects",
                  params={"unsubscribed":    "eq.true",
                          "unsubscribed_at": f"gt.{last}",
                          "select": "email,first_name,company,unsubscribed_at",
                          "order":  "unsubscribed_at.asc",
                          "limit":  "10"},
                  headers=self.headers)
        if r.status_code != 200: return
        rows = r.json()
        if not rows: return
        for row in rows:
            self.on_event("unsub", row)
            self.state["last_unsub_at"] = row["unsubscribed_at"]
        _save_state(self.state)

    def run(self) -> None:
        self._seed_if_first_run()
        with httpx.Client(timeout=15) as c:
            while not self._stop.is_set():
                if not self.state.get("paused"):
                    try:
                        self._poll_replies(c)
                        self._poll_unsubs(c)
                    except Exception as e:
                        # Silent on network blips — try again next tick.
                        sys.stderr.write(f"[notify] poll error: {e}\n")
                self._stop.wait(POLL_SECONDS)


# ─── Toast rendering ────────────────────────────────────────────────────────

def _toast(title: str, body: str, sound: bool = True) -> None:
    n = Notification(app_id=APP_ID, title=title, msg=body, launch=DASHBOARD_URL)
    if sound:
        n.set_audio(audio.Default, loop=False)
    n.add_actions(label="Open dashboard", launch=DASHBOARD_URL)
    n.show()


def _render_event(kind: str, row: dict) -> None:
    if kind == "reply":
        klass = row.get("class", "reply")
        frm = (row.get("from_addr") or "(unknown)").strip()
        subj = (row.get("subject") or "").strip()[:80]
        snippet = (row.get("body_snippet") or "").strip().replace("\r", " ").replace("\n", " ")[:160]
        title_by_class = {
            "reply":     f"New reply from {frm[:48]}",
            "bounce":    f"Bounce from {frm[:48]}",
            "complaint": f"Complaint from {frm[:48]}",
            "unrelated": f"New message from {frm[:48]}",
        }
        title = title_by_class.get(klass, f"New email event from {frm[:48]}")
        body  = f"{subj}\n{snippet}" if subj else snippet or "(no body)"
        _toast(title, body, sound=(klass == "reply"))
    elif kind == "unsub":
        who = row.get("first_name") or row.get("email") or "Someone"
        company = row.get("company") or ""
        title = f"{who} unsubscribed"
        body  = f"{company} — {row.get('email','')}"
        _toast(title, body, sound=False)


# ─── Tray icon ──────────────────────────────────────────────────────────────

def _make_icon_image(size: int = 64) -> Image.Image:
    """Draw a gold 'A' on black for the tray icon — matches Aureon brand."""
    img = Image.new("RGBA", (size, size), (10, 10, 10, 255))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", int(size * 0.7))
    except Exception:
        font = ImageFont.load_default()
    text = "A"
    # textbbox is the supported API on Pillow >= 10
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    d.text(((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - 2),
           text, fill="#E6C259", font=font)
    return img


def main() -> int:
    poller: Optional[Poller] = None
    icon: Optional[pystray.Icon] = None

    def open_dashboard(*_): webbrowser.open(DASHBOARD_URL)

    def toggle_pause(*_):
        if not poller: return
        poller.state["paused"] = not poller.state.get("paused", False)
        _save_state(poller.state)
        icon.notify(f"Notifications {'paused' if poller.state['paused'] else 'resumed'}", APP_ID)
        icon.update_menu()

    def mark_all_seen(*_):
        if not poller: return
        now = _now_iso()
        poller.state["last_reply_at"] = now
        poller.state["last_unsub_at"] = now
        _save_state(poller.state)
        icon.notify("Marked all events as seen", APP_ID)

    def quit_app(*_):
        if poller: poller.stop()
        if icon: icon.stop()

    def menu():
        paused = bool(poller and poller.state.get("paused"))
        return pystray.Menu(
            pystray.MenuItem("Open dashboard", open_dashboard, default=True),
            pystray.MenuItem(("Resume notifications" if paused else "Pause notifications"), toggle_pause),
            pystray.MenuItem("Mark all events as seen", mark_all_seen),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", quit_app),
        )

    icon = pystray.Icon(
        "LocalEmailStack", _make_icon_image(),
        title="LocalEmailStack — replies & unsubscribes", menu=menu(),
    )

    poller = Poller(on_event=lambda kind, row: _render_event(kind, row))
    poller.start()

    icon.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
