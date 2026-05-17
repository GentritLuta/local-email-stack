"""imap-poll.py — pull replies from info@aureonglobal.de via Hostinger IMAP.

Every cold send sets Reply-To: info@aureonglobal.de, so real human replies land in
that one mailbox. This poller:
  1. Connects to imap.hostinger.com:993 with the same Hostinger creds we use for SMTP
  2. Walks UNSEEN messages
  3. Classifies each (reply / bounce / complaint / unrelated)
  4. Tries to match In-Reply-To / References / In body Message-ID against Supabase
     send_log → resolves the originating run_id
  5. INSERTs a row into Supabase `replies`
  6. If class=reply and we found the run: PATCH runs.status='paused_replied'
  7. Marks the message as Seen so we don't re-process

Designed to run every 5 min as a scheduled task.

Usage:
    py imap-poll.py once                # one pass, exit
    py imap-poll.py loop --interval 300 # forever, every 5 min
"""

from __future__ import annotations

import argparse
import datetime as dt
import email
import email.policy
import imaplib
import json
import os
import re
import sys
import time
from email.utils import parseaddr
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent

# ─── Config loader ─────────────────────────────────────────────────────────

def load_env(path: Path) -> dict:
    env = dict(os.environ)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def hostinger_creds() -> tuple[str, str]:
    env = load_env(REPO_ROOT / "sequences" / "hostinger.env")
    user = env.get("SMTP_USER", "info@aureonglobal.de")
    password = env.get("SMTP_PASS", "")
    if not password:
        sys.exit("missing SMTP_PASS in sequences/hostinger.env")
    return user, password


def supabase_creds() -> tuple[str, str]:
    env = load_env(REPO_ROOT / "sequences" / "supabase.env")
    url = env.get("SUPABASE_URL", "").rstrip("/")
    key = env.get("SUPABASE_ANON_KEY", "")
    if not url or not key:
        sys.exit("missing SUPABASE_URL / SUPABASE_ANON_KEY in sequences/supabase.env")
    return url, key


# ─── Classification ─────────────────────────────────────────────────────────

BOUNCE_FROM = re.compile(r"^(mailer-daemon|postmaster|bounce|noreply|no-reply)@", re.I)
COMPLAINT_FROM = re.compile(r"^(abuse|feedback-loop)@", re.I)
BOUNCE_SUBJ = re.compile(r"(undelivered|delivery (status|failure)|returned mail|mail delivery|address (not found|rejected))", re.I)


def classify(msg) -> str:
    sender = parseaddr(msg.get("From", ""))[1].lower()
    subject = msg.get("Subject", "") or ""
    if msg.get("Feedback-Type") or COMPLAINT_FROM.search(sender):
        return "complaint"
    if BOUNCE_FROM.search(sender) or BOUNCE_SUBJ.search(subject):
        return "bounce"
    if msg.get("X-Failed-Recipients"):
        return "bounce"
    if msg.get("In-Reply-To") or msg.get("References"):
        return "reply"
    return "unrelated"


def extract_snippet(msg, max_chars: int = 1500) -> str:
    try:
        if msg.is_multipart():
            for part in msg.walk():
                ctype = part.get_content_type()
                if ctype == "text/plain":
                    body = part.get_payload(decode=True)
                    if body:
                        return body.decode(part.get_content_charset() or "utf-8", "ignore")[:max_chars]
            for part in msg.walk():
                if part.get_content_type() == "text/html":
                    body = part.get_payload(decode=True)
                    if body:
                        # crude strip-tags
                        text = re.sub(r"<[^>]+>", " ", body.decode(part.get_content_charset() or "utf-8", "ignore"))
                        return re.sub(r"\s+", " ", text)[:max_chars]
        else:
            body = msg.get_payload(decode=True) or b""
            return body.decode(msg.get_content_charset() or "utf-8", "ignore")[:max_chars]
    except Exception as e:
        return f"(parse error: {e})"
    return ""


# ─── Supabase access ────────────────────────────────────────────────────────

class Supa:
    def __init__(self, url: str, key: str):
        self.base = f"{url}/rest/v1"
        self.headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }
        self.client = httpx.Client(headers=self.headers, timeout=20)

    def find_run_by_message_id(self, refs: list[str]) -> tuple[str | None, str | None]:
        """Given list of candidate Message-IDs from In-Reply-To/References, find the matching run."""
        if not refs:
            return None, None
        # Postgrest doesn't have an "in" operator that's easy for strings with special chars,
        # but we can use OR(...) with eq filters or fetch+filter.
        for mid in refs:
            r = self.client.get(f"{self.base}/send_log",
                                params={"message_id": f"eq.{mid}", "select": "run_id,resend_id"})
            if r.status_code == 200 and r.json():
                row = r.json()[0]
                return row.get("run_id"), row.get("resend_id")
        return None, None

    def insert_reply(self, row: dict) -> None:
        self.client.post(f"{self.base}/replies", json=row)

    def already_have(self, message_id: str) -> bool:
        if not message_id:
            return False
        r = self.client.get(f"{self.base}/replies",
                            params={"raw_headers->>Message-ID": f"eq.{message_id}", "select": "id"})
        return r.status_code == 200 and bool(r.json())

    def pause_run(self, run_id: str, reason: str) -> None:
        self.client.patch(f"{self.base}/runs",
                          params={"id": f"eq.{run_id}"},
                          json={"status": f"paused_{reason}"})


# ─── IMAP loop ──────────────────────────────────────────────────────────────

def split_refs(value: str) -> list[str]:
    if not value:
        return []
    return [s.strip() for s in re.findall(r"<[^>]+>", value)]


def one_pass(verbose: bool = True) -> dict:
    user, password = hostinger_creds()
    url, key = supabase_creds()
    supa = Supa(url, key)

    stats = {"processed": 0, "reply": 0, "bounce": 0, "complaint": 0, "unrelated": 0,
             "matched_to_run": 0, "runs_paused": 0, "errors": 0}

    imap = imaplib.IMAP4_SSL("imap.hostinger.com", 993)
    try:
        imap.login(user, password)
        imap.select("INBOX", readonly=False)
        typ, data = imap.search(None, "UNSEEN")
        if typ != "OK":
            return stats
        nums = data[0].split() if data and data[0] else []
        for num in nums:
            try:
                typ, msg_data = imap.fetch(num, "(RFC822)")
                if typ != "OK" or not msg_data or not msg_data[0]:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                stats["processed"] += 1
                klass = classify(msg)
                stats[klass] = stats.get(klass, 0) + 1

                from_addr = parseaddr(msg.get("From", ""))[1] or "(unknown)"
                to_addr   = parseaddr(msg.get("To", ""))[1] or user
                subject   = msg.get("Subject", "") or ""
                msg_id    = msg.get("Message-ID", "")
                in_reply  = split_refs(msg.get("In-Reply-To", ""))
                references = split_refs(msg.get("References", ""))

                if supa.already_have(msg_id):
                    if verbose: print(f"  ↩ skip (already recorded): {msg_id}")
                    imap.store(num, "+FLAGS", "\\Seen")
                    continue

                run_id, resend_id = supa.find_run_by_message_id(in_reply + references)
                if run_id:
                    stats["matched_to_run"] += 1

                snippet = extract_snippet(msg)

                supa.insert_reply({
                    "run_id":       run_id,
                    "profile_slug": None,
                    "from_addr":    from_addr,
                    "to_addr":      to_addr,
                    "subject":      subject[:500],
                    "class":        klass,
                    "body_snippet": snippet,
                    "raw_headers":  {"Message-ID": msg_id,
                                     "In-Reply-To": msg.get("In-Reply-To", ""),
                                     "References":  msg.get("References", "")},
                })

                if klass == "reply" and run_id:
                    supa.pause_run(run_id, "replied")
                    stats["runs_paused"] += 1
                elif klass == "bounce" and run_id:
                    supa.pause_run(run_id, "bounced")
                    stats["runs_paused"] += 1

                imap.store(num, "+FLAGS", "\\Seen")
                if verbose:
                    print(f"  ✓ {klass:9} from {from_addr[:32]:32}  matched_run={'yes' if run_id else 'no'}")
            except Exception as e:
                stats["errors"] += 1
                if verbose: print(f"  ! error on msg {num}: {e}")
    finally:
        try: imap.logout()
        except Exception: pass
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("once")
    p_loop = sub.add_parser("loop")
    p_loop.add_argument("--interval", type=int, default=300)
    args = ap.parse_args()

    if args.cmd == "once":
        stats = one_pass()
        print(json.dumps(stats, indent=2))
        return 0
    while True:
        try:
            stats = one_pass()
            print(f"[{dt.datetime.now():%H:%M:%S}] {stats}")
        except Exception as e:
            print(f"[{dt.datetime.now():%H:%M:%S}] error: {e}")
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
