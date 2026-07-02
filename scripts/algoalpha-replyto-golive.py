#!/usr/bin/env python3
"""algoalpha-replyto-golive.py — flip AlgoAlpha's Reply-To to the aligned
forwarder reply@tryalgoalpha.com, but ONLY once that forward is proven live.

Runs ON the VPS (the machine that owns the live send path).

Why this exists (deliverability):
  AlgoAlpha sends from *.tryalgoalpha.com; replies currently go to
  info@aureonglobal.de. That From/Reply-To domain mismatch makes some corporate
  spam filters tag the mail as suspected spam. The fix is to reply to
  reply@tryalgoalpha.com (same registrable domain as From), which AlgoAlpha's
  Cloudflare Email Routing forwards to info@aureonglobal.de. We still get every
  reply, but From and Reply-To now align.

The switch has two parts:
  1. sequences/email_render.py: _reply_to_list honours "reply_to_exclusive" and
     does NOT also append the agency inbox. (Deployed as the enabler; a no-op
     until a persona sets the flag.)
  2. Each AlgoAlpha persona: reply_to -> reply@tryalgoalpha.com + reply_to_exclusive.
     IMPORTANT: sequence-runner.py reads personas from the Supabase profiles.config
     column (fetch_profile_config), NOT from profiles/algoalpha.json. So the flip
     MUST update the DB config. We also mirror it into the JSON file so any
     file->DB sync keeps the switch.

SAFETY INTERLOCK: --apply first sends a probe to reply@tryalgoalpha.com and waits
for it to land in info@. If it does not forward, NOTHING is changed. Flipping
reply_to before the forward is live would silently drop every prospect reply. Once
switched, later runs detect it and exit immediately WITHOUT probing.

Usage (intended as an hourly VPS task):
  py scripts/algoalpha-replyto-golive.py            # probe only: is the forward live?
  py scripts/algoalpha-replyto-golive.py --apply    # if live (and not already done), flip
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HENV = REPO / "sequences" / "hostinger.env"
SENV = REPO / "sequences" / "supabase.env"
PROFILE = REPO / "profiles" / "algoalpha.json"
RENDER = REPO / "sequences" / "email_render.py"
LOG = REPO / "logs" / "algoalpha-replyto-golive.log"

SLUG = "algoalpha"
FORWARD_ADDR = "reply@tryalgoalpha.com"
OLD_FILE = '"reply_to": "info@aureonglobal.de",'

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def log(msg: str) -> None:
    """Print and append a timestamped line, so the unattended run leaves a trail."""
    print(msg)
    try:
        from datetime import datetime
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}  {msg}\n")
    except Exception:
        pass


def _read_env(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _sb():
    e = _read_env(SENV)
    return e.get("SUPABASE_URL", "").rstrip("/"), e.get("SUPABASE_SERVICE_KEY", "")


def _sb_get_config() -> dict:
    import httpx
    url, key = _sb()
    r = httpx.get(f"{url}/rest/v1/profiles?slug=eq.{SLUG}&select=config",
                  headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    rows = r.json()
    if not rows:
        raise RuntimeError(f"no {SLUG} profile row in DB")
    return rows[0]["config"]


def _sb_patch_config(cfg: dict) -> None:
    import httpx
    url, key = _sb()
    r = httpx.patch(f"{url}/rest/v1/profiles?slug=eq.{SLUG}",
                    headers={"apikey": key, "Authorization": f"Bearer {key}",
                             "Content-Type": "application/json", "Prefer": "return=minimal"},
                    json={"config": cfg}, timeout=30)
    r.raise_for_status()


def already_switched() -> bool:
    """Authoritative check against the DB config the runner actually reads."""
    try:
        ps = _sb_get_config().get("personas", [])
    except Exception as ex:
        print("  could not read DB config:", type(ex).__name__, str(ex)[:80])
        return False
    return bool(ps) and all(p.get("reply_to") == FORWARD_ADDR for p in ps)


def enabler_present() -> bool:
    return "reply_to_exclusive" in RENDER.read_text(encoding="utf-8", errors="replace")


def probe(wait_s: int = 150) -> bool:
    """Send a tagged mail to reply@tryalgoalpha.com, poll info@ for it. True = forward live."""
    import imaplib
    import httpx  # Resend is behind Cloudflare; bare urllib gets a 1010 bot-block.

    e = _read_env(HENV)
    tag = f"AA-golive-probe-{int(time.time())}"
    r = httpx.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {e.get('RESEND_FULL_ACCESS_API_KEY','')}",
                 "Content-Type": "application/json",
                 "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
        json={"from": "Aureon Reports <reports@hi.aureonglobal.de>",
              "to": [FORWARD_ADDR], "subject": tag,
              "text": "Routing probe; ignore. Confirms reply@tryalgoalpha.com forwards to info@."},
        timeout=30)
    if r.status_code != 200:
        log(f"probe send FAILED (resend {r.status_code}): {r.text[:160]}")
        return False
    print(f"probe sent to {FORWARD_ADDR} (tag {tag}); waiting up to {wait_s}s for it to land in info@ ...")
    user, pw = e.get("SMTP_USER", "info@aureonglobal.de"), e.get("SMTP_PASS", "")
    deadline = time.time() + wait_s
    while time.time() < deadline:
        try:
            M = imaplib.IMAP4_SSL("imap.hostinger.com", 993); M.login(user, pw)
            for folder in ("INBOX", "INBOX.Spam", "Junk"):
                try:
                    if M.select(folder, readonly=True)[0] != "OK":
                        continue
                except Exception:
                    continue
                _, data = M.search(None, f'(SUBJECT "{tag}")')
                if data and data[0]:
                    M.logout(); log(f"forward LIVE (probe {tag} landed in {folder})"); return True
            M.logout()
        except Exception as ex:
            print("  imap check error:", type(ex).__name__, str(ex)[:80])
        time.sleep(15)
    log(f"forward NOT live (probe {tag} never arrived)")
    return False


def flip() -> int:
    """Point every AlgoAlpha persona at the forwarder, in the DB config the runner
    reads AND (best-effort) in the JSON file, so a file->DB sync cannot revert it."""
    cfg = _sb_get_config()
    ps = cfg.get("personas", [])
    n = 0
    for p in ps:
        if p.get("reply_to") != FORWARD_ADDR:
            p["reply_to"] = FORWARD_ADDR
            p["reply_to_exclusive"] = True
            n += 1
    if n == 0:
        return 0
    _sb_patch_config(cfg)
    log(f"flipped {n} persona(s) -> {FORWARD_ADDR} (+ reply_to_exclusive) in DB profiles.config")

    # mirror into the JSON file (in place, line endings preserved) — durability only
    try:
        raw = PROFILE.read_bytes().decode("utf-8")
        if OLD_FILE in raw:
            nl = "\r\n" if "\r\n" in raw else "\n"
            block = f'"reply_to": "{FORWARD_ADDR}",{nl}      "reply_to_exclusive": true,'
            new_raw = raw.replace(OLD_FILE, block)
            json.loads(new_raw)
            PROFILE.write_bytes(new_raw.encode("utf-8"))
            print("  mirrored flip into profiles/algoalpha.json")
    except Exception as ex:
        print("  (file mirror skipped:", type(ex).__name__, str(ex)[:80], ")")
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="if the forward is live, flip the DB config (and mirror to file)")
    a = ap.parse_args()

    if already_switched():
        print("already switched (DB personas reply to the forwarder); nothing to do.")
        return 0

    live = probe()
    if not a.apply:
        print("\n[probe only] Re-run with --apply once this prints 'forward LIVE'.")
        return 0 if live else 1
    if not live:
        print("not applying: forward not live yet (would drop replies). Will retry next run.")
        return 0  # normal, expected state until AlgoAlpha adds the rule; not a task failure
    if not enabler_present():
        log("ABORTED: email_render.py lacks the reply_to_exclusive branch; deploy the enabler first.")
        return 2

    log("forward is live -> flipping AlgoAlpha reply-to (DB config)")
    n = flip()
    try:  # surface the go-live once in the next operator daily report
        sys.path.insert(0, str(REPO / "sequences"))
        import ops_digest
        ops_digest.record("algoalpha-golive", "AlgoAlpha reply-to is now live",
                          f"{n} personas now reply to {FORWARD_ADDR} (Cloudflare forward to info@); "
                          "From/Reply-To aligned for deliverability.")
    except Exception:
        pass
    log("DONE. AlgoAlpha replies now route via reply@tryalgoalpha.com -> info@ (From/Reply-To aligned).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
