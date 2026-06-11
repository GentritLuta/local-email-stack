"""Find the header logo URL on each client landing page via playwright."""
import sys

TARGETS = {
    "aureon":         "https://aureonglobal.de",
    "algoalpha":      "https://algoalpha.io",
    "f2-malergipser": "https://f2-malergipser.ch",
    "lk-advertising": "https://lk-advertising.com",
}

JS = r"""
() => {
  // Look for img inside header / nav / .logo / [class*="Logo"]
  const sels = [
    'header img', 'nav img',
    'img.logo', 'img[class*="logo"]', 'img[class*="Logo"]',
    '[class*="header"] img', '[class*="Header"] img',
    '[class*="navbar"] img', '[class*="Nav"] img',
    'a[href="/"] img', 'a[href="/"] svg',
  ];
  const found = [];
  for (const s of sels) {
    document.querySelectorAll(s).forEach(el => {
      if (el.tagName === 'IMG' && el.src) {
        found.push({sel: s, src: el.src, alt: el.alt, w: el.naturalWidth, h: el.naturalHeight});
      } else if (el.tagName === 'SVG') {
        found.push({sel: s, src: '(inline SVG)', viewBox: el.getAttribute('viewBox')});
      }
    });
  }
  // Dedupe by src
  const seen = new Set();
  return found.filter(x => { if (seen.has(x.src)) return false; seen.add(x.src); return true; });
}
"""

from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1280, "height": 900},
                         user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                                      "Chrome/125.0.0.0 Safari/537.36"))
    page = ctx.new_page()
    for slug, url in TARGETS.items():
        print(f"=== {slug} ({url})")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(1500)
            found = page.evaluate(JS)
            for f in found:
                src = f.get('src','')
                if src.startswith('data:'):
                    src = '(data URI)'
                print(f"   sel={f.get('sel'):28s}  src={src}  size={f.get('w','?')}x{f.get('h','?')}")
            if not found:
                print(f"   (no logo elements found)")
        except Exception as e:
            print(f"   FAILED: {e}")
        print()
    ctx.close(); b.close()
