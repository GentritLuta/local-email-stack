"""brand_extract.py — given a client's website URL, pull their visual brand
into their profile so emails go out in their colors/fonts, not Aureon's.

What we extract (best-effort, all free, no APIs):
  * Wordmark + tagline (from <title>, meta og:site_name, meta description)
  * Color palette (every hex in inline styles and discoverable CSS — we keep
    the top accent + neutrals)
  * Primary font stack (font-family rules in inline style + linked Google Fonts)
  * Site root (the domain itself, used for the unsubscribe URL display + signature)

We do NOT scrape copy here (that's a separate copy_from_brand step that owns
copy generation and merges with the niche's variant template). This script
fills only the visual brand.

Usage:
    py sequences/brand_extract.py https://example.com aureon         # write to profiles/aureon.json
    py sequences/brand_extract.py https://example.com --dry          # print, don't write
    py sequences/brand_extract.py https://example.com --slug newco   # create / update profiles/newco.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse, urljoin

import httpx
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "Mozilla/5.0 LocalEmailStack/0.4 brand-extract"

# Heuristic: treat near-white/black backgrounds as neutrals; the "accent" is
# the most-used color OUTSIDE of {very dark, very light} space.
def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c*2 for c in h)
    if len(h) not in (6, 8):
        return 0.5
    r, g, b = int(h[0:2], 16)/255, int(h[2:4], 16)/255, int(h[4:6], 16)/255
    return 0.2126*r + 0.7152*g + 0.0722*b


def _normalize_hex(c: str) -> Optional[str]:
    c = c.strip().lower()
    if not re.fullmatch(r"#[0-9a-f]{3,8}", c): return None
    h = c.lstrip("#")
    if len(h) == 3: h = "".join(ch*2 for ch in h)
    if len(h) == 8: h = h[:6]  # drop alpha
    if len(h) != 6: return None
    return "#" + h


@dataclass
class Brand:
    wordmark:   str = ""
    site:       str = ""
    tagline:    str = ""
    font_stack: str = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
    font_url:   str = ""
    colors:     dict = field(default_factory=lambda: {
        "accent":   "#1f2937",
        "accent_2": "#374151",
        "text":     "#111827",
        "text_2":   "#4b5563",
        "muted":    "#9ca3af",
        "bg_page":  "#f5f5f5",
        "bg_card":  "#ffffff",
        "rule":     "#e5e7eb",
    })
    unsubscribe_url_template: str = "https://gentritluta.github.io/local-email-stack/unsubscribe.html?t={token}"
    extracted_from: str = ""
    extracted_at:   str = ""


def fetch(url: str, timeout: int = 25) -> tuple[Optional[str], dict]:
    """Returns (html, http_headers). None if fetch failed."""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True,
                          headers={"User-Agent": USER_AGENT,
                                   "Accept": "text/html,application/xhtml+xml"}) as c:
            r = c.get(url)
            return (r.text if r.status_code == 200 else None), dict(r.headers)
    except Exception as e:
        print(f"  ! fetch failed: {e}")
        return None, {}


def extract_brand(url: str) -> Optional[Brand]:
    html, _ = fetch(url)
    if not html:
        return None
    soup = BeautifulSoup(html, "lxml")
    parsed = urlparse(url)
    site_root = f"{parsed.scheme}://{parsed.netloc}"

    # Wordmark + tagline
    title = (soup.title.get_text(strip=True) if soup.title else "")[:80]
    wordmark = title.split(" - ")[0].split(" | ")[0].strip()[:60]
    meta_og   = soup.find("meta", property="og:site_name")
    if meta_og and meta_og.get("content"):
        wordmark = meta_og["content"].strip()[:60]
    meta_desc = soup.find("meta", attrs={"name": "description"})
    tagline = (meta_desc["content"].strip()[:140] if meta_desc and meta_desc.get("content") else "")

    # All inline + linked CSS content (linked CSS truncated to keep this free + fast)
    css_blob = html
    for link in soup.find_all("link", rel=lambda v: v and "stylesheet" in v.lower()):
        href = link.get("href")
        if not href: continue
        css_url = urljoin(url, href)
        css_body, _ = fetch(css_url)
        if css_body:
            css_blob += "\n" + css_body[:200_000]   # cap per file
        if len(css_blob) > 800_000: break            # cap total

    # Hex palette — count occurrences, sort by frequency
    hex_matches = re.findall(r"#[0-9a-fA-F]{3,8}\b", css_blob)
    counts = Counter(filter(None, (_normalize_hex(h) for h in hex_matches)))
    # Split into accent candidates (mid-luminance colors) and neutrals
    accent_candidates = []
    for hex_c, n in counts.most_common(80):
        L = _luminance(hex_c)
        if 0.10 < L < 0.85:
            accent_candidates.append((hex_c, n, L))

    palette = Brand().colors.copy()
    if accent_candidates:
        palette["accent"]   = accent_candidates[0][0]
        # Pick a darker variant of the accent (or the next-most-used) for hover/secondary
        same_hue = sorted(accent_candidates[:6], key=lambda x: x[2])
        palette["accent_2"] = same_hue[0][0] if same_hue else palette["accent"]

    # Font family: most common font-family declaration's first listed family
    fams = re.findall(r"font-family\s*:\s*([^;}\"\n]+)", css_blob, flags=re.I)
    fam_first = Counter()
    for f in fams:
        first = f.split(",")[0].strip().strip("'\"")
        # filter junk that isn't actually a font name
        if first and len(first) < 60 and not first.startswith(("var(", "inherit", "initial", "unset")):
            fam_first[first] += 1
    primary_font = fam_first.most_common(1)[0][0] if fam_first else ""
    font_stack = (f"'{primary_font}', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"
                  if primary_font else Brand().font_stack)

    # Google Fonts link (so the preview HTML can use the real font face)
    font_url = ""
    for link in soup.find_all("link", href=True):
        href = link["href"]
        if "fonts.googleapis.com" in href and primary_font.replace(" ", "+") in href.replace(" ", "+"):
            font_url = href
            break

    import datetime as dt
    return Brand(
        wordmark=wordmark, site=parsed.netloc, tagline=tagline,
        font_stack=font_stack, font_url=font_url, colors=palette,
        unsubscribe_url_template=Brand().unsubscribe_url_template,
        extracted_from=url,
        extracted_at=dt.datetime.utcnow().isoformat() + "Z",
    )


def write_brand(slug: str, brand: Brand) -> Path:
    p = REPO_ROOT / "profiles" / f"{slug}.json"
    if not p.exists():
        raise FileNotFoundError(f"profile not found: {p}. Create the profile first, then attach brand.")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    cfg["brand"] = asdict(brand)
    p.write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--slug", default=None,
                    help="profile slug to write brand into (profiles/<slug>.json). "
                         "Omit + use --dry to just preview.")
    ap.add_argument("--dry", action="store_true")
    args = ap.parse_args()

    brand = extract_brand(args.url)
    if brand is None:
        print("could not extract brand (fetch failed or empty page)")
        return 2

    print(json.dumps(asdict(brand), indent=2, ensure_ascii=False))
    if not args.dry and args.slug:
        path = write_brand(args.slug, brand)
        print(f"\nwrote brand to {path}")
    elif not args.dry and not args.slug:
        print("\n(no --slug given; pass --slug <slug> to write, or --dry to just preview)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
