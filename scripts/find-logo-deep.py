"""Deeper logo hunt — look at top-of-page images + SVGs, not just header.
Print everything visible in the first 200px of viewport."""
from playwright.sync_api import sync_playwright

TARGETS = {
    "aureon":         "https://aureonglobal.de",
    "algoalpha":      "https://algoalpha.io",
    "lk-advertising": "https://lk-advertising.com",
}

JS = r"""
() => {
  // Every img + svg in the top portion of the page (likely brand position)
  const all = [];
  for (const el of document.querySelectorAll('img, svg')) {
    const r = el.getBoundingClientRect();
    if (r.top > 200) continue;          // skip below-the-fold
    if (r.width < 16 || r.height < 16) continue;  // skip tiny tracking pixels
    if (el.tagName === 'IMG') {
      all.push({ tag: 'img', src: el.src, alt: el.alt || '',
                  w: el.naturalWidth || r.width, h: el.naturalHeight || r.height,
                  top: Math.round(r.top), left: Math.round(r.left) });
    } else {
      // SVG: serialize the first 200 chars so we can see what it is
      const xml = new XMLSerializer().serializeToString(el);
      all.push({ tag: 'svg', preview: xml.slice(0, 200),
                  w: r.width, h: r.height,
                  top: Math.round(r.top), left: Math.round(r.left) });
    }
  }
  return all;
}
"""

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
            page.wait_for_timeout(2000)
            results = page.evaluate(JS)
            if not results:
                print("   (no images/svg in top 200px)")
            for r in results:
                if r["tag"] == "img":
                    print(f"   IMG  top={r['top']:4d} left={r['left']:4d}  "
                          f"{r['w']}x{r['h']}  alt='{r['alt'][:30]}'")
                    print(f"        src={r['src']}")
                else:
                    print(f"   SVG  top={r['top']:4d} left={r['left']:4d}  "
                          f"{r['w']:.0f}x{r['h']:.0f}")
                    print(f"        preview={r['preview']}")
        except Exception as e:
            print(f"   FAILED: {e}")
        print()
    ctx.close(); b.close()
