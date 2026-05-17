"""context_autofill.py — autonomous business-context enrichment for every prospect.

Reads Supabase prospects table. For every row where:
  - we have a usable URL (prospect.website OR derived from email domain), AND
  - enriched_at is null OR older than --refresh-days days,

we run `context_enrich.enrich(url)` and write the result to
`enriched_context` + stamp `enriched_at`. This means a new prospect inserted
by `lead_scrape.py` (or manually) gets product/pricing/case-study context
attached within one scheduler tick, no human in the loop.

The enrichment pulls free, deterministic, regex-driven signals only — no
LLM, no third-party APIs. Good enough to merge into Hormozi-style pitches
where lines like "upselling Indicators subscribers to the {top_tier} bundle"
need real numbers per prospect.

CLI:
    py sequences/context_autofill.py once               # scan all eligible prospects
    py sequences/context_autofill.py once --slug X      # only one profile's prospects
    py sequences/context_autofill.py once --email X     # only one prospect
    py sequences/context_autofill.py once --force       # re-enrich even if already set
    py sequences/context_autofill.py once --limit 20    # cap how many we hit per tick

Schedule (every 60 min):
    schtasks /Create /TN "LES-context-enrich" /SC MINUTE /MO 60 ^
      /TR "py C:\\Users\\bernh\\local-email-stack\\sequences\\context_autofill.py once --limit 30"
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from dataclasses import asdict
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent))
from context_enrich import enrich  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE  = REPO_ROOT / "sequences" / "supabase.env"


def load_supabase() -> tuple[str, str]:
    env: dict[str, str] = {}
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line: continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env["SUPABASE_URL"].rstrip("/"), env["SUPABASE_ANON_KEY"]


FREE_MAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "icloud.com",
    "aol.com", "proton.me", "protonmail.com", "web.de", "gmx.de", "gmx.com",
    "mail.com", "live.com", "msn.com", "yandex.com", "yandex.ru", "zoho.com",
}


def _target_url(prospect: dict) -> str | None:
    """website > derive from email domain. Never returns a free-mail provider,
    even if a previous pipeline accidentally set website to one."""
    from urllib.parse import urlparse
    site = (prospect.get("website") or "").strip()
    if site:
        url = site if site.startswith(("http://", "https://")) else f"https://{site}"
        host = (urlparse(url).hostname or "").lower().replace("www.", "")
        if host in FREE_MAIL_DOMAINS:
            return None  # website was misfilled with a free-mail provider
        return url
    email = prospect.get("email") or ""
    if "@" in email:
        domain = email.split("@", 1)[1].lower()
        if domain in FREE_MAIL_DOMAINS:
            return None
        return f"https://{domain}"
    return None


def _eligible(prospect: dict, refresh_after: dt.datetime, force: bool) -> tuple[bool, str]:
    url = _target_url(prospect)
    if not url:
        return False, "no usable URL (no website and email is on a free-mail domain)"
    ts = prospect.get("enriched_at")
    if force or not ts: return True, "fresh"
    try:
        when = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (when < refresh_after), ("stale" if when < refresh_after else "fresh enough")
    except Exception:
        return True, "unparseable timestamp"


def autofill_once(slug: str | None = None, email: str | None = None,
                  force: bool = False, limit: int = 50,
                  refresh_days: int = 30, sleep_between: float = 1.0) -> int:
    url, key = load_supabase()
    refresh_after = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=refresh_days)

    with httpx.Client(base_url=f"{url}/rest/v1",
                      headers={"apikey": key, "Authorization": f"Bearer {key}",
                               "Content-Type": "application/json",
                               "Prefer": "return=representation"},
                      timeout=30) as c:
        q = ("/prospects?select=id,email,website,profile_slug,enriched_at,"
             "enriched_context&order=created_at.desc")
        if slug:  q += f"&profile_slug=eq.{slug}"
        if email: q += f"&email=eq.{email}"
        r = c.get(q); r.raise_for_status()
        prospects = r.json()

        examined = enriched = skipped = failed = 0
        for p in prospects[:limit]:
            examined += 1
            ok, why = _eligible(p, refresh_after, force)
            if not ok:
                print(f"  - {p['email']:40} skip: {why}")
                skipped += 1; continue

            target = _target_url(p)
            print(f"  > {p['email']:40} enriching from {target}")
            ctx = enrich(target)
            if ctx is None:
                print(f"    ! fetch failed")
                failed += 1; continue

            # Merge with any existing enriched_context so we don't trample
            # fields that were set by another pipeline (e.g. lead_scrape).
            merged = dict(p.get("enriched_context") or {})
            merged.update({k: v for k, v in asdict(ctx).items() if v})

            patch = {
                "enriched_context": merged,
                "enriched_at":      dt.datetime.utcnow().isoformat() + "Z",
            }
            up = c.patch(f"/prospects?id=eq.{p['id']}", json=patch)
            if up.status_code not in (200, 204):
                print(f"    ! patch {up.status_code}: {up.text[:200]}")
                failed += 1; continue
            enriched += 1
            summary = (ctx.product_summary or "(no summary)")[:80]
            extras = []
            if ctx.pricing_samples: extras.append(f"{len(ctx.pricing_samples)} prices")
            if ctx.user_count:      extras.append(f"users={ctx.user_count}")
            if ctx.outcome_snippets: extras.append(f"{len(ctx.outcome_snippets)} outcomes")
            print(f"    ok: {summary} [{', '.join(extras) or 'minimal'}]")
            time.sleep(sleep_between)

        print(f"\n=== summary === examined={examined} enriched={enriched} "
              f"skipped={skipped} failed={failed}")
        return 0 if failed == 0 else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_once = sub.add_parser("once")
    p_once.add_argument("--slug",  default=None, help="only one profile_slug")
    p_once.add_argument("--email", default=None, help="only one prospect by email")
    p_once.add_argument("--force", action="store_true", help="re-enrich even if already set")
    p_once.add_argument("--limit", type=int, default=50, help="max prospects per tick")
    p_once.add_argument("--refresh-days", type=int, default=30,
                        help="re-enrich rows whose enriched_at is older than N days")
    args = ap.parse_args()
    if args.cmd == "once":
        return autofill_once(args.slug, args.email, args.force, args.limit, args.refresh_days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
