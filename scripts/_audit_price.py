from pathlib import Path
import re
from collections import Counter

h = Path('docs/aureon-architecture-client.html').read_text(encoding='utf-8')
h2 = re.sub(r'<style[\s\S]*?</style>', '', h)
h3 = re.sub(r'<script[\s\S]*?</script>', '', h2)
# Strip attribute values so we don't false-positive on CSS class names
h4 = re.sub(r'="[^"]*"', '', h3)
patterns = [
    (r'\$[\d,]+(?:k|K|m|M)?', '$amount'),
    (r'(?i)\bROI\b', 'ROI'),
    (r'(?i)\bARR\b', 'ARR'),
    (r'(?i)\bACV\b', 'ACV'),
    (r'(?i)\bLTV\b', 'LTV'),
    (r'(?i)break[- ]?even', 'break even'),
    (r'(?i)pricing', 'pricing'),
    (r'(?i)per\s+month', 'per month'),
    (r'(?i)monthly\s+cost', 'monthly cost'),
    (r'(?i)cost\s+per', 'cost per'),
    (r'(?i)\btier\b', 'tier'),
    (r'(?i)closed\s+won', 'closed won'),
    (r'(?i)commission', 'commission'),
]
total = 0
for p, label in patterns:
    matches = re.findall(p, h4)
    if matches:
        print(f'  {label}: {len(matches)}x')
        for m in matches[:3]:
            print(f'      e.g. {m!r}')
        total += len(matches)
print(f'\nTotal money/ROI signals: {total}')
