"""check-supabase-key.py — tell me which Supabase key the backend is using, and
whether it can still READ prospects (i.e. whether RLS would break the backend).

Run BEFORE and AFTER enabling RLS to confirm the service-key swap worked:
    py scripts/check-supabase-key.py

Prints the active key role (anon vs service_role, inferred from the JWT) and does
a live read of one prospects row. If "read: OK" with role=service_role, the
backend will keep working after RLS is enabled. If role=anon and you have already
run the RLS SQL, the backend is BROKEN until you put SUPABASE_SERVICE_KEY in
sequences/supabase.env (see docs/SUPABASE_RLS_FIX_V2.sql).
"""
from __future__ import annotations
import base64
import json
import sys
import urllib.request
import urllib.error
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENV = REPO / "sequences" / "supabase.env"

env = {}
for line in ENV.read_text(encoding="utf-8").splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

URL = env["SUPABASE_URL"].rstrip("/")
# The backend prefers the service key when present, falling back to anon. This
# mirrors what the scripts should do; if your scripts read SUPABASE_ANON_KEY
# directly, putting the service_role value there (server-side only) is the
# zero-code-change activation — the public pages carry their own embedded anon key.
KEY = env.get("SUPABASE_SERVICE_KEY") or env.get("SUPABASE_ANON_KEY", "")


def jwt_role(token: str) -> str:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data.get("role", "unknown")
    except Exception:
        return "unparseable"


def main() -> int:
    role = jwt_role(KEY)
    src = "SUPABASE_SERVICE_KEY" if env.get("SUPABASE_SERVICE_KEY") else "SUPABASE_ANON_KEY"
    print(f"key source : {src}")
    print(f"key role   : {role}")
    # Live read test
    req = urllib.request.Request(
        f"{URL}/rest/v1/prospects?select=email&limit=1",
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
    try:
        rows = json.loads(urllib.request.urlopen(req, timeout=20).read())
        print(f"read test  : OK ({len(rows)} row[s] readable)")
        ok = True
    except urllib.error.HTTPError as e:
        print(f"read test  : BLOCKED (HTTP {e.code}) — {e.read().decode()[:120]}")
        ok = False
    print()
    if role == "service_role" and ok:
        print("=> service_role active and reading. Safe to enable RLS.")
    elif role == "anon" and ok:
        print("=> anon active and reading (RLS is OFF). Add SUPABASE_SERVICE_KEY")
        print("   then re-run before enabling RLS.")
    elif not ok:
        print("=> backend CANNOT read. If RLS is on, set SUPABASE_SERVICE_KEY now.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
