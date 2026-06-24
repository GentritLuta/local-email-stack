# -*- coding: utf-8 -*-
"""payoneer-charge.py — actively charge clients for their open invoices via
Payoneer, using the signed billing authorization on file.

Flow: for every invoice that is unpaid (status sent|overdue) AND whose client
has an authorized billing_profile, initiate a Payoneer charge for the
outstanding amount. Records the result on the invoice (payoneer_ref /
payoneer_status) and on the billing profile (payoneer_status), and — on a
captured charge — flips the invoice to 'paid'.

Until you add sequences/payoneer.env with API credentials, payoneer_lib returns
'not_configured' and this is a safe no-op. With PAYONEER_LIVE=false it does a
dry-run (logs intent, charges nothing). Set PAYONEER_LIVE=true to charge.

    py scripts/payoneer-charge.py            # charge all eligible open invoices
    py scripts/payoneer-charge.py --ref AG-ATAL-2026-003   # one invoice
"""
from __future__ import annotations
import argparse, json, sys, datetime as dt, urllib.request
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
from payoneer_lib import charge_client, configured, LIVE  # noqa: E402


def _load_env(path: Path) -> dict:
    out = {}
    if path.exists():
        for ln in path.read_text(encoding="utf-8").splitlines():
            if "=" in ln and not ln.strip().startswith("#"):
                k, v = ln.split("=", 1); out[k.strip()] = v.strip()
    return out


SENV = _load_env(REPO / "sequences" / "supabase.env")
URL = SENV["SUPABASE_URL"].rstrip("/")
KEY = SENV["SUPABASE_SERVICE_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
     "User-Agent": "les-payoneer-charge/1.0"}


def _get(path: str):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H, method="GET")
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def _patch(path: str, body: dict):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", data=json.dumps(body).encode(),
                                 headers={**H, "Prefer": "return=minimal"}, method="PATCH")
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", help="charge a single invoice by ref")
    args = ap.parse_args()

    if not configured():
        print("payoneer-charge: Payoneer not configured yet "
              "(add sequences/payoneer.env). No-op.")
        return 0

    flt = "status=in.(sent,overdue)"
    if args.ref:
        flt = f"invoice_ref=eq.{args.ref}"
    invoices = _get(f"invoices?{flt}&select=id,client_id,invoice_ref,title,amount_cents,"
                    f"due_cents,currency,status")
    if not invoices:
        print("payoneer-charge: no open invoices")
        return 0

    charged = 0
    for inv in invoices:
        if not inv.get("client_id"):
            continue
        bp = _get(f"billing_profiles?client_id=eq.{inv['client_id']}&authorized=eq.true&select=*")
        if not bp:
            print(f"  - {inv['invoice_ref']}: no authorized billing profile, skip")
            continue
        bp = bp[0]
        amount = inv.get("due_cents") or inv.get("amount_cents") or 0
        if amount <= 0:
            print(f"  - {inv['invoice_ref']}: zero amount, skip")
            continue
        res = charge_client(bp, amount_cents=amount, currency=inv.get("currency", "EUR"),
                            invoice_ref=inv["invoice_ref"],
                            description=inv.get("title") or "AUREON Global — services")
        st = res.get("status")
        print(f"  • {inv['invoice_ref']} ({amount/100:.2f} {inv.get('currency')}): {st}"
              f"{' — ' + res.get('detail') if res.get('detail') else ''}")
        # Record on invoice + billing profile.
        ref = (res.get("response") or {}).get("payment_id") \
            or (res.get("response") or {}).get("id") or inv["invoice_ref"]
        inv_patch = {"payoneer_status": st, "payoneer_ref": ref}
        if st == "charged":
            inv_patch["status"] = "paid"
            inv_patch["paid_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
            charged += 1
        _patch(f"invoices?id=eq.{inv['id']}", inv_patch)
        _patch(f"billing_profiles?id=eq.{bp['id']}", {"payoneer_status": st})

    mode = "LIVE" if LIVE else "dry-run"
    print(f"payoneer-charge: done ({mode}); {charged} captured")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
