"""trim-decks.py — delete slides 5, 11, 15 from every Aureon client deck
and renumber the remaining slide-num divs 1..15.

Operates on the 3 source decks in docs/ and the 3 mirrors in
~/Aureon-Presentations/. Idempotent: if a deck already has 15 slides
or doesn't contain the target slides, it's left alone.

Run:
    py scripts/trim-decks.py
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRES_DIR = Path.home() / "Aureon-Presentations"

FILES = [
    REPO / "docs" / "aureon-architecture-client.html",
    REPO / "docs" / "aureon-architecture-atal.html",
    REPO / "docs" / "aureon-architecture-otai.html",
    PRES_DIR / "Aureon-Listing-Engine-Client-Architecture.html",
    PRES_DIR / "Aureon-Listing-Engine-Atal.html",
    PRES_DIR / "Aureon-Listing-Engine-OTAI-Automates.html",
]

# Slide-num values to drop (display numbering, two-digit zero-padded).
DROP = {"05", "11", "15"}

SECTION_RX = re.compile(
    r"(?P<lead>\n?)(?P<comment><!--\s*SLIDE[^>]*-->\s*\n)?"
    r"<section class=\"slide[^\"]*\".*?</section>\s*\n",
    re.DOTALL,
)
SLIDE_NUM_RX = re.compile(r'<div class="slide-num">(\d{2})</div>')


def trim_one(path: Path) -> tuple[bool, str]:
    """Return (changed, message)."""
    if not path.exists():
        return False, f"SKIP (missing): {path}"

    html = path.read_text(encoding="utf-8")

    # Find all <section class="slide"...</section> blocks with their
    # leading SLIDE comment. We rebuild the file by keeping the head
    # before the first slide, dropping the targeted slides, renumbering
    # the rest, and keeping the tail after the last slide.
    matches = list(SECTION_RX.finditer(html))
    if not matches:
        return False, f"SKIP (no slides found): {path}"

    first_start = matches[0].start()
    last_end = matches[-1].end()
    head = html[:first_start]
    tail = html[last_end:]

    kept_blocks: list[str] = []
    for m in matches:
        block = m.group(0)
        num_match = SLIDE_NUM_RX.search(block)
        if not num_match:
            kept_blocks.append(block)
            continue
        if num_match.group(1) in DROP:
            continue
        kept_blocks.append(block)

    # Renumber the kept blocks 01..NN, two-digit zero-padded.
    renumbered: list[str] = []
    for i, block in enumerate(kept_blocks, start=1):
        new_num = f"{i:02d}"
        renumbered.append(SLIDE_NUM_RX.sub(
            f'<div class="slide-num">{new_num}</div>', block, count=1
        ))

    new_html = head + "".join(renumbered) + tail
    if new_html == html:
        return False, f"NOCHANGE: {path}"

    path.write_text(new_html, encoding="utf-8")
    return True, (
        f"OK: {path} -- dropped {len(matches) - len(kept_blocks)} slides, "
        f"renumbered {len(kept_blocks)} kept slides"
    )


def main() -> int:
    for path in FILES:
        changed, msg = trim_one(path)
        print(msg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
