# -*- coding: utf-8 -*-
"""Fill the placeholder fields in each client's pilot agreement from
contracts/client-contract-inputs.json.

Idempotent: only replaces a field that still shows a placeholder marker
(<span class="placeholder">, "(to be provided by Client)", or "...to be
confirmed by Client)"). A field whose input is an empty string is left as the
visible placeholder. Re-running after data is added fills only the new values.

Run after (re)generating contracts:  python scripts/fill-contract-placeholders.py
"""
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent
INPUTS = REPO / "contracts" / "client-contract-inputs.json"
DOCS = REPO / "docs"

# aureon-pilot-agreement-diraya-print.html doubles as the template base read by
# scripts/_gen-contracts.py, scripts/_gen-mark-eting-contract.py, and the live
# sequences/contract_lib.py. Filling it in place would break those. Diraya's real
# data stays in the inputs file; produce a standalone filled copy separately if needed.
SKIP_SLUGS = {"diraya"}

# The placeholder MARKER + field LABELS live in sequences/contract_lib.py so the
# legal fill logic has ONE source of truth (the live portal generator applies the
# same patterns on every contract). Import them here rather than redefining.
sys.path.insert(0, str(REPO / "sequences"))
from contract_lib import _FILL_MARKER as MARKER, _FILL_LABELS as LABELS  # noqa: E402

CONTRACT = "aureon-pilot-agreement-{slug}-print.html"


def html_escape(v: str) -> str:
    return v.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main() -> int:
    data = json.loads(INPUTS.read_text(encoding="utf-8"))
    slugs = [k for k in data if not k.startswith("_")]
    grand_filled = grand_skipped = grand_absent = 0
    still_missing = {}

    for slug in slugs:
        if slug in SKIP_SLUGS:
            print(f"  [skip] {slug}: template base (left as-is to protect generators/e-sign)")
            continue
        f = DOCS / CONTRACT.format(slug=slug)
        if not f.exists():
            print(f"  [skip] {slug}: no contract file ({f.name})")
            continue
        s = f.read_text(encoding="utf-8")
        rec = data[slug]
        filled, skipped, absent = [], [], []

        for field, label_re in LABELS.items():
            val = (rec.get(field) or "").strip()
            if not val:
                if field in rec:                       # field exists in inputs but empty
                    skipped.append(field)
                continue
            pat = re.compile(label_re + MARKER)
            new_s, n = pat.subn(lambda m: m.group(1) + html_escape(val), s, count=1)
            if n:
                s = new_s
                filled.append(field)
            else:
                absent.append(field)                   # value given but no placeholder to fill (already set / not in this contract)

        if filled:
            f.write_text(s, encoding="utf-8")
        grand_filled += len(filled); grand_skipped += len(skipped); grand_absent += len(absent)

        # what placeholders still remain in this contract after filling (count by line)
        remaining = sum(
            1 for line in s.splitlines()
            if ('class="placeholder"' in line)
            or re.search(r'\(to be provided by Client\)|to be confirmed by Client\)', line)
        )
        if remaining:
            still_missing[slug] = remaining
        miss = rec.get("_missing") or []
        print(f"  {slug:16} filled={filled or '-'}  empty_input={skipped or '-'}  "
              f"no_marker={absent or '-'}  placeholders_left={remaining}"
              + (f"  NEEDS={miss}" if miss else ""))

    print(f"\n  TOTAL: filled={grand_filled}, left_empty(no input)={grand_skipped}, "
          f"value_but_no_marker={grand_absent}")
    if still_missing:
        print("  Contracts still showing placeholders (data not yet provided): "
              + ", ".join(f"{k}({v})" for k, v in still_missing.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
