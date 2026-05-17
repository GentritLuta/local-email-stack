"""resend-pool-send.py — multi-persona send via Resend HTTP API.

Sends from any address on mail.aureonglobal.de (verified at Resend). The pool
of personas (daniel/anna/marco) each have their OWN sender address — true
per-persona reputation isolation — because Resend doesn't require a mailbox
to exist behind the From: as long as the domain is verified.

Uses the SEND-ONLY API key, which can POST /emails for any verified domain.

Usage:
    py resend-pool-send.py aureon --variants <p> --variant-n <N> --to <addr> [--force-persona daniel]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
import uuid
from pathlib import Path

import httpx

from profile_lib import load_profile

POOL_STATE = Path(__file__).resolve().parent.parent / "warmup-state"
POOL_STATE.mkdir(exist_ok=True)

RESEND_API = "https://api.resend.com/emails"


def _log(slug: str) -> Path:
    return POOL_STATE / f"{slug}.resend.jsonl"


def pick_persona(profile: dict) -> dict:
    personas = profile.get("personas", [])
    if not personas:
        sys.exit("profile has no personas")
    rot = profile.get("rotation", {})
    quota = int(rot.get("max_sends_per_persona_per_day", 30))
    min_gap = int(rot.get("min_seconds_between_sends_same_persona", 60))

    now = time.time()
    today_start = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    log = _log(profile["slug"])
    usage = {p["slug"]: {"count_today": 0, "last_ts": 0.0} for p in personas}
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            try:
                row = json.loads(line)
            except Exception:
                continue
            slug = row.get("persona")
            ts = float(row.get("ts", 0))
            if slug in usage:
                if ts >= today_start:
                    usage[slug]["count_today"] += 1
                usage[slug]["last_ts"] = max(usage[slug]["last_ts"], ts)

    candidates = []
    for p in personas:
        u = usage[p["slug"]]
        if u["count_today"] >= quota:
            continue
        if (now - u["last_ts"]) < min_gap:
            continue
        candidates.append((u["count_today"], u["last_ts"], p))
    if not candidates:
        sys.exit("all personas over quota or in cooldown")
    candidates.sort(key=lambda x: (x[0], x[1]))
    return candidates[0][2]


def send_resend(api_key: str, persona: dict, to_addr: str, subject: str, body: str) -> dict:
    sender_domain = persona["from_addr"].split("@", 1)[1]
    msg_id = f"<{uuid.uuid4().hex}.{int(time.time())}@{sender_domain}>"
    body_with_sig = body + "\n\n" + persona.get("signature", "")
    html = (
        "<!doctype html><html><body style='font-family:-apple-system,Segoe UI,sans-serif;font-size:14px;line-height:1.55;color:#1f2937;max-width:600px'>"
        + "".join(f"<p>{p}</p>" for p in body_with_sig.strip().split("\n\n"))
        + "</body></html>"
    )
    payload = {
        "from":     f'{persona["from_name"]} <{persona["from_addr"]}>',
        "to":       [to_addr],
        "reply_to": persona.get("reply_to", persona["from_addr"]),
        "subject":  subject,
        "text":     body_with_sig,
        "html":     html,
        "headers": {
            "Message-ID":            msg_id,
            "List-Unsubscribe":      f"<mailto:{persona['from_addr']}?subject=unsubscribe>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
        "tags": [
            {"name": "profile", "value": "aureon"},
            {"name": "persona", "value": persona["slug"]},
        ],
    }
    started = dt.datetime.now().isoformat()
    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(RESEND_API, headers={"Authorization": f"Bearer {api_key}",
                                            "Content-Type": "application/json"},
                       json=payload)
        if r.status_code in (200, 202):
            j = r.json()
            return {"sent": True, "resend_id": j.get("id"), "message_id": msg_id,
                    "smtp_response": f"{r.status_code} OK", "started_at": started}
        return {"sent": False, "error": f"{r.status_code}: {r.text[:300]}", "started_at": started}
    except Exception as e:
        return {"sent": False, "error": str(e), "started_at": started}


def record(slug: str, persona_slug: str, to: str, outcome: dict) -> None:
    row = {"ts": time.time(), "persona": persona_slug, "to": to,
           "delivered": outcome.get("sent"), "error": outcome.get("error"),
           "resend_id": outcome.get("resend_id")}
    with _log(slug).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("slug")
    ap.add_argument("--variants", required=True)
    ap.add_argument("--variant-n", type=int, required=True)
    ap.add_argument("--to", required=True)
    ap.add_argument("--force-persona", default=None)
    args = ap.parse_args()

    profile = load_profile(args.slug)
    persona = (next((p for p in profile["personas"] if p["slug"] == args.force_persona), None)
               if args.force_persona else pick_persona(profile))
    if not persona:
        sys.exit(f"persona '{args.force_persona}' not found")
    api_key = profile.get("relay", {}).get("resend_api_key", "").strip()
    if not api_key:
        sys.exit("profile has no relay.resend_api_key — set in profiles/aureon.private.json")

    variants = json.loads(Path(args.variants).read_text(encoding="utf-8"))
    variant = next((v for v in variants["variants"] if v["n"] == args.variant_n), None)
    if not variant:
        sys.exit(f"variant {args.variant_n} not found")

    print(f"\n=== resend pool send ===")
    print(f"  persona: {persona['slug']} ({persona['from_name']})")
    print(f"  from:    {persona['from_name']} <{persona['from_addr']}>")
    print(f"  to:      {args.to}")
    print(f"  subject: {variant['subject']}\n")

    outcome = send_resend(api_key, persona, args.to, variant["subject"], variant["body"])
    record(args.slug, persona["slug"], args.to, outcome)
    print(json.dumps(outcome, indent=2))
    return 0 if outcome.get("sent") else 2


if __name__ == "__main__":
    sys.exit(main())
