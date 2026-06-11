from pathlib import Path
import re
from collections import Counter

h = Path('docs/aureon-architecture-client.html').read_text(encoding='utf-8')

# Strip style/script blocks
h2 = re.sub(r'<style[\s\S]*?</style>', '', h)
h3 = re.sub(r'<script[\s\S]*?</script>', '', h2)
# Strip ALL HTML attributes (anything matching ="..." or ='...')
h4 = re.sub(r"""\s+[a-zA-Z-]+\s*=\s*("[^"]*"|'[^']*')""", '', h3)
# Strip remaining HTML tags
text = re.sub(r'<[^>]+>', '\n', h4)
# Squash whitespace
text = re.sub(r'\s+', ' ', text).strip()

# Find word-internal hyphens
HYPHEN_RX = re.compile(r'\b[A-Za-z]+-[A-Za-z][A-Za-z-]*\b')
matches = [m.group(0) for m in HYPHEN_RX.finditer(text)]
unique = Counter(matches)
print(f'Total visible word-hyphens: {sum(unique.values())} ({len(unique)} unique)')
print()
for w, n in unique.most_common():
    print(f'  {n}x  {w}')
print()
# Also flag standalone hyphens in text (' - ' as separator)
isolated = len(re.findall(r' - ', text))
print(f"Standalone ' - ' separators in text: {isolated}")
