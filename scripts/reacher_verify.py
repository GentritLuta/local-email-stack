# -*- coding: utf-8 -*-
"""reacher_verify.py — client for a self-hosted Reacher backend (the open-source
check-if-email-exists HTTP API), used to verify Diraya's guessed emails on the
NON-Google slice of the audience, where SMTP actually answers honestly.

Reacher runs on a VPS where port 25 is open (see notes/reacher-vps-deploy.md):
    docker run -d -p 8080:8080 -e RUST_LOG=info reacherhq/backend
It exposes POST /v0/check_email {"to_email": "x@y.com"} and returns
{is_reachable: safe|risky|invalid|unknown, smtp:{is_catch_all, ...}, ...}.

This client batches a CSV through that endpoint, keeps only "safe" results (and
optionally "risky" catch-all), and writes a verified CSV ready to import to Diraya.

  py scripts/reacher_verify.py --backend http://VPS_IP:8080 --in guesses.csv --out verified.csv
  py scripts/reacher_verify.py --selftest        # offline mock, no backend needed
"""
from __future__ import annotations
import argparse, csv, json, sys, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def check_one(backend: str, email: str, token: str | None, timeout: int) -> dict:
    body = json.dumps({"to_email": email}).encode()
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = token
    req = urllib.request.Request(backend.rstrip("/") + "/v0/check_email", data=body,
                                 method="POST", headers=headers)
    try:
        r = json.loads(urllib.request.urlopen(req, timeout=timeout).read())
    except urllib.error.HTTPError as e:
        return {"email": email, "is_reachable": "error", "detail": f"http{e.code}"}
    except Exception as e:
        return {"email": email, "is_reachable": "error", "detail": type(e).__name__}
    smtp = r.get("smtp") or {}
    return {"email": email, "is_reachable": r.get("is_reachable", "unknown"),
            "is_catch_all": smtp.get("is_catch_all"), "can_connect": smtp.get("can_connect_smtp"),
            "has_full_inbox": smtp.get("has_full_inbox"), "is_disabled": smtp.get("is_disabled")}


def verify_batch(backend, emails, token, timeout, workers, keep_catch_all):
    out = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(check_one, backend, e, token, timeout): e for e in emails}
        for f in as_completed(futs):
            out.append(f.result())
    return out


def is_sendable(r: dict, keep_catch_all: bool) -> bool:
    if r["is_reachable"] == "safe":
        return True
    if keep_catch_all and r["is_reachable"] == "risky" and r.get("is_catch_all"):
        return True              # catch-all accepts everything -> will not hard-bounce
    return False


def selftest() -> int:
    """Offline check of the keep/drop logic against representative Reacher verdicts."""
    cases = [
        ({"email": "a@x", "is_reachable": "safe", "is_catch_all": False}, True),
        ({"email": "b@x", "is_reachable": "invalid", "is_catch_all": False}, False),
        ({"email": "c@x", "is_reachable": "unknown", "is_catch_all": None}, False),
        ({"email": "d@x", "is_reachable": "risky", "is_catch_all": True}, True),    # catch-all kept
        ({"email": "e@x", "is_reachable": "risky", "is_catch_all": False}, False),  # risky non-catchall dropped
    ]
    ok = all(is_sendable(c, keep_catch_all=True) == exp for c, exp in cases)
    for c, exp in cases:
        got = is_sendable(c, True)
        print(f"  {c['is_reachable']:<8} catch_all={c['is_catch_all']!s:<5} -> sendable={got} (expect {exp}) {'ok' if got==exp else 'FAIL'}")
    print("SELF-TEST:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", help="Reacher backend URL, e.g. http://VPS_IP:8080")
    ap.add_argument("--token", help="Authorization header value, if your backend sets one")
    ap.add_argument("--email")
    ap.add_argument("--in", dest="inp", help="CSV with an 'email' column")
    ap.add_argument("--out")
    ap.add_argument("--timeout", type=int, default=30)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--keep-catch-all", action="store_true", help="also keep risky catch-all (won't hard-bounce)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    if not a.backend:
        print("need --backend http://VPS_IP:8080 (your self-hosted Reacher)"); return 2
    emails = [a.email] if a.email else [r["email"] for r in csv.DictReader(open(a.inp, encoding="utf-8-sig")) if r.get("email")]
    res = verify_batch(a.backend, emails, a.token, a.timeout, a.workers, a.keep_catch_all)
    from collections import Counter
    summ = Counter(r["is_reachable"] for r in res)
    sendable = [r for r in res if is_sendable(r, a.keep_catch_all)]
    for r in res[:40]:
        print(f"  {r['is_reachable']:<9} catch_all={r.get('is_catch_all')!s:<5} {r['email']}")
    print("\nsummary:", dict(summ))
    print(f"sendable: {len(sendable)} / {len(res)}")
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["email", "is_reachable", "is_catch_all", "can_connect", "has_full_inbox", "is_disabled"])
            w.writeheader(); w.writerows(res)
        print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
