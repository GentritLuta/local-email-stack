"""extract-brand-css.py — open each client landing page in headless
Chromium, read computed CSS for the visually-load-bearing elements
(body, h1, primary button), and report a structured color + font palette
for the operator to either review or auto-apply to each profile's
brand block.

Outputs:
  1. Per-URL: {url, body_color, body_bg, body_font, h1_color, h1_font,
     primary_button_bg, accent_candidates: [hex,...], status}
  2. JSON file: previews/brand-css-extract.json

Usage:
    py scripts/extract-brand-css.py
    py scripts/extract-brand-css.py --apply    # also writes into profile brand blocks
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from collections import Counter

REPO = Path(__file__).resolve().parent.parent
PROFILES = REPO / "profiles"
PUBLIC = REPO / "desktop" / "frontend" / "public" / "profiles"
OUT = REPO / "previews" / "brand-css-extract.json"


TARGETS = {
    "aureon":         "https://aureonglobal.de",
    "algoalpha":      "https://algoalpha.io",
    "lk-advertising": "https://lk-advertising.com",
}


def rgb_to_hex(rgb: str) -> str | None:
    """rgb(214, 178, 89) → #d6b259 ; rgba(...) with a<1 → None (skip transparent)."""
    if not rgb or rgb in ("transparent", "rgba(0, 0, 0, 0)"):
        return None
    m = re.match(r"rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)", rgb)
    if not m:
        return None
    r, g, b = int(m.group(1)), int(m.group(2)), int(m.group(3))
    a = float(m.group(4)) if m.group(4) else 1.0
    if a < 0.5:
        return None  # too transparent to be a brand color
    return f"#{r:02x}{g:02x}{b:02x}"


def is_neutral(hex_color: str) -> bool:
    """White / black / gray family — not a brand color."""
    if not hex_color or not hex_color.startswith("#"):
        return True
    h = hex_color.lstrip("#").lower()
    if len(h) != 6:
        return True
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    # Black-ish
    if max(r, g, b) < 40:
        return True
    # White-ish
    if min(r, g, b) > 235:
        return True
    # Gray-ish (R/G/B within ~10 of each other)
    spread = max(r, g, b) - min(r, g, b)
    if spread < 15:
        return True
    return False


# JS to inject — collects computed styles from key elements + ranks
# all elements' background colors to find the brand accent.
EXTRACTION_JS = r"""
() => {
  const cs = el => el ? window.getComputedStyle(el) : null;
  const body = document.body;
  const h1 = document.querySelector('h1');

  // Find buttons-like elements that look clickable + accent-colored
  const buttonSel = 'button, a.btn, a.button, .btn, .button, [role="button"], [class*="cta"], [class*="Cta"], [class*="CTA"]';
  const buttons = Array.from(document.querySelectorAll(buttonSel))
    .filter(el => el.offsetWidth > 30 && el.offsetHeight > 20)
    .slice(0, 10);
  const buttonBgs = buttons.map(b => cs(b).backgroundColor).filter(c => c);

  // Sample all visible elements for accent color frequency analysis
  // (background colors — body content blocks)
  const accentSample = [];
  document.querySelectorAll('a, button, [class*="primary"], [class*="accent"], [class*="brand"], [style*="background"]')
    .forEach(el => {
      const s = cs(el);
      if (s) {
        accentSample.push(s.backgroundColor);
        accentSample.push(s.color);
        accentSample.push(s.borderColor);
      }
    });

  return {
    body: body ? {
      color: cs(body).color,
      backgroundColor: cs(body).backgroundColor,
      fontFamily: cs(body).fontFamily,
    } : null,
    h1: h1 ? {
      color: cs(h1).color,
      fontFamily: cs(h1).fontFamily,
      backgroundColor: cs(h1).backgroundColor,
    } : null,
    buttons: buttonBgs,
    accentSample: accentSample,
    title: document.title,
    h1Text: h1 ? h1.innerText.trim().slice(0, 200) : null,
  };
}
"""


def rank_accents(samples: list[str]) -> list[tuple[str, int]]:
    """Convert raw CSS colors to hex, drop neutrals, return Counter ranked
    by frequency (most common first). Brand colors typically appear on
    buttons, links, and accent strips."""
    hexes = []
    for c in samples:
        h = rgb_to_hex(c)
        if h and not is_neutral(h):
            hexes.append(h)
    return Counter(hexes).most_common(8)


def extract_one(page, url: str) -> dict:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=20000)
        # Let JS rehydrate
        page.wait_for_timeout(1500)
        raw = page.evaluate(EXTRACTION_JS)
    except Exception as e:
        return {"url": url, "ok": False, "error": str(e)}

    body = raw.get("body") or {}
    h1 = raw.get("h1") or {}
    body_color = rgb_to_hex(body.get("color"))
    body_bg = rgb_to_hex(body.get("backgroundColor")) or "#ffffff"
    h1_color = rgb_to_hex(h1.get("color"))
    h1_font = (h1.get("fontFamily") or "").strip()
    body_font = (body.get("fontFamily") or "").strip()
    # Rank button backgrounds (often the cleanest brand accent)
    button_hexes = [rgb_to_hex(c) for c in raw.get("buttons", [])]
    button_hexes = [h for h in button_hexes if h and not is_neutral(h)]
    button_top = Counter(button_hexes).most_common(3)
    # Page-wide accent sample
    accent_top = rank_accents(raw.get("accentSample", []))
    return {
        "url": url,
        "ok": True,
        "title": raw.get("title"),
        "h1_text": raw.get("h1Text"),
        "body_color":   body_color or "#0a0a0a",
        "body_bg":      body_bg,
        "body_font":    body_font,
        "h1_color":     h1_color,
        "h1_font":      h1_font,
        "primary_button_top": [{"hex": h, "count": n} for h, n in button_top],
        "accent_candidates": [{"hex": h, "count": n} for h, n in accent_top],
    }


def _brightness(hex_color: str) -> int:
    """0-255 perceived brightness of a hex color. White=~255, black=0."""
    h = (hex_color or "").lstrip("#")
    if len(h) != 6:
        return 128
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return int(0.299*r + 0.587*g + 0.114*b)


def derive_brand_colors(rec: dict) -> dict:
    """Distill the extracted observations into the 8-color brand block
    used by email_render.py.

    Adopt accent colors from the site. Do NOT adopt site text/bg colors
    when the site is dark-themed — that white-on-dark scheme would render
    as invisible white-on-white text in a light-themed email card. Cold
    outreach goes into mostly-light inboxes; the email body stays light
    regardless of how the website looks.
    """
    accent = None
    if rec.get("primary_button_top"):
        accent = rec["primary_button_top"][0]["hex"]
    if not accent and rec.get("accent_candidates"):
        accent = rec["accent_candidates"][0]["hex"]
    accent = accent or "#0a0a0a"

    accent_2 = None
    if rec.get("accent_candidates") and len(rec["accent_candidates"]) > 1:
        for cand in rec["accent_candidates"][1:]:
            if cand["hex"] != accent:
                accent_2 = cand["hex"]
                break
    accent_2 = accent_2 or accent

    # Detect dark-themed site (light text on dark bg). When dark, ignore
    # site text/bg entirely — use email-safe defaults so the body stays
    # readable on the (light) email card.
    site_text = rec.get("body_color") or ""
    site_bg = rec.get("body_bg") or ""
    site_is_dark = (_brightness(site_text) > 200 and _brightness(site_bg) < 60)

    if site_is_dark:
        text = "#0a0a0a"      # near-black on light email card
        bg_page = "#fafafa"   # pale slate, slightly off-white
    else:
        # Light-themed site: safe to inherit its text + bg
        text = site_text or "#0a0a0a"
        bg_page = site_bg or "#fafafa"
        # Guard against pure-white text or pure-black bg leaking through
        if _brightness(text) > 235:
            text = "#0a0a0a"
        if _brightness(bg_page) < 40:
            bg_page = "#fafafa"

    return {
        "accent":   accent,
        "accent_2": accent_2,
        "text":     text,
        "text_2":   "#475569",
        "muted":    "#94a3b8",
        "bg_page":  bg_page,
        "bg_card":  "#ffffff",
        "rule":     "#e5e7eb",
    }


def derive_brand_font(rec: dict, current_font: str) -> str:
    """Prefer the site's body font when it's a real CSS stack."""
    raw = (rec.get("body_font") or rec.get("h1_font") or "").strip()
    if not raw:
        return current_font
    # If first family is generic ("sans-serif" alone), keep current
    head = raw.split(",")[0].strip().strip("\"'").lower()
    if head in ("sans-serif", "serif", "monospace", "system-ui", ""):
        return current_font
    return raw


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="Write extracted palette into each profile's brand block")
    args = ap.parse_args()

    from playwright.sync_api import sync_playwright

    results = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(viewport={"width": 1280, "height": 900},
                                   user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                                "AppleWebKit/537.36 (KHTML, like Gecko) "
                                                "Chrome/125.0.0.0 Safari/537.36"))
        page = ctx.new_page()
        for slug, url in TARGETS.items():
            print(f"=== {slug:18s}  {url}")
            rec = extract_one(page, url)
            if rec.get("ok"):
                print(f"   title:   {rec.get('title','')[:70]}")
                print(f"   h1:      {(rec.get('h1_text') or '')[:80]}")
                print(f"   body fg/bg: {rec.get('body_color')} on {rec.get('body_bg')}")
                print(f"   font:    {(rec.get('body_font') or '')[:60]}")
                print(f"   buttons: {[(b['hex'], b['count']) for b in rec.get('primary_button_top', [])]}")
                print(f"   accents: {[(b['hex'], b['count']) for b in rec.get('accent_candidates', [])]}")
                brand = derive_brand_colors(rec)
                print(f"   -> accent={brand['accent']}  accent_2={brand['accent_2']}")
            else:
                print(f"   FAILED:  {rec.get('error','?')}")
            print()
            results[slug] = rec
        ctx.close(); browser.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}")

    if args.apply:
        print("\n=== applying to profile brand blocks ===")
        for slug, rec in results.items():
            if not rec.get("ok"):
                print(f"  ! skip {slug}: extraction failed")
                continue
            # Skip Hostinger-parked-domain pages: title contains "nicht gefunden",
            # "not found", or "this domain is for sale". Their colors are useless.
            title_l = (rec.get("title") or "").lower()
            if any(k in title_l for k in ("nicht gefunden", "not found",
                                            "domain is for sale", "godaddy",
                                            "parked")):
                print(f"  ! skip {slug}: site is a parked/404 placeholder "
                      f"(title={rec.get('title','')[:50]!r})")
                continue
            pf = PROFILES / f"{slug}.json"
            if not pf.exists():
                continue
            data = json.loads(pf.read_text(encoding="utf-8"))
            current_font = data.get("brand", {}).get("font_stack", "")
            new_colors = derive_brand_colors(rec)
            new_font = derive_brand_font(rec, current_font)
            data.setdefault("brand", {})["colors"] = {
                **data["brand"].get("colors", {}),
                **new_colors,
            }
            data["brand"]["font_stack"] = new_font
            pf.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                          encoding="utf-8")
            pub = PUBLIC / f"{slug}.json"
            if pub.exists():
                pub.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                               encoding="utf-8")
            print(f"  + {slug:18s} accent={new_colors['accent']}  accent_2={new_colors['accent_2']}  font={new_font[:50]}...")

    return 0


if __name__ == "__main__":
    sys.exit(main())
