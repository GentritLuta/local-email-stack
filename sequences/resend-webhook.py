"""resend-webhook.py — receive Resend delivery events, write into Supabase.

Resend POSTs every email lifecycle event (delivered / bounced / complained / opened
/ clicked) to a webhook URL we configure in Resend → Webhooks. This service:
  1. Validates the Svix signature (Resend's signing scheme)
  2. Looks up the matching send_log row by resend_id
  3. Updates delivered / bounced / replied / complained / opened_at / clicked_at
  4. Cascades: if bounce → PATCH the run to paused_bounced; if complaint → suppress

Run locally + expose via Cloudflare Tunnel:
    py sequences/resend-webhook.py --port 7879 --secret <svix-secret>
    cloudflared tunnel --url http://127.0.0.1:7879
    # paste the printed *.trycloudflare.com URL into Resend → Webhooks
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
import httpx
import uvicorn

REPO_ROOT = Path(__file__).resolve().parent.parent

app = FastAPI(title="resend-webhook")
SIGNING_SECRET: str | None = None
SUPABASE_URL: str = ""
SUPABASE_KEY: str = ""


def _load_supabase() -> None:
    global SUPABASE_URL, SUPABASE_KEY
    env_path = REPO_ROOT / "sequences" / "supabase.env"
    if not env_path.exists():
        sys.exit("missing sequences/supabase.env")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            if k.strip() == "SUPABASE_URL":     SUPABASE_URL = v.strip().rstrip("/")
            if k.strip() == "SUPABASE_ANON_KEY": SUPABASE_KEY = v.strip()
    if not SUPABASE_URL or not SUPABASE_KEY:
        sys.exit("supabase.env missing SUPABASE_URL or SUPABASE_ANON_KEY")


def _verify_svix(headers: dict, body: bytes) -> bool:
    """Svix HMAC-SHA256 over <msg-id>.<timestamp>.<body>, base64-encoded."""
    if not SIGNING_SECRET:
        return True  # dev mode
    msg_id = headers.get("svix-id", "")
    ts     = headers.get("svix-timestamp", "")
    sig_hdr = headers.get("svix-signature", "")
    if not msg_id or not ts or not sig_hdr:
        return False
    # secret format: whsec_<base64>
    secret = SIGNING_SECRET
    if secret.startswith("whsec_"):
        secret = secret[len("whsec_"):]
    try:
        secret_bytes = base64.b64decode(secret)
    except Exception:
        return False
    signed_content = f"{msg_id}.{ts}.{body.decode('utf-8', errors='ignore')}".encode()
    digest = hmac.new(secret_bytes, signed_content, hashlib.sha256).digest()
    expected = base64.b64encode(digest).decode()
    # sig_hdr is space-separated list of "v1,<sig>" entries
    for token in sig_hdr.split(" "):
        if not token.startswith("v1,"):
            continue
        if hmac.compare_digest(expected, token[3:]):
            return True
    return False


async def _patch_send_log(client: httpx.AsyncClient, resend_id: str, patch: dict) -> None:
    if not resend_id:
        return
    await client.patch(f"{SUPABASE_URL}/rest/v1/send_log",
                       params={"resend_id": f"eq.{resend_id}"},
                       json=patch)


async def _resolve_run(client: httpx.AsyncClient, resend_id: str) -> str | None:
    r = await client.get(f"{SUPABASE_URL}/rest/v1/send_log",
                         params={"resend_id": f"eq.{resend_id}", "select": "run_id"})
    if r.status_code == 200 and r.json():
        return r.json()[0].get("run_id")
    return None


async def _pause_run(client: httpx.AsyncClient, run_id: str, reason: str) -> None:
    await client.patch(f"{SUPABASE_URL}/rest/v1/runs",
                       params={"id": f"eq.{run_id}"},
                       json={"status": f"paused_{reason}"})


@app.post("/webhook/resend")
async def webhook(req: Request):
    body = await req.body()
    if not _verify_svix({k.lower(): v for k, v in req.headers.items()}, body):
        raise HTTPException(401, "bad signature")
    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(400, "invalid JSON")

    event_type = payload.get("type", "")
    data = payload.get("data", {}) or {}
    resend_id = data.get("email_id") or data.get("id") or ""

    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
               "Content-Type": "application/json", "Prefer": "return=minimal"}
    async with httpx.AsyncClient(timeout=15, headers=headers) as c:
        patch: dict = {}
        if event_type == "email.delivered":
            patch["delivered"] = True
        elif event_type == "email.bounced":
            patch["bounced"] = True; patch["delivered"] = False
            patch["error"]   = data.get("bounce", {}).get("message") or "bounced"
            run = await _resolve_run(c, resend_id)
            if run: await _pause_run(c, run, "bounced")
        elif event_type == "email.complained":
            patch["complained"] = True
            run = await _resolve_run(c, resend_id)
            if run: await _pause_run(c, run, "bounced")
        elif event_type == "email.opened":
            patch["opened_at"] = data.get("created_at") or None
        elif event_type == "email.clicked":
            patch["clicked_at"] = data.get("created_at") or None
        if patch:
            await _patch_send_log(c, resend_id, patch)
    return {"ok": True, "type": event_type, "id": resend_id}


@app.get("/healthz")
async def healthz():
    return {"ok": True}


def main() -> int:
    global SIGNING_SECRET
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=7879)
    ap.add_argument("--secret", default=None,
                    help="Resend webhook signing secret (whsec_...). If omitted, requests are accepted unverified (dev only).")
    args = ap.parse_args()
    SIGNING_SECRET = args.secret or os.environ.get("RESEND_WEBHOOK_SECRET")
    _load_supabase()
    print(f"resend-webhook listening on :{args.port}  signing={'enforced' if SIGNING_SECRET else 'DEV (unsigned ok)'}")
    print(f"  Supabase: {SUPABASE_URL}")
    print(f"  Expose with: cloudflared tunnel --url http://127.0.0.1:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    sys.exit(main())
