#!/usr/bin/env python3
"""site_style.py — extract a client's real website style (logo, fonts, colors)
with NO browser dependency, so it works every time at onboarding.

Fetches the homepage HTML + linked CSS via httpx and mines:
  - logo:    <img> with 'logo' in src/alt/class -> og:image -> apple-touch-icon
  - fonts:   Google Fonts <link> family names; CSS font-family declarations
  - colors:  theme-color meta; CSS custom props (--*-color / --primary / --accent);
             most-common hex colors in the CSS (background vs text vs accent)

Every field falls back to the profile's brand.colors / font_stack when the site
can't be read (JS-only sites, blank homepages). Returns a dict the unsub-page
generator consumes. Importable: `from site_style import extract_site_style`.

CLI:  py scripts/site_style.py <site_url> [profile_slug]
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120 Safari/537.36")
HEADERS = {"User-Agent": UA}


def _get(url: str, timeout: int = 20) -> str:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=timeout, follow_redirects=True)
        if r.status_code == 200 and "text" in r.headers.get("content-type", ""):
            return r.text
    except Exception:
        pass
    return ""


def _is_image(url: str) -> bool:
    try:
        r = httpx.get(url, headers={**HEADERS, "Range": "bytes=0-0"}, timeout=12,
                      follow_redirects=True)
        return (r.status_code in (200, 206)
                and r.headers.get("content-type", "").startswith("image"))
    except Exception:
        return False


def find_logo(base: str, html: str) -> str | None:
    """First <img> whose src/alt/class mentions 'logo', else og:image, else icon.
    Only returns a URL that actually loads as an image."""
    cands: list[str] = []
    for m in re.finditer(r"<img[^>]+>", html, re.I):
        tag = m.group(0)
        src = re.search(r'src=["\']([^"\']+)["\']', tag)
        if src and "logo" in tag.lower():
            cands.append(urljoin(base, src.group(1)))
    og = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if og:
        cands.append(urljoin(base, og.group(1)))
    ic = re.search(r'<link[^>]+rel=["\'][^"\']*icon[^"\']*["\'][^>]+href=["\']([^"\']+)', html, re.I)
    if ic:
        cands.append(urljoin(base, ic.group(1)))
    seen = set()
    for u in cands:
        if u in seen or u.startswith("data:"):
            continue
        seen.add(u)
        if _is_image(u):
            return u
    return None


def find_fonts(html: str, css: str) -> tuple[str | None, str | None]:
    """Return (font_url, font_family_stack) — CONSISTENT: if a Google Fonts link
    exists, both the URL and the family come from it (so the linked font is the
    one the CSS asks for). Only the css2/css stylesheet href counts (not the
    preconnect domain link). If there's no Google Fonts link we return
    (None, stack-from-CSS) — the family renders if the user has it, else system."""
    font_url = None
    # Must match the actual stylesheet path /css or /css2 with a query — not the
    # bare https://fonts.googleapis.com preconnect link.
    m = re.search(r'<link[^>]+href=["\'](https://fonts\.googleapis\.com/css2?\?[^"\']+)["\']', html, re.I)
    if m:
        font_url = m.group(1).replace("&amp;", "&")

    fam = None
    if font_url:
        # The family the linked stylesheet actually provides — keeps URL+stack in sync.
        fm = re.search(r"family=([^:&]+)", font_url)
        if fm:
            fam = fm.group(1).replace("+", " ")
    if not fam:
        fm = re.search(r"font-family\s*:\s*([^;}{]+)", css or html, re.I)
        if fm:
            fam = fm.group(1).split(",")[0]
    stack = None
    if fam:
        fam = fam.strip().strip('"\'').strip()
        if fam and not fam.startswith("var("):
            stack = (f"'{fam}', -apple-system, BlinkMacSystemFont, 'Segoe UI', "
                     "Roboto, sans-serif")
    return font_url, stack


def _hexes(text: str) -> list[str]:
    out = []
    for h in re.findall(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})\b", text):
        h = h.lower()
        if len(h) == 4:  # #abc -> #aabbcc
            h = "#" + "".join(c * 2 for c in h[1:])
        out.append(h)
    return out


def _luma(hexc: str) -> float:
    r = int(hexc[1:3], 16); g = int(hexc[3:5], 16); b = int(hexc[5:7], 16)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def find_colors(html: str, css: str) -> dict:
    """Best-effort site colors. Strategy: theme-color meta for accent; then the
    most-common dark + light hexes in the CSS for bg/text; CSS custom props named
    accent/primary/brand for the accent. Returns {} keys it couldn't determine."""
    blob = (css or "") + "\n" + html
    out: dict = {}

    # accent from CSS custom properties named accent/primary/brand
    for m in re.finditer(r"--[\w-]*(?:accent|primary|brand)[\w-]*\s*:\s*(#[0-9a-fA-F]{3,6})", blob, re.I):
        out["accent"] = _hexes(m.group(1))[0]
        break
    # theme-color meta as accent fallback
    if "accent" not in out:
        m = re.search(r'<meta[^>]+name=["\']theme-color["\'][^>]+content=["\'](#[0-9a-fA-F]{3,6})', html, re.I)
        if m:
            out["accent"] = _hexes(m.group(1))[0]

    hexes = _hexes(blob)
    if hexes:
        counts = Counter(hexes)
        # candidate bg = most common very-dark or very-light; text = opposite
        dark = [h for h in counts if _luma(h) < 60]
        light = [h for h in counts if _luma(h) > 200]
        if dark:
            out.setdefault("bg", Counter({h: counts[h] for h in dark}).most_common(1)[0][0])
        if light:
            out.setdefault("text_on_dark", Counter({h: counts[h] for h in light}).most_common(1)[0][0])
        # accent fallback: most common mid-saturation color that isn't bg/text
        if "accent" not in out:
            mids = [h for h in counts if 60 <= _luma(h) <= 200]
            if mids:
                out["accent"] = Counter({h: counts[h] for h in mids}).most_common(1)[0][0]
    return out


def extract_site_style(site_url: str, profile: dict | None = None) -> dict:
    """Extract {logo_url, font_url, font_stack, accent, bg, text} from the live
    site, falling back to the profile's brand for anything not found. ALWAYS
    returns a complete, renderable style dict."""
    if not site_url.startswith("http"):
        site_url = "https://" + site_url
    html = _get(site_url)
    # pull the first linked stylesheet (helps color/font mining)
    css = ""
    if html:
        cm = re.search(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)', html, re.I)
        if cm:
            css = _get(urljoin(site_url, cm.group(1)))

    brand = (profile or {}).get("brand", {})
    colors = brand.get("colors", {})
    legal = brand.get("legal", {})

    # Logo priority: a profile-curated logo (legal.logo_url / brand.logo_url) is
    # DELIBERATE, so it wins. Only auto-mine the site when the profile has none.
    # (Mining can grab an og-image/banner; a curated URL is the real brand mark.)
    logo = None
    for cand in (legal.get("logo_url"), brand.get("logo_url")):
        if cand and str(cand).startswith("http") and _is_image(cand):
            logo = cand
            break
    if not logo and html:
        logo = find_logo(site_url, html)

    font_url, font_stack = find_fonts(html, css)
    if font_url:
        # Site gave a real Google Fonts stylesheet — use its URL + family together.
        pass
    elif brand.get("font_url"):
        # No site font link: fall back to the profile's font URL AND its matching
        # stack together (never mix a mined family with the profile's URL).
        font_url = brand.get("font_url")
        font_stack = brand.get("font_stack") or font_stack
    # else: keep the mined font_stack (renders if installed), no <link>.
    font_stack = font_stack or brand.get("font_stack") or \
        "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif"

    site_colors = find_colors(html, css) if html else {}
    # Accent: the profile's hand-set brand accent is curated and correct, so it
    # wins. Only fall back to a site-mined accent when the profile has none, and
    # never use a near-black/near-white mined "accent" (those are bg/text, not a
    # brand color).
    accent = colors.get("accent") or colors.get("accent_2")
    if not accent:
        mined = site_colors.get("accent")
        if mined and 40 < _luma(mined) < 215:
            accent = mined
    accent = accent or "#d4af37"
    # bg: an explicit profile override (brand.colors.unsub_bg) wins — for sites
    # whose mined bg is wrong (e.g. a gradient section instead of the real page).
    # Otherwise use the mined bg, then profile dark/navy, then default dark.
    bg = (colors.get("unsub_bg") or site_colors.get("bg")
          or colors.get("bg_dark") or colors.get("navy") or "#0b0b0b")
    # text follows bg: dark text on a light bg, light text on a dark bg.
    bg_is_light = _luma(bg) > 150
    text = colors.get("unsub_text") or ("#0a0a0a" if bg_is_light else "#ffffff")

    return {
        "logo_url": logo,
        "font_url": font_url,
        "font_stack": font_stack,
        "accent": accent,
        "bg": bg,
        "text": text,
        "source": "site" if html else "profile-fallback",
    }


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    site = sys.argv[1]
    profile = None
    if len(sys.argv) > 2:
        p = Path(f"profiles/{sys.argv[2]}.json")
        if p.exists():
            profile = json.loads(p.read_text(encoding="utf-8"))
    style = extract_site_style(site, profile)
    print(json.dumps(style, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
