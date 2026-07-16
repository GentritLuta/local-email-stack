# -*- coding: utf-8 -*-
"""suppress.py — the global do-not-contact list.

One list, all clients. A person who replies, opts out, or belongs to a blocked
domain (e.g. a former client) is never cold-emailed again by ANY profile, now or
after a future re-scrape. This is email- and domain-level, unlike prospects.unsubscribed
which is per-row and so misses re-scrapes into a new profile.

Table `suppression(value text pk, vtype 'email'|'domain', reason, created_at)`.

    from suppress import load_suppressed, is_suppressed, add_email, add_domain
    sup = load_suppressed()            # {'emails': set, 'domains': set}
    if is_suppressed(addr, sup): skip

Enforced at ENROLL (daily-fill-and-enroll) and SEND (sequence-runner backstop),
and fed at reply time (imap-poll).
"""
from __future__ import annotations
import json, urllib.request, urllib.parse
from pathlib import Path

_ENV = Path(__file__).resolve().parent / "supabase.env"
_e = {}
for _ln in _ENV.read_text().splitlines():
    if "=" in _ln and not _ln.strip().startswith("#"):
        _k, _v = _ln.split("=", 1); _e[_k.strip()] = _v.strip()
_URL = _e["SUPABASE_URL"].rstrip("/"); _KEY = _e["SUPABASE_ANON_KEY"]
_H = {"apikey": _KEY, "Authorization": "Bearer " + _KEY, "User-Agent": "les-suppress/1.0"}


def _dom(email: str) -> str:
    return (email or "").split("@")[-1].lower().strip()


def load_suppressed() -> dict:
    """Return {'emails': set[str], 'domains': set[str]} of everything suppressed.
    Fail-open on a read error (never block sending because the list was unreachable)."""
    try:
        rows, start = [], 0
        while True:
            req = urllib.request.Request(
                f"{_URL}/rest/v1/suppression?select=value,vtype&limit=1000&offset={start}", headers=_H)
            chunk = json.loads(urllib.request.urlopen(req, timeout=30).read())
            rows += chunk
            if len(chunk) < 1000:
                break
            start += 1000
        return {"emails": {r["value"] for r in rows if r["vtype"] == "email"},
                "domains": {r["value"] for r in rows if r["vtype"] == "domain"}}
    except Exception as ex:
        print(f"  ! suppress.load failed ({ex}); treating list as empty this pass")
        return {"emails": set(), "domains": set()}


def is_suppressed(email: str, sup: dict) -> bool:
    e = (email or "").lower().strip()
    return bool(e) and (e in sup["emails"] or _dom(e) in sup["domains"])


def _upsert(value: str, vtype: str, reason: str) -> None:
    body = json.dumps([{"value": value.lower().strip(), "vtype": vtype, "reason": reason}]).encode()
    req = urllib.request.Request(
        f"{_URL}/rest/v1/suppression?on_conflict=value", data=body, method="POST",
        headers={**_H, "Content-Type": "application/json", "Prefer": "resolution=ignore-duplicates,return=minimal"})
    try:
        urllib.request.urlopen(req, timeout=20)
    except Exception as ex:
        print(f"  ! suppress.add failed for {value}: {ex}")


def add_email(email: str, reason: str = "replied") -> None:
    if email and "@" in email:
        _upsert(email, "email", reason)


def add_domain(domain: str, reason: str = "blocked") -> None:
    if domain:
        _upsert(domain, "domain", reason)
