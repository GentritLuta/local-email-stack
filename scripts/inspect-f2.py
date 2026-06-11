"""Inspect f2-malergipser.ch — screenshot + extract structural CSS for
designing a custom email template that mirrors the actual website style."""
from playwright.sync_api import sync_playwright
from pathlib import Path
import json

OUT = Path(__file__).resolve().parent.parent / "previews" / "f2-inspect"
OUT.mkdir(parents=True, exist_ok=True)

JS = r"""
() => {
  const cs = el => el ? window.getComputedStyle(el) : null;
  const body = document.body;

  // Hero block — first big section
  const h1 = document.querySelector('h1');
  const heroSection = h1 ? h1.closest('section, header, div[class*="hero"], main') : null;

  // Look for the FIRST big visible button / CTA
  const buttonSel = 'button, a.btn, a.button, .btn, .button, [role="button"], [class*="cta"]';
  const btn = Array.from(document.querySelectorAll(buttonSel))
    .filter(el => el.offsetWidth > 80 && el.offsetHeight > 30)[0];

  // Look for a "Kontakt" or "Contact" section/card
  const contactNode = Array.from(document.querySelectorAll('section, footer, div'))
    .find(el => /kontakt|contact|impressum/i.test(el.textContent || '') &&
                 el.offsetWidth > 200 && el.offsetWidth < 1400 && el.offsetHeight < 1200);

  // Pull all heading sizes
  const headings = {};
  for (const tag of ['h1','h2','h3','h4']) {
    const el = document.querySelector(tag);
    if (el) {
      const s = cs(el);
      headings[tag] = {
        fontSize: s.fontSize, fontWeight: s.fontWeight, color: s.color,
        fontFamily: s.fontFamily, lineHeight: s.lineHeight, text: el.innerText.slice(0,120)
      };
    }
  }

  // Pull section spacing
  const sections = Array.from(document.querySelectorAll('section')).slice(0,3).map(s => {
    const x = cs(s);
    return { padding: x.padding, background: x.backgroundColor };
  });

  return {
    body: {
      color: cs(body).color, bg: cs(body).backgroundColor,
      fontFamily: cs(body).fontFamily, fontSize: cs(body).fontSize,
    },
    h1_text: h1 ? h1.innerText.slice(0,200) : null,
    headings: headings,
    button: btn ? {
      bg: cs(btn).backgroundColor, color: cs(btn).color,
      borderRadius: cs(btn).borderRadius, padding: cs(btn).padding,
      fontSize: cs(btn).fontSize, fontWeight: cs(btn).fontWeight,
      text: btn.innerText.slice(0,60)
    } : null,
    sections: sections,
    contact_block: contactNode ? contactNode.innerText.slice(0, 800) : null,
    page_text_sample: body.innerText.slice(0, 1500),
  };
}
"""

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900},
                         device_scale_factor=1,
                         user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                                      "Chrome/125.0.0.0 Safari/537.36"))
    page = ctx.new_page()
    page.goto("https://f2-malergipser.ch", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(2000)

    # Screenshot — full page so we see the design language
    page.screenshot(path=str(OUT / "f2-fullpage.png"), full_page=True)
    print(f"wrote {OUT / 'f2-fullpage.png'}")

    # Also screenshot just the viewport (top hero)
    page.screenshot(path=str(OUT / "f2-hero.png"), full_page=False)
    print(f"wrote {OUT / 'f2-hero.png'}")

    # Extract structural data
    data = page.evaluate(JS)
    (OUT / "f2-css.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT / 'f2-css.json'}")

    ctx.close(); b.close()
