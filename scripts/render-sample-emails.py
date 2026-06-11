"""Render one real-prospect step-1 email per profile and save to disk.

Pulls a representative enrollable prospect for each profile, runs the same
render path the sequence-runner uses (`email_render.build_payload`), and
writes:
    out/sample_<profile>.html  — exact HTML the recipient will see
    out/sample_<profile>.txt   — text body + headers summary

Run after backfills / parser changes to confirm the new prospects render
without "Hey , at ." artifacts.
"""
from __future__ import annotations
import json
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))

from email_render import build_payload  # noqa: E402
import importlib.util as _ilu  # noqa: E402

_spec = _ilu.spec_from_file_location("sequence_runner", REPO / "sequences" / "sequence-runner.py")
_sr = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_sr)  # type: ignore
synthesize_optional_merges = _sr.synthesize_optional_merges

env = {}
for line in (REPO / "sequences" / "supabase.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}


def q(path: str):
    req = urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H)
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def first_enrollable(profile_slug: str, requires_city: bool) -> dict | None:
    rows = q(
        f"prospects?profile_slug=eq.{profile_slug}&verified=eq.true"
        f"&unsubscribed=eq.false&select=email,first_name,company,city,unsubscribe_token"
        f"&order=created_at.desc&limit=50"
    )
    for r in rows:
        if r.get("first_name") and r.get("company") and (not requires_city or r.get("city")):
            return r
    return None


PROFILES = [
    {"slug": "aureon",         "variants_dir": "aureon-default",         "requires_city": False},
    {"slug": "algoalpha",      "variants_dir": "algoalpha-default",      "requires_city": False},
    {"slug": "f2-malergipser", "variants_dir": "f2-malergipser-default", "requires_city": True},
]

OUT = REPO / "out"
OUT.mkdir(exist_ok=True)


def main() -> int:
    for p in PROFILES:
        slug = p["slug"]
        prospect = first_enrollable(slug, p["requires_city"])
        if not prospect:
            print(f"  ! {slug}: no enrollable prospect found")
            continue

        # Load profile JSON (for brand + a persona's from_addr/from_name)
        profile = json.loads((REPO / "profiles" / f"{slug}.json").read_text(encoding="utf-8"))
        personas = profile.get("personas") or []
        if not personas:
            print(f"  ! {slug}: no personas in profile JSON")
            continue
        persona = personas[0]
        brand = profile.get("brand") or {}

        # Load step-1 variant
        variants = json.loads(
            (REPO / "sequences" / p["variants_dir"] / "variants.json").read_text(encoding="utf-8")
        )
        step1 = next((v for v in variants["variants"] if v["n"] == 1), None)
        if not step1:
            print(f"  ! {slug}: no step-1 variant")
            continue

        # Render — pull the same optional merges sequence-runner uses, so
        # `{geo_clause}`, `{team_phrase}`, etc. are populated.
        merge = {
            "first_name": prospect["first_name"],
            "company":    prospect["company"],
            "city":       prospect.get("city") or "",
            "state":      prospect.get("state") or "",
            **synthesize_optional_merges(prospect),
        }
        subject = step1["subject"].format_map(merge)
        body    = step1["body"].format_map(merge)
        payload, msg_id = build_payload(
            persona=persona,
            to_addr=prospect["email"],
            subject=subject,
            body=body,
            unsubscribe_token=prospect.get("unsubscribe_token"),
            brand=brand,
            step_n=1,
        )

        html_path = OUT / f"sample_{slug}.html"
        txt_path  = OUT / f"sample_{slug}.txt"
        html_path.write_text(payload["html"], encoding="utf-8")
        # Plaintext summary
        summary = (
            f"=== {slug.upper()} step-1 sample ===\n"
            f"From:    {payload['from']}\n"
            f"To:      {payload['to'][0]}\n"
            f"Reply-To:{payload['reply_to']}\n"
            f"Subject: {payload['subject']}\n"
            f"Headers: {json.dumps(payload['headers'], indent=2)}\n"
            f"\n--- merge fields ---\n"
            f"first_name = {merge['first_name']}\n"
            f"company    = {merge['company']}\n"
            f"city       = {merge['city']}\n"
            f"\n--- text body ---\n"
            f"{payload['text']}\n"
        )
        txt_path.write_text(summary, encoding="utf-8")
        print(f"  + {slug:18}  to={prospect['email']:38}  subj=\"{subject[:60]}\"")
        print(f"      html -> {html_path}")
        print(f"      txt  -> {txt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
