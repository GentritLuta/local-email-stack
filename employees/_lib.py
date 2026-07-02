"""Shared plumbing for the AI-employee framework.

One place for: env loading, the headless-Claude call, the operator email send,
and the on-disk layout. Mirrors the patterns already used in sequences/
(clarity_gate.py for the Claude CLI, meeting-followup.py for Resend send).
"""
import json
import os
import ssl
import smtplib
import subprocess
import sys
import urllib.request
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

# Windows console is cp1252; employee output contains EUR, <=, and other
# non-cp1252 characters. Make all stdout/stderr UTF-8 safe so terminal review
# never crashes on a print.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

OPERATOR_ADDR = "info@aureonglobal.de"
UA = "Mozilla/5.0 (AureonEmployee/1.0)"

REPO = Path(__file__).resolve().parents[1]          # local-email-stack/
HERE = Path(__file__).resolve().parent              # employees/
ROLES_DIR = HERE / "roles"
STATE_DIR = HERE / "state"

# Claude CLI (same resolution clarity_gate.py uses)
_CLAUDE_EXE = r"D:\npm-global\node_modules\@anthropic-ai\claude-code\bin\claude.exe"
CLAUDE_CMD = os.environ.get("CLAUDE_CLI") or (
    _CLAUDE_EXE if os.path.exists(_CLAUDE_EXE) else r"D:\npm-global\claude.cmd")


def load_env(path: Path) -> dict:
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


HOST = load_env(REPO / "sequences" / "hostinger.env")
RESEND_KEY = (HOST.get("RESEND_NEW_ACCOUNT_API_KEY")
              or HOST.get("RESEND_FULL_ACCESS_API_KEY")
              or HOST.get("RESEND_API_KEY", ""))


# ─── per-role on-disk layout ────────────────────────────────────────────────

def role_paths(role: str) -> dict:
    base = STATE_DIR / role
    paths = {
        "base": base,
        "memory": base / "memory.json",
        "pending": base / "pending",
        "approved": base / "approved",
        "reports": base / "reports",
        "data": base / "data-inbox",
    }
    for key in ("pending", "approved", "reports", "data"):
        paths[key].mkdir(parents=True, exist_ok=True)
    return paths


def load_memory(role: str) -> dict:
    p = role_paths(role)["memory"]
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"role": role, "standing_context": "", "runs": []}


def save_memory(role: str, mem: dict) -> None:
    p = role_paths(role)["memory"]
    p.write_text(json.dumps(mem, indent=2, ensure_ascii=False), encoding="utf-8")


def load_charter(role: str) -> str:
    p = ROLES_DIR / f"{role}.md"
    if not p.exists():
        raise SystemExit(f"No charter for role '{role}'. Expected {p}")
    return p.read_text(encoding="utf-8", errors="replace")


def list_roles() -> list:
    return sorted(p.stem for p in ROLES_DIR.glob("*.md"))


# ─── the employee's brain: one headless Claude call ─────────────────────────

# Tools the employee MAY use. Note: no Bash, no send scripts, no Write/Edit. It
# can research and read the operator's files, but it cannot write files or ship
# anything. The work product is returned as text; shipping only happens after you
# approve, via review.py.
_ALLOWED_TOOLS = "WebSearch,WebFetch,Read,Glob,Grep"


def ask_claude(system: str, prompt: str, cwd: Path, timeout: int = 900) -> str:
    """Run the employee's reasoning headlessly and return raw stdout."""
    cwd.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [CLAUDE_CMD, "-p",
         "--append-system-prompt", system,
         "--allowedTools", _ALLOWED_TOOLS,
         "--permission-mode", "acceptEdits",
         "--setting-sources", "user"],
        input=prompt, capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace", cwd=str(cwd),
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError(f"Claude returned nothing. stderr: {(proc.stderr or '')[:500]}")
    return out


# ─── operator email (the 'push' on approval) ────────────────────────────────

def send_email(to_addr: str, subject: str, body: str,
               from_addr: str = OPERATOR_ADDR, from_name: str = "AI Employee",
               dry: bool = False) -> bool:
    """Generic send (Resend, Hostinger SMTP fallback). Used both for the
    operator report and for approved third-party actions."""
    if dry:
        print(f"  [DRY] would email {to_addr}: '{subject}' ({len(body)} chars)")
        return True
    payload = {"from": f"{from_name} <{from_addr}>", "to": [to_addr],
               "subject": subject[:200], "text": body, "reply_to": from_addr}
    req = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(payload).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {RESEND_KEY}",
                 "Content-Type": "application/json", "User-Agent": UA})
    try:
        urllib.request.urlopen(req, timeout=20)
        return True
    except Exception as e:
        try:  # Hostinger SMTP fallback, same as meeting-followup.py
            pw = HOST.get("SMTP_PASS", "")
            user = HOST.get("SMTP_USER", OPERATOR_ADDR)
            m = MIMEText(body, "plain", "utf-8")
            m["Subject"] = subject[:200]
            m["From"] = f"{from_name} <{user}>"
            m["To"] = to_addr
            m["Reply-To"] = user
            with smtplib.SMTP_SSL("smtp.hostinger.com", 465,
                                  context=ssl.create_default_context()) as s:
                s.login(user, pw)
                s.sendmail(user, [to_addr], m.as_string())
            return True
        except Exception as e2:
            print(f"  ! send failed (resend: {e}; smtp: {e2})")
            return False


def send_to_operator(subject: str, body: str, dry: bool = False,
                     to_addr: str = OPERATOR_ADDR) -> bool:
    return send_email(to_addr, subject, body, dry=dry)


# ─── local-RTX-model backend (roles with "backend": "local" in their config) ──

def ask_local_agent(system: str, prompt: str, cwd: Path, timeout: int = 900) -> str:
    """Drop-in alternative to ask_claude() that reasons on the RTX's local Ollama
    model instead of the paid cloud, via a real tool-calling loop (news/wikipedia/
    image search + read-only data-inbox access). See local_agent.py."""
    import local_agent
    return local_agent.ask_local_agent(system, prompt, cwd, timeout)


# ─── per-role config (can this employee send to third parties on approval?) ──

def load_role_config(role: str) -> dict:
    cfg = {"can_send": False, "send_from": OPERATOR_ADDR, "send_name": "Gentrit"}
    p = ROLES_DIR / f"{role}.config.json"
    if p.exists():
        try:
            cfg.update(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            pass
    return cfg


def set_role_config(role: str, **changes) -> dict:
    p = ROLES_DIR / f"{role}.config.json"
    cfg = {}
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            cfg = {}
    cfg.update(changes)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return cfg


# ─── standing orders (permanent rules) + routine (recurring work) ────────────
# Two human-editable markdown files per role. Standing orders are injected into
# EVERY shift verbatim and are how the operator stops the same mistake twice.
# The routine is the recurring checklist the employee runs each shift.

def _orders_path(role: str):
    return role_paths(role)["base"] / "standing_orders.md"


def _routine_path(role: str):
    return role_paths(role)["base"] / "routine.md"


def load_standing_orders(role: str) -> str:
    p = _orders_path(role)
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def load_routine(role: str) -> str:
    p = _routine_path(role)
    return p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""


def append_standing_order(role: str, text: str) -> None:
    text = text.strip()
    if not text:
        return
    p = _orders_path(role)
    if not p.exists():
        p.write_text("# Standing orders for the " + role + "\n\n"
                     "Permanent rules from the operator. The employee follows every one, "
                     "every shift, and never repeats a mistake covered here.\n\n",
                     encoding="utf-8")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"- ({today()}) {text}\n")


def append_routine(role: str, text: str) -> None:
    text = text.strip()
    if not text:
        return
    p = _routine_path(role)
    if not p.exists():
        p.write_text("# Daily routine for the " + role + "\n\n"
                     "The recurring work this employee runs each shift, in order.\n\n",
                     encoding="utf-8")
    with p.open("a", encoding="utf-8") as f:
        f.write(f"- {text}\n")


def now_stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")


def today() -> str:
    return datetime.now().strftime("%Y-%m-%d")
