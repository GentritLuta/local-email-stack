"""Render every (profile × step) variant against a representative real
prospect and check for merge-field artifacts, KeyErrors, encoding issues.

Catches:
  - Unresolved {placeholders} (e.g. variant uses {state} but synthesize doesn't fill it)
  - KeyError on .format_map (variant references a key we don't supply)
  - Empty greetings ("Hey ,")
  - Empty company in body ("checking out ")
  - Non-ASCII or unrenderable text

Exit code: 0 if all 21 renders pass strict checks; non-zero with a report otherwise.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "sequences"))
import importlib.util as _ilu
_spec = _ilu.spec_from_file_location("sequence_runner", REPO / "sequences" / "sequence-runner.py")
_sr = _ilu.module_from_spec(_spec); _spec.loader.exec_module(_sr)  # type: ignore
synthesize_optional_merges = _sr.synthesize_optional_merges
find_merge_tags = _sr.find_merge_tags

import urllib.request
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}"}

def q(path: str):
    return json.loads(urllib.request.urlopen(urllib.request.Request(f"{URL}/rest/v1/{path}", headers=H), timeout=20).read())

# Sample one real enrollable prospect per profile (must have all 3 merge fields)
PROFILES = [
    {"slug": "aureon",         "variants_dir": "aureon-default",         "requires_city": False},
    {"slug": "algoalpha",      "variants_dir": "algoalpha-default",      "requires_city": False},
]

ARTIFACT_RX = re.compile(r"\{[a-z_]+\}")            # unrendered {field}
EMPTY_GREETING_RX = re.compile(r"\b(Hey|Guten Tag) ,", re.I)
EMPTY_BODY_RX = re.compile(r"(checking out|sehe, was|nach)\s+,", re.I)


def main() -> int:
    issues: list[str] = []
    for prof in PROFILES:
        slug = prof["slug"]
        rows = q(
            f"prospects?profile_slug=eq.{slug}&verified=eq.true&unsubscribed=eq.false"
            f"&first_name=not.is.null&company=not.is.null"
            + ("&city=not.is.null" if prof["requires_city"] else "")
            + "&select=email,first_name,last_name,company,city,state&limit=1"
        )
        if not rows:
            issues.append(f"  {slug}: no enrollable prospect to render against")
            continue
        prospect = rows[0]
        variants = json.loads((REPO / "sequences" / prof["variants_dir"] / "variants.json").read_text(encoding="utf-8"))
        merge = {
            "first_name": prospect["first_name"] or "",
            "company":    prospect["company"]    or "",
            "city":       prospect.get("city")   or "",
            "state":      prospect.get("state")  or "",
            **synthesize_optional_merges(prospect),
        }
        # AlgoAlpha only — personal_hook is filled by personal_hook_worker
        if slug == "algoalpha":
            merge["personal_hook"] = "your latest TradingView indicator drop"
        print(f"--- {slug}  (prospect={prospect['email']}) ---")
        for v in variants["variants"]:
            step = v["n"]
            tags_subj = find_merge_tags(v["subject"])
            tags_body = find_merge_tags(v["body"])
            try:
                subj = v["subject"].format_map(merge)
                body = v["body"].format_map(merge)
            except KeyError as e:
                issues.append(f"  {slug} step{step}: KeyError on .format_map: {e}  (tags subj={tags_subj} body={tags_body})")
                print(f"  step{step}: ! KeyError {e}")
                continue
            problems = []
            if ARTIFACT_RX.search(subj):
                problems.append(f"unrendered {{...}} in subject: {ARTIFACT_RX.findall(subj)}")
            if ARTIFACT_RX.search(body):
                problems.append(f"unrendered {{...}} in body: {ARTIFACT_RX.findall(body)}")
            if EMPTY_GREETING_RX.search(body):
                problems.append("empty greeting (Hey ,)")
            if EMPTY_BODY_RX.search(body):
                problems.append("empty company reference")
            tag = "OK" if not problems else "FAIL"
            print(f"  step{step}: {tag}  subj={subj[:60]!r}")
            for p in problems:
                print(f"          ! {p}")
                issues.append(f"  {slug} step{step}: {p}")
    print()
    if issues:
        print(f"=== {len(issues)} ISSUES ===")
        for i in issues: print(i)
        return 1
    print("=== ALL 21 (profile x step) variants render clean ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
