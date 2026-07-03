#!/usr/bin/env python3
"""client-reports.py — STANDARD per-client branded daily report dispatcher.

For every active client (or a chosen one) it:
  1. pulls the same detailed data as the internal aureon report (reuses
     daily-report.fetch_all_data + scope_to_profile + aggregate + render_html),
  2. brands the report with the client's REAL site logo + colors (site_style),
  3. sends it to BOTH the client's own email AND info@aureonglobal.de.

This is the onboarding standard: a new client gets a branded report to both
inboxes automatically, no per-client script. Reuses the 1100-line detailed
report engine in daily-report.py rather than duplicating it.

Usage:
  py scripts/client-reports.py                 # all active clients
  py scripts/client-reports.py --profile mark-eting
  py scripts/client-reports.py --include mark-eting   # also send for an inactive one
  py scripts/client-reports.py --dry           # render, print, don't send
"""
import argparse
import json
import re
import sys
import datetime as dt
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))

import importlib
dr = importlib.import_module("daily-report")          # the detailed report engine
from site_style import extract_site_style              # noqa: E402

AGENCY_INBOX = "info@aureonglobal.de"


def load_profile(slug: str) -> dict:
    return json.loads((REPO / "profiles" / f"{slug}.json").read_text(encoding="utf-8"))


def list_target_slugs(args) -> list[str]:
    slugs = []
    for f in sorted((REPO / "profiles").glob("*.json")):
        if f.name.endswith(".private.json"):
            continue
        if f.name.startswith("."):
            # orphaned atomic-write temp (.tmp.*.json) — never a real profile.
            # Loading it as a client would leak all clients' data (2026-07-03).
            continue
        slug = f.stem
        if args.profile:
            if slug == args.profile:
                slugs.append(slug)
            continue
        d = load_profile(slug)
        if d.get("active") or slug in (args.include or []):
            slugs.append(slug)
    return slugs


def client_email(profile: dict) -> str | None:
    # relay.report_to is the curated human recipient; contact_email is the fallback.
    return (profile.get("relay", {}).get("report_to")
            or profile.get("brand", {}).get("legal", {}).get("contact_email"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None, help="only this client")
    ap.add_argument("--include", nargs="*", default=[], help="also send for these inactive slugs")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--agency-only", action="store_true",
                    help="send only to info@ (skip the client address) — for testing")
    args = ap.parse_args()

    targets = list_target_slugs(args)
    if not targets:
        print("no target clients"); return 0
    print(f"clients: {', '.join(targets)}")

    print("fetching data once for all clients...")
    base = dr.fetch_all_data()

    for slug in targets:
        prof = load_profile(slug)
        # Scope the shared dataset to this client + aggregate.
        data = dr.scope_to_profile(dict(base), slug)
        agg = dr.aggregate(data)

        # Brand: real site logo + colors (falls back to profile brand).
        site = prof.get("brand", {}).get("site") or prof.get("company", {}).get("site") or ""
        style = extract_site_style(site, prof) if site else {}
        pname = (data["profiles"][0]["name"] if data.get("profiles") else prof.get("name", slug))
        pname = re.split(r"\s+[—–-]\s+", pname)[0].strip()
        # Accent: prefer a vivid brand color. If the resolved accent is near-black
        # or near-white (a poor header color), fall back to the profile's accent_2.
        pcolors = prof.get("brand", {}).get("colors", {})
        accent = style.get("accent") or pcolors.get("accent") or "#d4af37"

        def _luma(h):
            h = h.lstrip("#")
            if len(h) == 3:
                h = "".join(c * 2 for c in h)
            try:
                return 0.2126 * int(h[0:2], 16) + 0.7152 * int(h[2:4], 16) + 0.0722 * int(h[4:6], 16)
            except ValueError:
                return 128
        if _luma(accent) < 35 or _luma(accent) > 225:
            alt = pcolors.get("accent_2")
            if alt and 35 <= _luma(alt) <= 225:
                accent = alt
        client_mode = {
            "name":   pname,
            "accent": accent,
            "dark":   style.get("bg") or "#0b0b0b",
            "logo":   style.get("logo_url"),
        }
        html = dr.render_html(agg, client_mode=client_mode)

        subject = (f"{pname} - campaign report - {dt.datetime.now().strftime('%a %b %d')} - "
                   f"{agg['today']['sent']} sent, {agg['today']['real_replies']} replied")
        subject = subject.replace("—", "-").replace("–", "-")

        # Recipients: client email + agency inbox (deduped).
        recips = []
        ce = client_email(prof)
        for r in ([] if args.agency_only else [ce]) + [AGENCY_INBOX]:
            if r and r.lower() not in [x.lower() for x in recips]:
                recips.append(r)
        to = ",".join(recips)

        print(f"\n[{slug}] -> {to}  (logo={'yes' if client_mode['logo'] else 'no'}, "
              f"accent={client_mode['accent']})")
        dr.send_via_resend(to_addr=to, subject=subject, html=html, dry=args.dry)

    return 0


if __name__ == "__main__":
    sys.exit(main())
