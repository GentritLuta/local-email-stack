# -*- coding: utf-8 -*-
"""ops_digest.py — collect operational alerts into ONE daily digest instead of
emailing each event.

The operator was getting flooded with per-event [WATCHDOG] and [SAFEGUARD] emails
(one per guard trip / remediation). Now those sources call ops_digest.record(...)
(NO email); the daily report drains this buffer once a day and renders a single
"System events" section. Remediation still HAPPENS in real time (the watchdog still
acts, guards still block) — only the NOTIFICATION is consolidated. 2026-06-16.
"""
from __future__ import annotations
import datetime as dt
import json
import os
from collections import Counter
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_BUF = _REPO / "warmup-state" / "ops_digest.jsonl"


def record(source: str, subject: str, detail: str = "", severity: str = "info") -> None:
    """Append one operational event to the digest buffer (no email). Best-effort;
    never raises (must not break a send or a watchdog tick)."""
    try:
        _BUF.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps({
            "ts": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": source, "severity": severity,
            "subject": subject, "detail": detail,
        }, ensure_ascii=False)
        with _BUF.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def drain() -> list[dict]:
    """Return all buffered events and CLEAR the buffer, so each event is reported
    exactly once. Renames first so concurrent per-brand writers append to a fresh
    file while we read the snapshot."""
    if not _BUF.exists():
        return []
    snap = _BUF.with_suffix(".jsonl.draining")
    try:
        os.replace(_BUF, snap)
    except Exception:
        return []
    events: list[dict] = []
    try:
        for ln in snap.read_text(encoding="utf-8").splitlines():
            ln = ln.strip()
            if not ln:
                continue
            try:
                events.append(json.loads(ln))
            except Exception:
                pass
        snap.unlink()
    except Exception:
        pass
    return events


def peek_count() -> int:
    if not _BUF.exists():
        return 0
    try:
        return sum(1 for ln in _BUF.read_text(encoding="utf-8").splitlines() if ln.strip())
    except Exception:
        return 0


def render_html(events: list[dict]) -> str:
    """One HTML section summarizing buffered ops events. Safe to embed in the
    daily report."""
    if not events:
        return ("<h3 style='margin:18px 0 6px'>System events (24h)</h3>"
                "<p style='color:#16a34a;margin:0'>All clear — no watchdog remedies "
                "or safeguard trips.</p>")
    by_source = Counter(e.get("source", "?") for e in events)
    head = " · ".join(f"{n}× {s}" for s, n in by_source.most_common())
    rows = []
    for e in sorted(events, key=lambda x: x.get("ts", "")):
        rows.append(
            "<tr>"
            f"<td style='padding:3px 8px;color:#64748b;white-space:nowrap'>{(e.get('ts') or '')[:16].replace('T',' ')}</td>"
            f"<td style='padding:3px 8px'><b>{e.get('source','')}</b></td>"
            f"<td style='padding:3px 8px'>{e.get('subject','')}</td>"
            "</tr>")
    return (f"<h3 style='margin:18px 0 6px'>System events (24h): {len(events)} "
            f"<span style='color:#64748b;font-weight:400'>({head})</span></h3>"
            "<table style='border-collapse:collapse;font-size:13px;width:100%'>"
            f"{''.join(rows)}</table>")
