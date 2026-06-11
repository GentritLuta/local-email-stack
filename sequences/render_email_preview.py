"""render_email_preview.py — render variant HTML + screenshot it.

For each profile + variant pair, this builds the actual HTML payload the
recipient would see (using the same email_render pipeline that real sends
use), loads it in a Playwright Chromium at email-typical width (640px),
and saves a PNG.

Usage:
    py render_email_preview.py <profile_slug> <variants_json> [--persona slug] [--out path.png]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
import json
import re

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_lib import load_profile, iter_send_domains, materialize_persona
from email_render import build_payload


def render(profile_slug: str, variants_path: str, persona_slug: str | None,
           out_path: str, demo_overrides: dict[str, str] | None = None,
           variant_n: int = 1) -> int:
    profile = load_profile(profile_slug)
    personas = profile.get("personas") or []
    if persona_slug:
        persona = next((p for p in personas if p["slug"] == persona_slug), personas[0])
    else:
        persona = personas[0]
    domain = iter_send_domains(profile)[0]
    materialized = materialize_persona(persona, domain)

    all_variants = json.loads(Path(variants_path).read_text(encoding="utf-8"))["variants"]
    v = next((x for x in all_variants if x.get("n") == variant_n), all_variants[0])
    # Substitute merge tags with sensible demo values. The real send path
    # (sequence-runner.py:_render_merge) replaces these with prospect-row
    # data; if any tag is missing on a real prospect the run is skipped.
    # Demo values below are only for the preview screenshot.
    DEMO = {
        "first_name": "Max",
        "last_name":  "Mustermann",
        "company":    "Müller Immobilien GmbH",
        "city":       "München",
        "state":      "Bayern",
        "title":      "Senior Makler",
        # algoalpha derived merges (sequence-runner computes these from
        # prospects.audience_size at send time; demo = a 270k channel)
        "retainer_quote": "a flat 1,100 USD per video",
        "retainer_math":  ("Your rate is locked on our end: we pay you 1,100 USD per "
                           "video, flat, up to four paid videos a month. That is up to "
                           "4,400 USD a month in retainer, paid up front, win or lose, "
                           "before a single viewer signs up."),
    }
    DEMO.update(demo_overrides or {})
    body = v["body"]
    subject = v["subject"]
    for tag, val in DEMO.items():
        body = body.replace("{" + tag + "}", val)
        subject = subject.replace("{" + tag + "}", val)

    brand = profile.get("brand") or {}
    payload, _ = build_payload(
        persona=materialized, to_addr="preview@example.com",
        subject=subject, body=body, brand=brand, step_n=variant_n,
    )
    html = payload["html"]
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Wrap with a gmail-like background so the email card stands out
    wrapper = f"""<!doctype html>
<html><head><meta charset=\"utf-8\"></head>
<body style=\"margin:0;padding:24px;background:#f1f5f9;font-family:-apple-system,Segoe UI,Roboto,sans-serif;\">
<div style=\"max-width:680px;margin:0 auto;\">
  <div style=\"padding:8px 12px 16px;color:#475569;font-size:13px;\">
    <div><b>From</b> {payload['from']}</div>
    <div><b>To</b> {payload['to'][0]}</div>
    <div><b>Subject</b> {payload['subject']}</div>
  </div>
  <div style=\"background:white;border-radius:8px;box-shadow:0 1px 3px rgba(0,0,0,0.06);overflow:hidden;\">
    {html}
  </div>
</div>
</body></html>"""
    out.write_text(wrapper, encoding="utf-8")
    print(f"wrote {out} ({len(wrapper)} bytes)")

    # Screenshot via Playwright
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        ctx = b.new_context(viewport={"width": 720, "height": 1200},
                             device_scale_factor=1)
        page = ctx.new_page()
        page.goto(out.absolute().as_uri(), wait_until="domcontentloaded")
        page.wait_for_timeout(800)
        # Take a full-page screenshot
        png_path = out.with_suffix(".png")
        page.screenshot(path=str(png_path), full_page=True)
        ctx.close(); b.close()
    print(f"screenshot: {png_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("profile_slug")
    ap.add_argument("variants")
    ap.add_argument("--persona", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--demo", default=None,
                    help='JSON of demo merge overrides, e.g. \'{"company":"Foo","city":"Bar"}\'')
    ap.add_argument("--variant-n", type=int, default=1,
                    help="Which variant n to render (default 1). Also used as step_n "
                         "so CTA visibility follows the per-step rule (button hidden on step 1).")
    args = ap.parse_args()
    overrides = json.loads(args.demo) if args.demo else None
    return render(args.profile_slug, args.variants, args.persona, args.out, overrides,
                  variant_n=args.variant_n)


if __name__ == "__main__":
    sys.exit(main())
