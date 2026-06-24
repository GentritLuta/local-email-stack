# -*- coding: utf-8 -*-
"""payoneer_lib.py — initiate a charge / payment request against a client's
billing profile via Payoneer.

Kosovo-reality note: a Kosovo-registered business CANNOT be a card acquirer
(Stripe/Mollie) or a SEPA Direct Debit creditor — those rails are closed to
Kosovo entities. Payoneer is the working option. There are two access levels:

  • Plain account  -> "Request a Payment": YOU initiate a payment request, the
    client gets a link/email and approves the charge. Semi-active.
  • Approved API   -> "Billing Service" / Request Payment API: YOU initiate the
    charge programmatically and Payoneer pulls from the client's authorized
    funding method. Active. Requires Payoneer to approve API access for the
    account (program/partner id + API username + token).

This module talks to the approved API when credentials are present, and is a
clean no-op (returns a 'not_configured' result) otherwise, so the rest of the
stack works before Payoneer access is granted.

Config — sequences/payoneer.env (create when you have credentials):
    PAYONEER_BASE=https://api.payoneer.com           # or sandbox host
    PAYONEER_PROGRAM_ID=<your program/partner id>
    PAYONEER_CLIENT_ID=<api username / client id>
    PAYONEER_CLIENT_SECRET=<api token / secret>
    PAYONEER_LIVE=false                               # true to actually charge

Usage:
    from payoneer_lib import charge_client
    res = charge_client(billing_profile, amount_cents=50000, currency="EUR",
                        invoice_ref="AG-ATAL-2026-003",
                        description="AUREON Global — services")
    # res = {"status": "requested|charged|failed|not_configured|dry_run", ...}
"""
from __future__ import annotations
import base64, json, time, urllib.request, urllib.parse
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _load_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); out[k.strip()] = v.strip()
    return out


ENV = _load_env(REPO / "sequences" / "payoneer.env")
BASE = (ENV.get("PAYONEER_BASE") or "https://api.payoneer.com").rstrip("/")
PROGRAM_ID = ENV.get("PAYONEER_PROGRAM_ID")
CLIENT_ID = ENV.get("PAYONEER_CLIENT_ID")
CLIENT_SECRET = ENV.get("PAYONEER_CLIENT_SECRET")
LIVE = (ENV.get("PAYONEER_LIVE", "false").lower() == "true")

_token_cache: dict = {"value": None, "exp": 0.0}


def configured() -> bool:
    return bool(PROGRAM_ID and CLIENT_ID and CLIENT_SECRET)


def _post(path: str, body: dict, token: str | None = None, form: bool = False) -> dict:
    url = f"{BASE}{path}"
    if form:
        data = urllib.parse.urlencode(body).encode()
        ctype = "application/x-www-form-urlencoded"
    else:
        data = json.dumps(body).encode()
        ctype = "application/json"
    headers = {"Content-Type": ctype, "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.loads(r.read().decode() or "{}")


def _token() -> str:
    """OAuth2 client-credentials bearer token (cached until ~60s before expiry)."""
    now = time.time()
    if _token_cache["value"] and _token_cache["exp"] - 60 > now:
        return _token_cache["value"]
    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    req = urllib.request.Request(
        f"{BASE}/v4/programs/{PROGRAM_ID}/token",
        data=urllib.parse.urlencode({"grant_type": "client_credentials",
                                     "scope": "read write"}).encode(),
        headers={"Authorization": f"Basic {basic}",
                 "Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"},
        method="POST")
    with urllib.request.urlopen(req, timeout=40) as r:
        tok = json.loads(r.read().decode())
    _token_cache["value"] = tok.get("access_token")
    _token_cache["exp"] = now + float(tok.get("expires_in", 3000))
    return _token_cache["value"]


def charge_client(billing: dict, *, amount_cents: int, currency: str = "EUR",
                  invoice_ref: str, description: str = "") -> dict:
    """Initiate a Payoneer charge / payment request for a billing profile.

    Returns a dict with a 'status':
      not_configured — no Payoneer credentials yet (stack still works)
      dry_run        — configured but PAYONEER_LIVE != true (logs intent only)
      requested      — payment request created (client must approve)
      charged        — charge captured (approved Billing-Service API)
      failed         — Payoneer returned an error
    """
    payee = (billing or {}).get("payoneer_email") or (billing or {}).get("billing_email")
    amount = round(amount_cents / 100.0, 2)

    if not configured():
        return {"status": "not_configured",
                "detail": "Add sequences/payoneer.env with PAYONEER_* credentials."}

    if not payee:
        return {"status": "failed", "detail": "no payoneer_email/billing_email on profile"}

    if not LIVE:
        return {"status": "dry_run", "payee": payee, "amount": amount,
                "currency": currency, "invoice_ref": invoice_ref,
                "detail": "PAYONEER_LIVE=false — set true to charge for real."}

    # Approved Billing-Service / Request-Payment call. The exact endpoint + body
    # are confirmed against your Payoneer API package on activation; this is the
    # documented charge-request shape (program-scoped, idempotent on invoice_ref).
    try:
        token = _token()
        body = {
            "payee_id": payee,
            "amount": amount,
            "currency": currency,
            "client_reference_id": invoice_ref,
            "description": description or f"AUREON Global — {invoice_ref}",
        }
        resp = _post(f"/v4/programs/{PROGRAM_ID}/charges", body, token=token)
        status = "charged" if resp.get("status") in ("COMPLETED", "captured", "charged") \
            else "requested"
        return {"status": status, "payee": payee, "amount": amount,
                "currency": currency, "invoice_ref": invoice_ref, "response": resp}
    except Exception as e:
        return {"status": "failed", "detail": str(e), "invoice_ref": invoice_ref}


if __name__ == "__main__":
    print("Payoneer configured:", configured(), "| live:", LIVE, "| base:", BASE)
