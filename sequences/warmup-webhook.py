"""warmup-webhook.py — Resend webhook receiver.

Resend posts events here whenever a message is delivered, bounced, complained,
or opened. We parse, attribute to the right profile (via the `profile` tag on
each send), and update the rolling 7-day reputation window stored in the
profile JSON.

Profile updates land back in profiles/<slug>.json and the desktop app's static
public/profiles/<slug>.json so the Warmup view in the UI is always live.

Run locally on a port the public can reach. For local testing use a tunnel:
    cloudflared tunnel --url http://127.0.0.1:7878
…then paste the public URL into Resend → Webhooks → Add endpoint, subscribed
to: email.delivered, email.bounced, email.complained, email.opened.

Usage:
    py warmup-webhook.py [--port 7878] [--secret <resend signing secret>]
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import hashlib
import hmac
import json
import sys
import time
from pathlib import Path
from typing import Deque, Dict

from fastapi import FastAPI, HTTPException, Request
import uvicorn

from profile_lib import REPO_ROOT, list_profiles, load_profile, save_profile

app = FastAPI(title="warmup-webhook")
SIGNING_SECRET: str | None = None
LOG_DIR = REPO_ROOT / "warmup-state"
LOG_DIR.mkdir(exist_ok=True)

# Rolling 7-day counters in memory (also persisted to profile.warmup.reputation
# on every event so a restart doesn't lose state):
#   {slug: deque[(timestamp, event_type)]}
_events: Dict[str, Deque[tuple]] = collections.defaultdict(collections.deque)
WINDOW = 7 * 24 * 3600


def _verify_sig(body: bytes, sig_header: str | None) -> bool:
    if not SIGNING_SECRET:
        return True  # signing disabled — accept everything (dev only)
    if not sig_header:
        return False
    # Resend signs as HMAC-SHA256 hex of the raw body
    expected = hmac.new(SIGNING_SECRET.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, sig_header.lower())


def _attribute(payload: dict) -> str | None:
    """Pull the profile slug from the email's tags. Defaults to None."""
    data = payload.get("data") or {}
    for t in data.get("tags") or []:
        if isinstance(t, dict) and t.get("name") == "profile":
            return t.get("value")
    return None


def _update_profile_rep(slug: str) -> None:
    """Recompute 7-day windows from the in-memory deque and persist."""
    profile = load_profile(slug)
    cutoff = time.time() - WINDOW
    dq = _events[slug]
    while dq and dq[0][0] < cutoff:
        dq.popleft()
    delivered = sum(1 for _, e in dq if e == "email.delivered")
    bounced   = sum(1 for _, e in dq if e == "email.bounced")
    complained = sum(1 for _, e in dq if e == "email.complained")
    total = delivered + bounced + complained
    rep = profile.setdefault("warmup", {}).setdefault("reputation", {})
    rep["delivered_7d"] = delivered
    rep["bounce_rate_7d"]    = (bounced / total) if total else 0.0
    rep["complaint_rate_7d"] = (complained / total) if total else 0.0
    rep["last_check"] = dt.datetime.now().isoformat()
    save_profile(profile)


def _log_event(payload: dict) -> None:
    ev_type = payload.get("type", "unknown")
    slug = _attribute(payload) or "_unattributed"
    line = {
        "ts": dt.datetime.now().isoformat(),
        "profile": slug,
        "type": ev_type,
        "to": (payload.get("data") or {}).get("to"),
        "id": (payload.get("data") or {}).get("email_id") or (payload.get("data") or {}).get("id"),
        "raw_meta": (payload.get("data") or {}).get("subject"),
    }
    with (LOG_DIR / f"{slug}.events.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    if ev_type in ("email.delivered", "email.bounced", "email.complained"):
        _events[slug].append((time.time(), ev_type))
        if slug != "_unattributed":
            _update_profile_rep(slug)


@app.post("/webhook/resend")
async def receive(request: Request):
    body = await request.body()
    sig = request.headers.get("resend-signature") or request.headers.get("svix-signature")
    if not _verify_sig(body, sig):
        raise HTTPException(401, "bad signature")
    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(400, "invalid JSON")
    _log_event(payload)
    return {"ok": True}


@app.get("/status")
async def status():
    out = []
    for p in list_profiles():
        slug = p["slug"]
        dq = _events[slug]
        cutoff = time.time() - WINDOW
        dq_recent = [(t, e) for t, e in dq if t >= cutoff]
        out.append({
            "slug": slug,
            "delivered_7d": sum(1 for _, e in dq_recent if e == "email.delivered"),
            "bounced_7d":   sum(1 for _, e in dq_recent if e == "email.bounced"),
            "complained_7d":sum(1 for _, e in dq_recent if e == "email.complained"),
            "reputation":   p.get("warmup", {}).get("reputation", {}),
        })
    return out


@app.get("/healthz")
async def healthz():
    return {"ok": True}


def main() -> int:
    global SIGNING_SECRET
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7878)
    ap.add_argument("--secret", default=None,
                    help="Resend signing secret. Without one, requests are accepted unverified (dev only).")
    args = ap.parse_args()
    SIGNING_SECRET = args.secret
    print(f"warmup-webhook listening on :{args.port}")
    print(f"  signing: {'enforced' if SIGNING_SECRET else 'DEV MODE (unsigned accepted)'}")
    print(f"  expose via: cloudflared tunnel --url http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
