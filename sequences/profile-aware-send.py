"""profile-aware-send.py — send a sequence under a specific profile via Resend.

Reads the profile (identity, voice, Resend creds), reads the sequence (steps),
and sends each step through Resend with proper threading + From: alignment.

Usage:
    py profile-aware-send.py <profile_slug> <sequence_json> [--resume-from N] [--dry-run] [--delay-sec 2]

The profile's identity OVERRIDES whatever From/signature was hardcoded in the
sequence JSON — that way one sequence can be reused across multiple senders.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import sys
import time
from pathlib import Path

import httpx

from profile_lib import load_profile, save_profile, today_iso

RESEND_API = "https://api.resend.com"


def render_email(profile: dict, step: dict, msg_id: str, threading: dict, override_to: str | None = None) -> dict:
    ident = profile["identity"]
    plain = step["body"] + "\n\n--\n" + ident["signature"]
    html = (
        "<!doctype html><html><body style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.55;color:#1f2937'>"
        + step["body"].replace("\n", "<br>")
        + "<br><br>--<br>"
        + ident["signature"].replace("\n", "<br>")
        + "</body></html>"
    )
    headers = {"Message-ID": msg_id}
    if threading.get("in_reply_to"):
        headers["In-Reply-To"] = threading["in_reply_to"]
        headers["References"]  = " ".join(threading.get("references", []))
    return {
        "from":     f'{ident["from_name"]} <{ident["from_addr"]}>',
        "to":       [override_to or step.get("to") or step["__seq_to"]],
        "reply_to": ident["reply_to"],
        "subject":  step["subject"],
        "text":     plain,
        "html":     html,
        "headers":  headers,
        "tags":     [
            {"name": "profile",  "value": profile["slug"]},
            {"name": "sequence", "value": step["__seq_slug"]},
            {"name": "step",     "value": str(step["n"])},
        ],
    }


def send_resend(api_key: str, payload: dict) -> dict:
    with httpx.Client(timeout=30) as c:
        r = c.post(
            f"{RESEND_API}/emails",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
    if r.status_code in (200, 202):
        return {"sent": True, "remote_id": r.json().get("id"), "smtp_response": f"{r.status_code} OK", "backend": "resend"}
    return {"sent": False, "error": f"resend {r.status_code}: {r.text[:400]}", "backend": "resend"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile_slug")
    ap.add_argument("sequence_json")
    ap.add_argument("--resume-from", type=int, default=1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--delay-sec", type=float, default=2.0)
    args = ap.parse_args()

    profile = load_profile(args.profile_slug)
    api_key = profile.get("relay", {}).get("resend_api_key", "").strip()
    if not api_key and not args.dry_run:
        sys.exit("profile has no relay.resend_api_key — Settings → Sender → paste it first")

    seq_path = Path(args.sequence_json).resolve()
    seq = json.loads(seq_path.read_text(encoding="utf-8"))

    ident = profile["identity"]
    rcpt = seq["recipient"]["email"]
    sender_domain = ident["from_addr"].split("@", 1)[1]

    print(f"\n=== {profile['name']} → {seq['name']}")
    print(f"    From:   {ident['from_addr']}")
    print(f"    To:     {rcpt}")
    print(f"    Backend: resend {'(DRY RUN)' if args.dry_run else ''}\n")

    # Read prior results for threading continuity
    prior_path = seq_path.parent / "results.json"
    prior = {}
    if prior_path.exists():
        prior_data = json.loads(prior_path.read_text(encoding="utf-8")).get("results", [])
        prior = {r["step"]: r for r in prior_data}

    first_msg_id = next((r["message_id"] for r in prior.values() if r["step"] == 1), None)
    references   = [r["message_id"] for s, r in sorted(prior.items()) if r.get("message_id")]
    results: list[dict] = []

    for step in seq["steps"]:
        if step["n"] < args.resume_from:
            if step["n"] in prior:
                results.append(prior[step["n"]])
            continue
        step["__seq_to"]   = rcpt
        step["__seq_slug"] = seq["slug"]
        msg_id = f"<seq.{profile['slug']}.{seq['slug']}.{step['n']}.{int(time.time())}@{sender_domain}>"
        threading = {}
        if first_msg_id and step["n"] > 1:
            threading["in_reply_to"] = first_msg_id
            threading["references"]  = references[:]

        payload = render_email(profile, step, msg_id, threading)

        if args.dry_run:
            outcome = {"sent": False, "skipped": True, "dry_run": True, "backend": "resend"}
        else:
            outcome = send_resend(api_key, payload)

        outcome.update({
            "step":         step["n"],
            "subject":      step["subject"],
            "message_id":   msg_id,
            "attempted_at": dt.datetime.now().isoformat(),
            "profile":      profile["slug"],
        })
        results.append(outcome)
        print(f"  [{step['n']:02d}] {'DRY' if args.dry_run else 'SENT' if outcome['sent'] else 'FAIL'} — {step['subject']!r}"
              + ("" if outcome.get("sent") or args.dry_run else f" :: {outcome.get('error')}"))

        if step["n"] == 1 and not first_msg_id:
            first_msg_id = msg_id
        references.append(msg_id)
        if not args.dry_run:
            time.sleep(args.delay_sec)

    # Merge with prior so untouched steps preserve history
    merged = dict(prior)
    for r in results:
        merged[r["step"]] = r
    final = [merged[k] for k in sorted(merged)]

    out_payload = {
        "sequence":   seq["slug"],
        "profile":    profile["slug"],
        "ran_at":     dt.datetime.now().isoformat(),
        "backend":    "resend",
        "results":    final,
    }
    prior_path.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")

    # Also publish to the desktop app's static dir so the UI picks it up live
    pub = seq_path.parent.parent.parent / "desktop" / "frontend" / "public" / "sequences" / seq_path.parent.name
    if pub.exists():
        (pub / "results.json").write_text(json.dumps(out_payload, indent=2), encoding="utf-8")

    sent = sum(1 for r in final if r.get("sent"))
    print(f"\nSummary: {sent}/{len(final)} delivered via Resend.")
    return 0 if sent == len(final) else 2


if __name__ == "__main__":
    sys.exit(main())
