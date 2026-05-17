"""relay-send.py — send a sequence through a real deliverability relay.

Supports three backends, all real, all designed for inbox placement:

  --backend resend        — Resend HTTP API. Free tier: 100/day, 3000/month.
                            Needs RESEND_API_KEY + a verified sending domain.
                            Best inbox placement of the three.

  --backend smtp          — generic STARTTLS SMTP (Gmail, Outlook, custom).
                            Needs SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS.
                            For Gmail: use an App Password (account.google.com/apppasswords).
                            For Outlook: same. ~500/day limit.

  --backend postal        — self-hosted Postal on the Oracle Free Tier VM.
                            Needs POSTAL_SMTP_HOST + POSTAL_SMTP_USER + POSTAL_SMTP_PASS,
                            reachable via Tailscale.

Reads config from relay.env in the same directory, or pass via --env.

Usage:
    python relay-send.py path/to/sequence.json --backend resend
    python relay-send.py path/to/sequence.json --backend smtp --resume-from 2

--resume-from N: skip steps before N (so re-sending only the failed 9/10 is one command).
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import json
import os
import smtplib
import socket
import ssl
import sys
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

try:
    import httpx
    HAVE_HTTPX = True
except ImportError:
    HAVE_HTTPX = False


def load_env(env_path: Path) -> dict:
    env = dict(os.environ)
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def build_msg(seq: dict, step: dict, msg_id: str, threading: dict, content_only: bool = False):
    sender = seq["sender"]
    recipient = seq["recipient"]

    plain_body = step["body"] + "\n\n--\n" + sender["signature"]
    html_body = (
        "<!doctype html><html><body style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.55;color:#1f2937'>"
        + step["body"].replace("\n", "<br>")
        + "<br><br>--<br>"
        + sender["signature"].replace("\n", "<br>")
        + "</body></html>"
    )

    if content_only:
        return {"plain": plain_body, "html": html_body, "msg_id": msg_id, "subject": step["subject"]}

    msg = MIMEMultipart("alternative")
    msg["From"] = f'"{sender["from_name"]}" <{sender["from_addr"]}>'
    msg["To"] = recipient["email"]
    msg["Reply-To"] = sender["reply_to"]
    msg["Subject"] = step["subject"]
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = msg_id
    msg["User-Agent"] = "LocalEmailStack/0.4"
    if threading.get("in_reply_to"):
        msg["In-Reply-To"] = threading["in_reply_to"]
    if threading.get("references"):
        msg["References"] = " ".join(threading["references"])
    msg.attach(MIMEText(plain_body, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    return msg


# ─── Backends ──────────────────────────────────────────────────────────────

def send_resend(seq: dict, step: dict, msg_id: str, threading: dict, env: dict) -> dict:
    if not HAVE_HTTPX:
        return {"sent": False, "error": "httpx not installed (pip install httpx)"}
    api_key = env.get("RESEND_API_KEY", "").strip()
    if not api_key:
        return {"sent": False, "error": "RESEND_API_KEY not set in relay.env"}
    content = build_msg(seq, step, msg_id, threading, content_only=True)
    payload = {
        "from": f'{seq["sender"]["from_name"]} <{seq["sender"]["from_addr"]}>',
        "to": [seq["recipient"]["email"]],
        "subject": content["subject"],
        "text": content["plain"],
        "html": content["html"],
        "headers": {"Message-ID": msg_id},
        "reply_to": seq["sender"]["reply_to"],
    }
    if threading.get("in_reply_to"):
        payload["headers"]["In-Reply-To"] = threading["in_reply_to"]
        payload["headers"]["References"] = " ".join(threading.get("references", []))
    try:
        with httpx.Client(timeout=20) as c:
            r = c.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
            )
        if r.status_code in (200, 202):
            return {"sent": True, "backend": "resend", "remote_id": r.json().get("id"), "smtp_response": f"{r.status_code} OK"}
        return {"sent": False, "error": f"resend {r.status_code}: {r.text[:300]}"}
    except Exception as e:
        return {"sent": False, "error": f"resend request failed: {e}"}


def send_smtp(seq: dict, step: dict, msg_id: str, threading: dict, env: dict) -> dict:
    host = env.get("SMTP_HOST", "").strip()
    port = int(env.get("SMTP_PORT", "587"))
    user = env.get("SMTP_USER", "").strip()
    password = env.get("SMTP_PASS", "").strip()
    if not host or not user or not password:
        return {"sent": False, "error": "SMTP_HOST / SMTP_USER / SMTP_PASS not set in relay.env"}
    msg = build_msg(seq, step, msg_id, threading)
    try:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.ehlo()
            s.login(user, password)
            # Some providers (Gmail) require the envelope FROM = authenticated user.
            envelope_from = user if "@" in user else seq["sender"]["from_addr"]
            s.send_message(msg, from_addr=envelope_from)
        return {"sent": True, "backend": "smtp", "smtp_response": f"sent via {host}:{port}"}
    except smtplib.SMTPAuthenticationError as e:
        return {"sent": False, "error": f"SMTP auth failed: {e.smtp_error.decode(errors='ignore') if e.smtp_error else e}"}
    except Exception as e:
        return {"sent": False, "error": f"SMTP error: {e}"}


def send_postal(seq: dict, step: dict, msg_id: str, threading: dict, env: dict) -> dict:
    # Postal exposes a standard SMTP endpoint with username/password creds from
    # its admin UI ("Credentials" tab on each Mail Server).
    return send_smtp(
        seq, step, msg_id, threading,
        {**env,
         "SMTP_HOST": env.get("POSTAL_SMTP_HOST", ""),
         "SMTP_PORT": env.get("POSTAL_SMTP_PORT", "587"),
         "SMTP_USER": env.get("POSTAL_SMTP_USER", ""),
         "SMTP_PASS": env.get("POSTAL_SMTP_PASS", "")},
    )


BACKENDS = {"resend": send_resend, "smtp": send_smtp, "postal": send_postal}


# ─── Main ──────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sequence_json")
    ap.add_argument("--backend", required=True, choices=list(BACKENDS.keys()))
    ap.add_argument("--env", default=None, help="path to relay.env (default: sibling of sequence_json)")
    ap.add_argument("--delay-sec", type=float, default=2.0)
    ap.add_argument("--resume-from", type=int, default=1, help="skip steps before this n (so you can re-send only the failed ones)")
    args = ap.parse_args()

    seq_path = Path(args.sequence_json).resolve()
    seq = json.loads(seq_path.read_text(encoding="utf-8"))
    env_path = Path(args.env).resolve() if args.env else (seq_path.parent.parent / "relay.env")
    env = load_env(env_path)
    backend = BACKENDS[args.backend]

    rcpt = seq["recipient"]["email"]
    sender_addr = seq["sender"]["from_addr"]
    sender_domain = sender_addr.split("@", 1)[1]

    print(f"\n=== Sequence: {seq['name']}")
    print(f"    Backend:   {args.backend}")
    print(f"    Env file:  {env_path}")
    print(f"    From:      {sender_addr}")
    print(f"    To:        {rcpt}")
    print(f"    Resume:    step {args.resume_from} -> {len(seq['steps'])}\n")

    # Read prior results.json to preserve threading + status of earlier sends.
    prior_path = seq_path.parent / "results.json"
    prior = {}
    if prior_path.exists():
        prior_data = json.loads(prior_path.read_text(encoding="utf-8")).get("results", [])
        prior = {r["step"]: r for r in prior_data}

    results: list[dict] = []
    first_msg_id: str | None = next(
        (r["message_id"] for r in prior.values() if r["step"] == 1),
        None,
    )
    references: list[str] = [r["message_id"] for s, r in sorted(prior.items()) if r.get("message_id")]

    for step in seq["steps"]:
        if step["n"] < args.resume_from:
            if step["n"] in prior:
                results.append(prior[step["n"]])
            continue

        ts = dt.datetime.now()
        msg_id = f"<seq.{seq['slug']}.{step['n']}.{int(ts.timestamp())}@{sender_domain}>"
        threading = {}
        if first_msg_id and step["n"] > 1:
            threading["in_reply_to"] = first_msg_id
            threading["references"] = references[:]

        outcome = backend(seq, step, msg_id, threading, env)
        outcome["message_id"] = msg_id
        outcome["step"] = step["n"]
        outcome["subject"] = step["subject"]
        outcome["attempted_at"] = ts.isoformat()
        results.append(outcome)

        if outcome.get("sent"):
            print(f"  [{step['n']:02d}] SENT via {args.backend}")
        else:
            print(f"  [{step['n']:02d}] FAILED: {outcome.get('error')}")

        if step["n"] == 1 and not first_msg_id:
            first_msg_id = msg_id
        references.append(msg_id)
        time.sleep(args.delay_sec)

    # Merge with prior so unchanged steps keep their record.
    merged = {r["step"]: r for r in prior.values()}
    for r in results:
        merged[r["step"]] = r
    final = [merged[k] for k in sorted(merged)]

    out_payload = {
        "sequence": seq["slug"],
        "ran_at": dt.datetime.now().isoformat(),
        "backend": args.backend,
        "results": final,
    }
    prior_path.write_text(json.dumps(out_payload, indent=2), encoding="utf-8")
    sent = sum(1 for r in final if r.get("sent"))
    print(f"\nSummary: {sent}/{len(final)} delivered.")
    print(f"  → {prior_path}")
    return 0 if sent == len(final) else 2


if __name__ == "__main__":
    sys.exit(main())
