"""Render the parsed CSV as a PNG table + dump every row as text, so we can
visually AND textually inspect for errors before sending. Renders from the
RE-PARSED file (utf-8-sig, comma) — clean columns => well-formed CSV."""
import csv
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

REPO = Path(__file__).resolve().parent.parent
CSVF = REPO / "referral-lists" / "Attorney-Referral-List-Indianapolis.csv"
OUT = REPO / "referral-lists" / "_preview.png"

with CSVF.open(encoding="utf-8-sig", newline="") as fh:
    rows = list(csv.reader(fh))
header, data = rows[0], rows[1:]
ncol = len(header)
ragged = [(i + 2, len(r)) for i, r in enumerate(data) if len(r) != ncol]
print(f"columns ({ncol}): {header}")
print(f"data rows: {len(data)}  | ragged: {ragged or 'none'}")
empties = {header[c]: sum(1 for r in data if not r[c].strip()) for c in range(ncol)}
print(f"empty cells/col: {empties}\n")

# full textual dump for exact inspection
ti = header.index("Type") if "Type" in header else 1
for i, r in enumerate(data, 1):
    print(f"{i:2}. {r[0]}  [{r[ti]}]")
    for c in range(ncol):
        if c not in (0, ti):
            print(f"      {header[c]:14}: {r[c] or '-'}")

# ---- render PNG (cap widths for legibility) ----
FS = 15
try:
    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", FS)
    bold = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", FS)
except Exception:
    font = bold = ImageFont.load_default()
pad, rowh, CAP = 9, 30, 300
tmp = ImageDraw.Draw(Image.new("RGB", (1, 1)))


def trunc(text, maxpx):
    if tmp.textlength(text, font=font) <= maxpx:
        return text
    while text and tmp.textlength(text + "...", font=font) > maxpx:
        text = text[:-1]
    return text + "..."


widths = []
for c in range(ncol):
    w = tmp.textlength(header[c], font=bold)
    for r in data:
        w = max(w, tmp.textlength(r[c], font=font))
    widths.append(int(min(w, CAP)) + 2 * pad)
W, H = sum(widths), rowh * (len(data) + 1)
img = Image.new("RGB", (W, H), "white")
d = ImageDraw.Draw(img)
d.rectangle([0, 0, W, rowh], fill="#0f172a")
x = 0
for c in range(ncol):
    d.text((x + pad, 7), header[c], fill="white", font=bold)
    x += widths[c]
for i, r in enumerate(data):
    y = rowh * (i + 1)
    is_div = r[ti].startswith("Divorce")
    d.rectangle([0, y, W, y + rowh], fill="#ffffff" if i % 2 else "#f8fafc")
    x = 0
    for c in range(ncol):
        color = "#1e293b"
        if c == ti:
            d.rectangle([x + 4, y + 5, x + widths[c] - 4, y + rowh - 5],
                        fill="#dbeafe" if is_div else "#dcfce7")
            color = "#1e40af" if is_div else "#166534"
        d.text((x + pad, y + 7), trunc(r[c], widths[c] - 2 * pad), fill=color, font=font)
        x += widths[c]
    d.line([0, y, W, y], fill="#e2e8f0")
x = 0
for c in range(ncol):
    x += widths[c]; d.line([x, 0, x, H], fill="#e2e8f0")
img.save(OUT)
print(f"\nwrote {OUT}  ({W}x{H})")
