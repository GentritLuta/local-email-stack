"""onboard-resend.py — one-command Resend onboarding for a profile.

Does every step that doesn't require leaving the terminal:

  1. Take/persist a Resend API key into profiles/<slug>.private.json
  2. Add the profile's sending domain to Resend (idempotent)
  3. Print the exact DNS records to paste in your DNS provider
  4. Poll until verified (up to 30 min)
  5. Stamp relay.domain_verified_at into the profile
  6. (optional) Send the two test emails (info@aureonglobal.de + g-luta@web.de)
     through Resend with proper DKIM and full header hygiene
  7. Run a deliverability scorecard on the final state

Usage:
    py onboard-resend.py <profile_slug> [--api-key re_...] [--test-send] [--no-wait]

If --api-key is omitted, prompts you to paste one. The script never logs the
key.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import httpx

from profile_lib import load_profile, save_profile, save_private

RESEND_API = "https://api.resend.com"
SCRIPT_DIR = Path(__file__).resolve().parent


def _client(api_key: str) -> httpx.Client:
    return httpx.Client(
        base_url=RESEND_API, timeout=30,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )


def _h(s: str) -> str:
    return f"\033[1;36m{s}\033[0m"


def _ok(s: str) -> str:
    return f"\033[1;32m✓ {s}\033[0m"


def _warn(s: str) -> str:
    return f"\033[1;33m⚠ {s}\033[0m"


def _err(s: str) -> str:
    return f"\033[1;31m✗ {s}\033[0m"


def step_save_api_key(slug: str, key: str | None) -> str:
    if key is None:
        key = input("Paste your Resend API key (visit https://resend.com/api-keys, never logged): ").strip()
    if not key.startswith("re_"):
        sys.exit(_err("That doesn't look like a Resend API key (should start with 're_')"))
    save_private(slug, {"relay": {"resend_api_key": key}})
    print(_ok(f"Saved to profiles/{slug}.private.json"))
    return key


def step_add_domain(api_key: str, domain: str) -> dict:
    with _client(api_key) as c:
        # Idempotent: GET existing first
        r = c.get("/domains")
        r.raise_for_status()
        for d in r.json().get("data", []):
            if d.get("name") == domain:
                # Re-fetch with full record set
                full = c.get(f"/domains/{d['id']}").json()
                return full
        r = c.post("/domains", json={"name": domain, "region": "us-east-1"})
        if r.status_code >= 400:
            sys.exit(_err(f"Resend rejected the domain: {r.status_code} {r.text}"))
        # Refetch to get records
        return c.get(f"/domains/{r.json()['id']}").json()


def step_print_dns(domain_obj: dict, domain: str) -> None:
    print(_h(f"\nDNS records to add for {domain}:"))
    print("(Paste these into your DNS provider — for insaneaiautomation.xyz that's likely")
    print(" GoDaddy DNS or wherever the domain is hosted. TTL: leave at default/Auto.)\n")
    records = domain_obj.get("records") or []
    if not records:
        print(_warn("Resend did not return records — domain may already be verified."))
        return
    # Render a table
    rows = [("Type", "Name", "Value", "Priority")]
    for r in records:
        rt = r.get("record") or r.get("type") or "?"
        n  = r.get("name") or "?"
        v  = r.get("value") or "?"
        # Truncate long DKIM values for screen, then print full below
        prio = str(r.get("priority", ""))
        rows.append((rt, n, v if len(v) < 70 else v[:65] + "…", prio))
    widths = [max(len(str(r[i])) for r in rows) for i in range(4)]
    sep = "   "
    for i, row in enumerate(rows):
        line = sep.join(str(c).ljust(widths[i]) for i, c in enumerate(row))
        print(line)
        if i == 0:
            print(sep.join("─" * w for w in widths))
    # Then print full DKIM values that were truncated
    longs = [r for r in records if len(r.get("value", "")) >= 70]
    if longs:
        print("\nFull values (in case the table truncated):")
        for r in longs:
            print(f"\n  {r.get('record') or r.get('type')} {r.get('name')}:")
            print(f"  {r.get('value')}")


def step_wait_verify(api_key: str, domain: str, timeout_min: int = 30) -> bool:
    print(_h("\nPolling Resend until the domain flips to 'verified'…"))
    print("(usually 1–5 min after the DNS records propagate. Ctrl-C to abort.)\n")
    deadline = time.time() + timeout_min * 60
    with _client(api_key) as c:
        last_status = None
        while True:
            r = c.get("/domains")
            r.raise_for_status()
            data = next((d for d in r.json().get("data", []) if d.get("name") == domain), None)
            status = (data or {}).get("status", "unknown")
            if status != last_status:
                ts = dt.datetime.now().strftime("%H:%M:%S")
                print(f"  [{ts}] status = {status}")
                last_status = status
            if status == "verified":
                return True
            if time.time() > deadline:
                print(_warn(f"timed out after {timeout_min} min. Re-run later with `verify --wait`."))
                return False
            time.sleep(15)


def step_persist_verified(slug: str) -> None:
    profile = load_profile(slug)
    profile.setdefault("relay", {})["domain_verified_at"] = dt.datetime.now().isoformat()
    save_profile(profile)
    print(_ok(f"Stamped relay.domain_verified_at into profiles/{slug}.json"))


def step_send_tests(api_key: str, profile: dict, recipients: list[str]) -> None:
    print(_h("\nSending test emails through Resend (full DKIM, proper headers)…\n"))
    ident = profile["identity"]
    body = (
        "hi,\n\n"
        "quick test — verifying our outbound mail reaches your inbox cleanly. "
        "no action needed.\n\n"
        "if you happen to see this in spam, dragging it to inbox once helps with reputation. "
        "thanks.\n\n"
        f"{ident['signature']}\n"
    )
    html_body = body.replace("\n\n", "<br><br>").replace("\n", "<br>")
    results = []
    with _client(api_key) as c:
        for to in recipients:
            try:
                r = c.post("/emails", json={
                    "from":     f'{ident["from_name"]} <{ident["from_addr"]}>',
                    "to":       [to],
                    "subject":  "quick test",
                    "text":     body,
                    "html":     f"<!doctype html><html><body style='font-family:-apple-system,Segoe UI,sans-serif;font-size:14px;line-height:1.55;color:#1f2937'>{html_body}</body></html>",
                    "reply_to": ident["reply_to"],
                    "headers": {
                        "List-Unsubscribe":      f"<mailto:{ident['from_addr']}?subject=unsubscribe>",
                        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                    },
                    "tags": [{"name": "kind", "value": "test"}, {"name": "profile", "value": profile["slug"]}],
                })
                if r.status_code in (200, 202):
                    j = r.json()
                    print(_ok(f"{to}  →  Resend id {j.get('id')}"))
                    results.append({"to": to, "sent": True, "id": j.get("id")})
                else:
                    print(_err(f"{to}  →  {r.status_code} {r.text[:200]}"))
                    results.append({"to": to, "sent": False, "error": f"{r.status_code} {r.text[:200]}"})
            except Exception as e:
                print(_err(f"{to}  →  exception: {e}"))
                results.append({"to": to, "sent": False, "error": str(e)})
            time.sleep(2)
    return results


def step_scorecard(slug: str) -> None:
    """Defer to deliverability-score.py for the readable scorecard."""
    import subprocess
    out = subprocess.run(
        [sys.executable, str(SCRIPT_DIR / "deliverability-score.py"), slug],
        capture_output=False,
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--api-key", default=None)
    ap.add_argument("--test-send", nargs="*", default=None,
                    help="recipient addresses to test (default: info@aureonglobal.de g-luta@web.de)")
    ap.add_argument("--no-wait", action="store_true", help="don't poll for verification")
    args = ap.parse_args()

    profile = load_profile(args.slug)
    domain  = (profile.get("relay", {}).get("from_domains") or [None])[0]
    if not domain:
        sys.exit(_err(f"profile {args.slug} has no relay.from_domains — edit profiles/{args.slug}.json first"))

    print(_h(f"\nOnboarding {profile['name']}  →  Resend"))
    print(f"  Sending domain:  {domain}")
    print(f"  From identity:   {profile['identity']['from_name']} <{profile['identity']['from_addr']}>")

    key = step_save_api_key(args.slug, args.api_key)

    print(_h("\nAdding domain to Resend…"))
    domain_obj = step_add_domain(key, domain)
    status = domain_obj.get("status")
    print(f"  Current status: {status}")

    if status != "verified":
        step_print_dns(domain_obj, domain)
        if not args.no_wait:
            ok = step_wait_verify(key, domain)
            if not ok:
                return 2
            step_persist_verified(args.slug)
        else:
            print(_warn("Skipping verify (--no-wait). Run `resend-setup.py verify <slug> --wait` later."))
            return 0
    else:
        print(_ok("Already verified."))
        step_persist_verified(args.slug)

    if args.test_send is not None:
        recipients = args.test_send or ["info@aureonglobal.de", "g-luta@web.de"]
        # Refresh profile to pick up the key we just persisted
        profile = load_profile(args.slug)
        step_send_tests(key, profile, recipients)

    print(_h("\nDeliverability scorecard:"))
    step_scorecard(args.slug)

    print(_h("\n✓ Onboarding complete."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
