#!/usr/bin/env python3
"""rotate-leaked-secrets.py — turnkey rotation of the two secrets that leaked in
_dorian_12.py (GitGuardian, 2026-07-02): the shared Resend API key and the
Hostinger DNS token (HOSTINGER_API_TOKEN_DORIAN).

You rotate the keys in the dashboards; this script does the tedious part: it
swaps the OLD value for the NEW one everywhere it lives, on the laptop, then
syncs to the VPS. It NEVER prints or logs a key value, and reads the new values
from a hidden prompt (getpass), so nothing lands in shell history.

Where each secret lives (auto-detected, value-based replace):
  - Resend key : profiles/*.private.json (relay.resend_api_key) + sequences/hostinger.env
                 (RESEND_FULL_ACCESS_API_KEY, RESEND_NEW_ACCOUNT_API_KEY)
  - DNS token  : sequences/hostinger.env (HOSTINGER_API_TOKEN_DORIAN)

SAFE ORDER (do it this way to avoid a send outage):
  1. In Resend, CREATE a new key (do NOT revoke the old one yet).
     In Hostinger, create the new API token.
  2. Run:  py scripts/rotate-leaked-secrets.py --sync-vps
     Paste the new value(s) when prompted. It updates laptop + VPS.
  3. Verify a send/report works (both old and new keys are valid right now).
  4. THEN revoke the OLD key/token in the dashboards.

Usage:
  py scripts/rotate-leaked-secrets.py --dry        # show where the old values are, change nothing
  py scripts/rotate-leaked-secrets.py              # prompt + replace on the laptop
  py scripts/rotate-leaked-secrets.py --sync-vps   # also scp updated files to the VPS
"""
from __future__ import annotations

import argparse
import datetime as dt
import getpass
import glob
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV = REPO / "sequences" / "hostinger.env"
VPS = "Administrator@188.209.157.127"
VPS_REPO = "C:/Users/Administrator/local-email-stack"
SSH_KEY = str(Path.home() / ".ssh" / "id_ed25519_hostinger")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def detect_old_resend() -> str:
    for f in glob.glob(str(REPO / "profiles" / "*.private.json")):
        try:
            k = (json.load(open(f, encoding="utf-8")).get("relay") or {}).get("resend_api_key")
        except Exception:
            k = None
        if k:
            return k
    return ""


def env_value(var: str) -> str:
    if not ENV.exists():
        return ""
    for line in ENV.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, v = s.split("=", 1)
            if k.strip() == var:
                return v.strip().strip('"').strip("'")
    return ""


def target_files() -> list[Path]:
    files = [Path(p) for p in glob.glob(str(REPO / "profiles" / "*.private.json"))]
    if ENV.exists():
        files.append(ENV)
    return files


def count_occurrences(old: str) -> dict[str, int]:
    out = {}
    if not old:
        return out
    for f in target_files():
        try:
            n = f.read_text(encoding="utf-8", errors="replace").count(old)
        except Exception:
            n = 0
        if n:
            out[str(f.relative_to(REPO))] = n
    return out


def replace_everywhere(old: str, new: str, stamp: str) -> list[Path]:
    changed = []
    for f in target_files():
        txt = f.read_text(encoding="utf-8", errors="replace")
        if old and old in txt:
            f.with_suffix(f.suffix + f".bak-{stamp}").write_text(txt, encoding="utf-8")
            f.write_text(txt.replace(old, new), encoding="utf-8")
            changed.append(f)
    return changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry", action="store_true", help="show where the old values are; change nothing")
    ap.add_argument("--sync-vps", action="store_true", help="scp updated files to the VPS after replacing")
    a = ap.parse_args()

    old_resend = detect_old_resend()
    old_dns = env_value("HOSTINGER_API_TOKEN_DORIAN")

    print("Current (leaked) values found in:")
    print("  Resend key:", count_occurrences(old_resend) or "NOT FOUND")
    print("  DNS token :", count_occurrences(old_dns) or "NOT FOUND")
    if a.dry:
        print("\n[DRY] nothing changed. Re-run without --dry to rotate.")
        return 0

    print("\nPaste the NEW values (input hidden). Leave blank to skip that one.")
    new_resend = getpass.getpass("  NEW Resend API key: ").strip()
    new_dns = getpass.getpass("  NEW Hostinger DNS token: ").strip()
    if not new_resend and not new_dns:
        print("nothing to do (both blank)."); return 0
    if new_resend and (len(new_resend) < 20 or new_resend == old_resend):
        print("! new Resend key looks wrong (too short or same as old) — aborting."); return 2
    if new_dns and (len(new_dns) < 20 or new_dns == old_dns):
        print("! new DNS token looks wrong (too short or same as old) — aborting."); return 2

    stamp = "rotate"
    changed: set[Path] = set()
    if new_resend and old_resend:
        changed.update(replace_everywhere(old_resend, new_resend, stamp))
    if new_dns and old_dns:
        changed.update(replace_everywhere(old_dns, new_dns, stamp))

    print(f"\nupdated {len(changed)} file(s) on the laptop (backups written as *.bak-{stamp}):")
    for f in sorted(changed):
        print("  ", f.relative_to(REPO))

    # sanity: no target file should still contain an old value we replaced
    left = {}
    if new_resend:
        left.update({k: v for k, v in count_occurrences(old_resend).items()})
    if new_dns:
        left.update({k: v for k, v in count_occurrences(old_dns).items()})
    print("remaining old-value occurrences after replace:", left or "none (clean)")

    if a.sync_vps and changed:
        print("\nsyncing updated files to the VPS...")
        for f in sorted(changed):
            rel = f.relative_to(REPO).as_posix()
            dst = f"{VPS}:{VPS_REPO}/{rel}"
            r = subprocess.run(["scp", "-i", SSH_KEY, "-o", "StrictHostKeyChecking=no",
                                "-o", "ConnectTimeout=25", str(f), dst],
                               capture_output=True, text=True)
            print(f"  {'ok ' if r.returncode == 0 else 'FAIL'} {rel}")
    elif a.sync_vps:
        print("nothing changed, skipped VPS sync.")

    print("\nDONE. The scheduled tasks read the key fresh each tick, so no restart needed.")
    print("Now verify a send/report works, THEN revoke the OLD key + token in the dashboards.")
    print("When satisfied, delete the *.bak-rotate backups.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
