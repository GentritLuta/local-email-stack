"""intent_route.py — route scored seller-intent signals to per-channel deliverables.

Reads intent_signals rows (status='new') for an agent-client, groups them by the
channel the signal pack assigned, writes a per-channel CSV under out/intent/, and
marks the rows routed. Homeowners are never cold-emailed; these are mail / ad /
engage / prioritize actions that feed the consent-gated seller-appointment flow.

  direct_mail                    -> mailing list (distressed-seller direct mail)
  optin_funnel                   -> drive-to-funnel list (push to the home-value funnel)
  reply_or_dm / agent_follow_up  -> engagement list (public posts for the agent to work)
  ad_audience                    -> audience seed (Meta/Google geo + lookalike)
  prioritize_existing            -> priority list for the agent's own pipeline

Reads the local scan artifacts written by intent_signals.py by default (no DB).
Pass --from-db to read the intent_signals table instead (needs migration 009).

USAGE
  py sequences/intent_route.py route --profile <agent_slug> [--dry] [--from-db]
  py sequences/intent_route.py selftest      # offline, no DB
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Optional

import httpx

from intent_signals import _load_supabase_env, _supa_headers

REPO = Path(__file__).resolve().parent.parent
OUT_DIR = REPO / "out" / "intent"

# channel -> (output file stem). Several channels can share one bucket file.
CHANNEL_BUCKET = {
    "direct_mail": "direct_mail",
    "optin_funnel": "funnel_drive",
    "reply_or_dm": "engage",
    "agent_follow_up": "engage",
    "ad_audience": "ad_audience",
    "prioritize_existing": "prioritize",
}
COLUMNS = ["score", "confidence", "signal_id", "lead_label", "event_date",
           "evidence_url", "metro", "channel"]


def export_rows(rows: list[dict], profile_slug: str,
                out_dir: Optional[Path] = None) -> dict[str, int]:
    """Pure: group rows by channel bucket and write one CSV per bucket. Returns
    {filename: row_count}. No DB access, so it is offline-testable."""
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    buckets: dict[str, list[dict]] = {}
    for row in rows:
        bucket = CHANNEL_BUCKET.get(row.get("channel"), "other")
        buckets.setdefault(bucket, []).append(row)

    written: dict[str, int] = {}
    for bucket, brows in buckets.items():
        brows.sort(key=lambda r: float(r.get("score") or 0), reverse=True)
        fname = f"{profile_slug}_{bucket}.csv"
        with (out_dir / fname).open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
            w.writeheader()
            for r in brows:
                w.writerow({c: r.get(c, "") for c in COLUMNS})
        written[fname] = len(brows)
    return written


def _fetch_local(profile_slug: str) -> list[dict]:
    """Read scan artifacts written by intent_signals.py — the default, DB-free source."""
    rows: list[dict] = []
    for p in sorted(OUT_DIR.glob(f"{profile_slug}__*.signals.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        rows.extend(data.get("rows") or [])
    return rows


def _fetch_new(profile_slug: str) -> list[dict]:
    url, key = _load_supabase_env()
    if not url or not key:
        raise RuntimeError("missing SUPABASE_URL / key in sequences/supabase.env")
    r = httpx.get(
        f"{url}/rest/v1/intent_signals"
        f"?profile_slug=eq.{profile_slug}&status=eq.new"
        f"&order=score.desc&select=id,{','.join(COLUMNS)}",
        headers=_supa_headers(key), timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"fetch {r.status_code}: {r.text[:300]}")
    return r.json() or []


def _mark_routed(ids: list[str]) -> None:
    if not ids:
        return
    url, key = _load_supabase_env()
    id_list = ",".join(f'"{i}"' for i in ids)
    r = httpx.patch(
        f"{url}/rest/v1/intent_signals?id=in.({id_list})",
        headers={**_supa_headers(key), "Prefer": "return=minimal"},
        json={"status": "routed"}, timeout=30)
    if r.status_code not in (200, 204):
        raise RuntimeError(f"mark_routed {r.status_code}: {r.text[:300]}")


def route(profile_slug: str, dry: bool = False, from_db: bool = False) -> dict:
    rows = _fetch_new(profile_slug) if from_db else _fetch_local(profile_slug)
    if not rows:
        src = "intent_signals table" if from_db else f"out/intent/{profile_slug}__*.signals.json"
        print(f"  no intent signals for {profile_slug} in {src} "
              f"(run intent_signals.py first)")
        return {"profile": profile_slug, "rows": 0, "files": {}}
    written = export_rows(rows, profile_slug)
    if from_db and not dry:
        _mark_routed([r["id"] for r in rows if r.get("id")])
    print(f"\n--- routed {len(rows)} signals for {profile_slug}"
          f"{' (DRY)' if dry else ''} [{'db' if from_db else 'local'}] ---")
    for fname, n in sorted(written.items()):
        print(f"  {n:4d}  out/intent/{fname}")
    return {"profile": profile_slug, "rows": len(rows), "files": written,
            "source": "db" if from_db else "local", "dry": dry}


def _selftest() -> int:
    import tempfile
    ok = True

    def check(label, cond):
        nonlocal ok
        print(f"  {'OK ' if cond else 'FAIL'} {label}")
        ok = ok and cond

    rows = [
        {"id": "1", "score": 0.9, "confidence": 0.8, "signal_id": "pre_foreclosure",
         "lead_label": "123 Main St", "event_date": "2026-05-01",
         "evidence_url": "https://x/1", "metro": "Austin, TX", "channel": "direct_mail"},
        {"id": "2", "score": 0.5, "confidence": 0.6, "signal_id": "tax_delinquency",
         "lead_label": "9 Oak Ave", "event_date": "", "evidence_url": "https://x/2",
         "metro": "Austin, TX", "channel": "direct_mail"},
        {"id": "3", "score": 0.8, "confidence": 0.8, "signal_id": "public_intent_recommend_agent",
         "lead_label": "r/Austin recommend a realtor", "event_date": "",
         "evidence_url": "https://reddit.com/3", "metro": "Austin, TX", "channel": "reply_or_dm"},
        {"id": "4", "score": 0.7, "confidence": 0.7, "signal_id": "public_intent_relocating_sell",
         "lead_label": "relocating need to sell", "event_date": "",
         "evidence_url": "https://reddit.com/4", "metro": "Austin, TX", "channel": "optin_funnel"},
    ]
    with tempfile.TemporaryDirectory() as td:
        written = export_rows(rows, "testagent", Path(td))
        check(f"buckets written: {written}", len(written) == 3)
        check("direct_mail has 2", written.get("testagent_direct_mail.csv") == 2)
        check("engage has 1", written.get("testagent_engage.csv") == 1)
        check("funnel_drive has 1", written.get("testagent_funnel_drive.csv") == 1)
        # direct_mail CSV is score-sorted (0.9 before 0.5)
        dm = (Path(td) / "testagent_direct_mail.csv").read_text(encoding="utf-8").splitlines()
        check("header + 2 rows", len(dm) == 3)
        check("sorted by score desc", dm[1].startswith("0.9"))

    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("route", help="export per-channel deliverables for an agent")
    p.add_argument("--profile", required=True)
    p.add_argument("--dry", action="store_true")
    p.add_argument("--from-db", action="store_true",
                   help="read the intent_signals table instead of local artifacts")
    sub.add_parser("selftest", help="offline checks (no DB)")

    args = ap.parse_args()
    if args.cmd == "selftest":
        return _selftest()
    if args.cmd == "route":
        route(args.profile, dry=args.dry, from_db=args.from_db)
        return 0


if __name__ == "__main__":
    sys.exit(main())
