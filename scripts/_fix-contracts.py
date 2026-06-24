# -*- coding: utf-8 -*-
"""Deterministic cleanup pass for the generated client contracts.

The per-client agents swap the parties table + recitals but sometimes miss the
client SIGNATURE block (leaving 'Diraya Inc.' / 'Mohammed El Amine Amoura') and
stray Diraya references. This pass fixes the signature block and scrubs every
base-template (Diraya/SMH) leak deterministically, then verifies zero leaks +
zero em dashes. Run after the contract workflow writes the HTML files.
"""
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = Path(__file__).resolve().parent.parent

CLIENTS = {
    "dorian":          dict(entity="Skiljo Enterprise",   sig="Dorian Skiljo",  title="Founder",   place="Munich, Germany"),
    "lk-advertising":  dict(entity="LK Advertising",      sig="Lukas Koehler",  title="Owner",     place="Karlsruhe, Germany"),
    "energ":           dict(entity="ENER-G Beratung",     sig="Philipp Loisha", title="Owner",     place="Muenster, Germany"),
    "algoalpha":       dict(entity="AlgoAlpha",           sig="Tomas Silva",    title="Founder",   place="Lisbon, Portugal"),
}

# Every base-template client token that must NOT survive in any output.
BASE_LEAK = ["Diraya Inc.", "Diraya", "Mohammed El Amine Amoura", "Mohammed",
             "amoura.ma@diraya.ca", "amoura", "diraya.ca",
             "Sales Methodology Hub", "The Founder Academy Limited", "Founder Academy",
             "Ashraf Hussain", "Ashraf", "Tilbury"]


def fix_one(slug: str, c: dict) -> None:
    f = REPO / "docs" / f"aureon-pilot-agreement-{slug}-print.html"
    if not f.exists():
        print(f"  ! {slug}: file missing, skip")
        return
    s = f.read_text(encoding="utf-8")

    # 1. Client SIGNATURE block: the second sig-entity (Diraya Inc.) + its Name/Title/Place.
    #    Replace the Diraya signer identity wherever it appears in a sig context.
    s = s.replace(
        '<div class="sig-entity">Diraya Inc.</div>',
        f'<div class="sig-entity">{c["entity"]}</div>')
    s = s.replace(
        '<span class="sig-line filled">Mohammed El Amine Amoura</span>',
        f'<span class="sig-line filled">{c["sig"]}</span>')
    # Title in the client sig block was 'Founder' for Diraya; only swap if this client differs
    # AND only inside the client sig context. Diraya's client title line:
    s = s.replace(
        '<span class="label">Title</span><span class="sig-line filled">Founder</span>',
        f'<span class="label">Title</span><span class="sig-line filled">{c["title"]}</span>')
    # Client name line "Name: Mohammed El Amine Amoura" (recital/notice area)
    s = s.replace("Name: Mohammed El Amine Amoura", f"Name: {c['sig']}")

    # 2. Scrub any residual base-template client tokens -> this client's entity.
    #    (Do the longest tokens first so 'Diraya Inc.' is handled before 'Diraya'.)
    for tok in BASE_LEAK:
        if tok in s:
            repl = c["entity"] if tok in ("Diraya Inc.", "Diraya") else c["sig"] if "Amoura" in tok or "Mohammed" in tok or "Ashraf" in tok else c["entity"]
            s = s.replace(tok, repl)

    # 3. No em/en dashes anywhere.
    s = s.replace(" — ", " - ").replace("—", "-").replace(" – ", " - ").replace("–", "-")

    f.write_text(s, encoding="utf-8")

    # 4. Verify
    leaks = [t for t in BASE_LEAK if t.lower() in s.lower()]
    # other-client leaks
    others = []
    for oslug, oc in CLIENTS.items():
        if oslug == slug:
            continue
        for tok in (oc["entity"], oc["sig"]):
            if re.search(r"\b" + re.escape(tok) + r"\b", s):
                others.append(f"{oslug}:{tok}")
    emd = "—" in s or "–" in s
    status = "OK" if not leaks and not others and not emd else "STILL-LEAKS"
    print(f"  [{status}] {slug:16} base_leaks={leaks} other_clients={others} em_dash={emd}")


def main() -> int:
    for slug, c in CLIENTS.items():
        fix_one(slug, c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
