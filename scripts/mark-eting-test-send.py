#!/usr/bin/env python3
"""One-shot end-to-end test send for mark-eting through the REAL production path.

Renders E1 with the live mark-eting branded template and sends it via the same
send_via_resend() the runner uses, from a VERIFIED mark-eting persona, to a
controlled inbox. Proves DKIM-signed delivery before go-live. Sends nothing to
real prospects.

Usage: py scripts/mark-eting-test-send.py --to info@aureonglobal.de
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, "sequences")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import importlib
runner = importlib.import_module("sequence-runner")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--to", required=True)
    args = ap.parse_args()

    prof = json.loads(Path("profiles/mark-eting.json").read_text(encoding="utf-8"))
    key = json.loads(Path("profiles/mark-eting.private.json").read_text(encoding="utf-8"))["relay"]["resend_api_key"]
    variants = json.loads(Path("sequences/mark-eting-default/variants.json").read_text(encoding="utf-8"))["variants"]
    e1 = variants[0]

    # Pick the first VERIFIED persona/subdomain
    verified_domains = {d["domain"] for d in prof["relay"]["from_domains"] if d.get("verified_at")}
    persona = next((p for p in prof["personas"]
                    if p["from_addr"].split("@")[-1] in verified_domains), None)
    if not persona:
        print("  ! no verified persona/subdomain available — cannot test send")
        return 1

    body = e1["body"].replace("{greeting}", "there").replace("{company}", "your business")
    subject = e1["subject"].replace("{greeting}", "there").replace("{company}", "your business")

    prospect = {"email": args.to, "id": "test", "unsubscribe_token": "TESTTOKEN"}

    print(f"  from: {persona['from_addr']}  ({persona['from_name']})")
    print(f"  to:   {args.to}")
    print(f"  subj: {subject}")
    outcome = runner.send_via_resend(key, persona, prospect, subject, body,
                                     brand=prof["brand"], step_n=1)
    if outcome.get("ok"):
        print(f"  SENT  resend_id={outcome.get('resend_id')}")
        return 0
    print(f"  FAIL  {outcome.get('error')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
