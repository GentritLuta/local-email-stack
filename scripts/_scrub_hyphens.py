"""Scrub word-internal hyphens from visible text in the client deck.
Skips: <style> blocks, <script> blocks, tag attributes (class="grid-2"),
and CSS-like content inside tag bodies. Only touches actual rendered text."""
from pathlib import Path
import re

p = Path('docs/aureon-architecture-client.html')
h = p.read_text(encoding='utf-8')

# Strategy: walk the HTML token by token. Anything inside <style>...</style>,
# <script>...</script>, or inside a tag's < ... > brackets is "structure" and
# left alone. Everything else is text and gets the dash scrub.

TOKEN_RX = re.compile(
    r'(<style[\s\S]*?</style>|<script[\s\S]*?</script>|<[^>]+>)',
    re.IGNORECASE,
)
HYPHEN_WORD = re.compile(r'\b([A-Za-z]+)-([A-Za-z][A-Za-z-]*)\b')

def scrub_text(t: str) -> str:
    # Multiple iterations handle Word-Word-Word (which would otherwise
    # only collapse one hyphen per pass).
    while True:
        new = HYPHEN_WORD.sub(lambda m: m.group(1) + ' ' + m.group(2), t)
        if new == t:
            return t
        t = new

parts = TOKEN_RX.split(h)
for i, part in enumerate(parts):
    # Even indices = text between structure tokens
    if i % 2 == 0:
        parts[i] = scrub_text(part)
out = ''.join(parts)

# Replace stray ' - ' separators (left over from em-dash substitution).
# In text only; CSS/HTML structure won't have this pattern.
out_parts = TOKEN_RX.split(out)
for i, part in enumerate(out_parts):
    if i % 2 == 0:
        out_parts[i] = part.replace(' - ', ' ')
out = ''.join(out_parts)

# Collapse runs of double-space introduced by replacements
parts2 = TOKEN_RX.split(out)
for i, part in enumerate(parts2):
    if i % 2 == 0:
        parts2[i] = re.sub(r'  +', ' ', parts2[i])
out = ''.join(parts2)

p.write_text(out, encoding='utf-8')
print(f'  + scrubbed visible word-hyphens and " - " separators')
print(f'  + file size now: {len(out)/1024:.1f} KB')
