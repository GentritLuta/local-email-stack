# -*- coding: utf-8 -*-
"""dial.py - outbound dialer for the AI voice agent.

It does exactly one thing safely: pull CONSENTED, callable leads, run each through
the compliance gate, and only then place a call that bridges to agent.py. Every
lead passes compliance.can_call() - there is no path that dials a number the gate
rejects. Refusals are logged, not dialed.

    python dial.py --limit 20            # dial up to 20 gated leads
    python dial.py --limit 20 --dry      # show who WOULD be dialed + why, place nothing

Speed-to-lead: leads are ordered freshest-consent-first, so a funnel opt-in gets a
call within minutes, which is where AI voice actually converts.
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compliance

REPO = Path(__file__).resolve().parent.parent


def _env() -> dict:
    env = dict(os.environ)
    for p in (Path(__file__).resolve().parent / ".env",
              REPO / "sequences" / "supabase.env"):
        if p.exists():
            for ln in p.read_text(encoding="utf-8").splitlines():
                if "=" in ln and not ln.strip().startswith("#"):
                    k, v = ln.split("=", 1)
                    env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    return env


ENV = _env()
SUPA_URL = ENV.get("SUPABASE_URL", "").rstrip("/")
# Service key so the dialer can read leads + write outcomes under the locked RLS.
SUPA_KEY = ENV.get("SUPABASE_SERVICE_KEY") or ENV.get("SUPABASE_ANON_KEY", "")
H = {"apikey": SUPA_KEY, "Authorization": f"Bearer {SUPA_KEY}",
     "Content-Type": "application/json"}


def fetch_callable_leads(limit: int) -> list[dict]:
    """Consented, phone-bearing, un-suppressed leads, freshest consent first.

    The consent filter is applied in the query AND re-checked by can_call(); the
    query is an optimization, can_call() is the authority.
    """
    q = ("prospects?select=id,email,phone,state,consent_to_ai_call,dnc,unsubscribed,"
         "call_consent_at,last_call_at,custom_fields"
         "&consent_to_ai_call=eq.true&phone=not.is.null"
         "&dnc=eq.false&unsubscribed=eq.false"
         "&order=call_consent_at.desc.nullslast"
         f"&limit={limit}")
    r = httpx.get(f"{SUPA_URL}/rest/v1/{q}", headers=H, timeout=30)
    r.raise_for_status()
    return r.json()


def log_outcome(lead_id: str, outcome: str, note: str = "") -> None:
    body = {"last_call_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "call_outcome": outcome}
    if outcome == "do_not_call":
        body["dnc"] = True          # a "remove me" on the call is a hard suppress
    httpx.patch(f"{SUPA_URL}/rest/v1/prospects?id=eq.{lead_id}", headers=H,
                json=body, timeout=30)
    if note:
        print(f"    note: {note}")


def place_call(lead: dict, dry: bool) -> str:
    """Originate a Telnyx call and bridge its media to agent.run_call().

    INTEGRATION POINT (needs the Telnyx number/key + the RTX box online):
    Telnyx Call Control -> answer webhook -> stream media over websocket into the
    Pipecat transport that agent.build_pipeline() consumes. The disclosure is the
    forced first line (see agent.py). Until Telnyx creds + RTX are live, --dry is
    the only safe mode and this raises if asked to really dial.
    """
    if dry:
        return "dry"
    if not (ENV.get("TELNYX_API_KEY") and ENV.get("TELNYX_FROM_NUMBER")):
        raise RuntimeError("no Telnyx creds in env - cannot place a real call yet")
    # TODO(go-live): implement Telnyx origination + media bridge to agent.run_call().
    # Deliberately not stubbed as a silent no-op so a half-configured run fails loud.
    raise NotImplementedError(
        "Telnyx origination + media bridge not wired yet. Add creds and implement "
        "the bridge before removing --dry. See README 'Go-live checklist'.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    if not SUPA_URL or not SUPA_KEY:
        print("missing SUPABASE_URL / SUPABASE_SERVICE_KEY"); return 1

    leads = fetch_callable_leads(args.limit)
    print(f"pulled {len(leads)} consented candidate(s)"
          + ("  [DRY RUN]" if args.dry else ""))
    dialed = skipped = 0
    for L in leads:
        ok, reason = compliance.can_call(L)           # <-- the hard gate, always
        who = L.get("phone") or L.get("email") or L.get("id")
        if not ok:
            skipped += 1
            print(f"  SKIP  {who:20} : {reason}")
            continue
        print(f"  CALL  {who:20} : {reason}"
              + ("  (dry, not dialed)" if args.dry else ""))
        try:
            place_call(L, args.dry)
            dialed += 1
        except (RuntimeError, NotImplementedError) as e:
            print(f"        not placed: {e}")
            break   # config/go-live gap affects all rows; stop rather than spam errors
    print(f"\ndone: {dialed} callable, {skipped} gated out"
          + ("  (dry run - nothing dialed)" if args.dry else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
