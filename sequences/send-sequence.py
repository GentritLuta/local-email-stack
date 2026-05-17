"""send-sequence.py — generate .eml files and (optionally) direct-to-MX SMTP send.

Reads a sequence.json, materializes one .eml per step, then attempts to send each
one to the recipient's MX. Writes a results.json with per-step status.

Usage:
  python send-sequence.py path/to/sequence.json [--dry-run] [--delay-sec 2]

Defaults:
  - delay 2s between sends (avoids the recipient MX rate-limiting us)
  - threads each message off the first message so they appear as a sequence,
    not 10 unrelated emails (sets References + In-Reply-To)
  - All .eml saved to ./eml/<n>.eml regardless of send success.

Note: home/residential ISPs almost always block port 25 outbound. This script
will report which sends actually completed an SMTP transaction vs which were
blocked at the network level.
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
    import dns.resolver
    HAVE_DNS = True
except ImportError:
    HAVE_DNS = False


def resolve_mx(domain: str) -> list[str]:
    """Return MX hosts ordered by preference."""
    if HAVE_DNS:
        try:
            answers = dns.resolver.resolve(domain, "MX")
            return [str(r.exchange).rstrip(".") for r in sorted(answers, key=lambda x: x.preference)]
        except Exception as e:
            print(f"  ! dnspython MX lookup failed: {e}")
    # Fallback: socket has no MX lookup; use nslookup via subprocess
    import subprocess
    try:
        out = subprocess.run(["nslookup", "-type=mx", domain], capture_output=True, text=True, timeout=10)
        hosts = []
        for line in out.stdout.splitlines():
            line = line.strip()
            if "mail exchanger" in line.lower():
                parts = line.split("=")
                if len(parts) >= 2:
                    hosts.append(parts[-1].strip().rstrip("."))
        return hosts
    except Exception as e:
        print(f"  ! nslookup MX lookup failed: {e}")
        return []


def build_eml(seq: dict, step: dict, msg_id: str, threading: dict) -> bytes:
    sender = seq["sender"]
    recipient = seq["recipient"]
    msg = MIMEMultipart("alternative")
    msg["From"] = f'"{sender["from_name"]}" <{sender["from_addr"]}>'
    msg["To"] = recipient["email"]
    msg["Reply-To"] = sender["reply_to"]
    msg["Subject"] = step["subject"]
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = msg_id
    msg["User-Agent"] = "LocalEmailStack/0.4 (test sender)"
    if threading.get("in_reply_to"):
        msg["In-Reply-To"] = threading["in_reply_to"]
    if threading.get("references"):
        msg["References"] = " ".join(threading["references"])

    body_plain = step["body"] + "\n\n--\n" + sender["signature"]
    body_html = (
        "<!doctype html><html><body style='font-family:-apple-system,Segoe UI,Roboto,sans-serif;font-size:14px;line-height:1.55;color:#1f2937'>"
        + step["body"].replace("\n", "<br>")
        + "<br><br>--<br>"
        + sender["signature"].replace("\n", "<br>")
        + "</body></html>"
    )
    msg.attach(MIMEText(body_plain, "plain", "utf-8"))
    msg.attach(MIMEText(body_html, "html", "utf-8"))
    return msg.as_bytes()


def attempt_send(eml_bytes: bytes, sender_addr: str, rcpt_addr: str, mx_hosts: list[str], helo_name: str) -> dict:
    """Try each MX in order; first success wins."""
    if not mx_hosts:
        return {"sent": False, "error": "no MX hosts resolved"}
    last_err = None
    for host in mx_hosts:
        try:
            with smtplib.SMTP(host, 25, timeout=15) as s:
                s.ehlo(helo_name)
                try:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo(helo_name)
                except smtplib.SMTPException:
                    pass  # MX doesn't support STARTTLS; continue plaintext
                s.mail(sender_addr)
                code, resp = s.rcpt(rcpt_addr)
                if code >= 400:
                    last_err = f"RCPT TO {code}: {resp.decode('utf-8', 'ignore')}"
                    continue
                s.data(eml_bytes)
                return {"sent": True, "mx": host, "smtp_response": f"{code} {resp.decode('utf-8','ignore').strip()}"}
        except smtplib.SMTPException as e:
            last_err = f"smtp error on {host}: {e}"
        except (socket.timeout, ConnectionRefusedError, OSError) as e:
            last_err = f"network error on {host}: {e}"
        except Exception as e:
            last_err = f"unexpected {host}: {e}"
    return {"sent": False, "error": last_err or "all MX hosts failed"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sequence_json")
    ap.add_argument("--dry-run", action="store_true", help="generate .eml files only; don't send")
    ap.add_argument("--delay-sec", type=float, default=2.0)
    ap.add_argument("--helo", default=socket.gethostname())
    args = ap.parse_args()

    seq_path = Path(args.sequence_json).resolve()
    seq = json.loads(seq_path.read_text(encoding="utf-8"))
    out_dir = seq_path.parent / "eml"
    out_dir.mkdir(exist_ok=True)

    rcpt = seq["recipient"]["email"]
    rcpt_domain = rcpt.split("@", 1)[1]
    sender_addr = seq["sender"]["from_addr"]
    sender_domain = sender_addr.split("@", 1)[1]

    print(f"\n=== Sequence: {seq['name']}")
    print(f"    From:      {sender_addr}")
    print(f"    To:        {rcpt}")
    print(f"    Steps:     {len(seq['steps'])}")
    print(f"    Mode:      {'DRY-RUN (.eml only)' if args.dry_run else 'LIVE SEND via direct-to-MX'}\n")

    mx_hosts: list[str] = []
    if not args.dry_run:
        print(f"--- resolving MX for {rcpt_domain}")
        mx_hosts = resolve_mx(rcpt_domain)
        print(f"    {mx_hosts or '(none — send will fail)'}\n")

    results: list[dict] = []
    first_msg_id: str | None = None
    references: list[str] = []

    for step in seq["steps"]:
        ts = dt.datetime.now()
        msg_id = f"<seq.{seq['slug']}.{step['n']}.{int(ts.timestamp())}@{sender_domain}>"
        threading = {}
        if first_msg_id and step["n"] > 1:
            threading["in_reply_to"] = first_msg_id
            threading["references"] = references[:]

        eml = build_eml(seq, step, msg_id, threading)
        eml_path = out_dir / f"{step['n']:02d}-{step['kind']}.eml"
        eml_path.write_bytes(eml)
        print(f"  [{step['n']:02d}] wrote {eml_path.name}  ({len(eml)} bytes)  subject={step['subject']!r}")

        send_outcome = {"sent": False, "skipped": True} if args.dry_run else attempt_send(eml, sender_addr, rcpt, mx_hosts, args.helo)
        send_outcome["message_id"] = msg_id
        send_outcome["subject"] = step["subject"]
        send_outcome["step"] = step["n"]
        results.append(send_outcome)

        if not args.dry_run:
            if send_outcome.get("sent"):
                print(f"        SENT via {send_outcome['mx']}")
            else:
                print(f"        FAILED: {send_outcome.get('error')}")
            time.sleep(args.delay_sec)

        if step["n"] == 1:
            first_msg_id = msg_id
        references.append(msg_id)

    results_path = seq_path.parent / "results.json"
    results_path.write_text(json.dumps({
        "sequence": seq["slug"],
        "ran_at": dt.datetime.now().isoformat(),
        "dry_run": args.dry_run,
        "mx_hosts": mx_hosts,
        "results": results,
    }, indent=2), encoding="utf-8")
    print(f"\n  → {results_path}")

    sent = sum(1 for r in results if r.get("sent"))
    print(f"\nSummary: {sent}/{len(results)} actually delivered to MX.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
