import asyncio, json
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width":1440,"height":1200})
        await pg.goto("https://diraya.ca", wait_until="networkidle", timeout=60000)
        await pg.wait_for_timeout(2500)
        # screenshot full page for design reference
        await pg.screenshot(path="out/diraya_full.png", full_page=True)
        await pg.screenshot(path="out/diraya_hero.png", full_page=False)
        data = await pg.evaluate(r"""() => {
          const cs = getComputedStyle(document.body);
          const pick = el => { if(!el) return null; const s=getComputedStyle(el);
            return {bg:s.backgroundColor,color:s.color,ff:s.fontFamily,fs:s.fontSize,fw:s.fontWeight,br:s.borderRadius,pad:s.padding,ls:s.letterSpacing,tt:s.textTransform}; };
          // gather buttons / links that look like CTAs
          const ctas = [...document.querySelectorAll('a,button')].filter(e=>{
            const t=(e.textContent||'').toLowerCase();
            return /schedule|contact|meeting|get|start|book|let|talk/.test(t) && e.offsetHeight>10;
          }).slice(0,6).map(e=>({txt:e.textContent.trim().slice(0,40),...pick(e)}));
          const headings=[...document.querySelectorAll('h1,h2,h3')].slice(0,6).map(h=>({tag:h.tagName,txt:h.textContent.trim().slice(0,50),...pick(h)}));
          // collect all distinct background colors used on large blocks
          const blocks=[...document.querySelectorAll('section,div,header,footer')].filter(e=>e.offsetHeight>120&&e.offsetWidth>300);
          const bgcount={};
          blocks.forEach(e=>{const c=getComputedStyle(e).backgroundColor; if(c&&c!=='rgba(0, 0, 0, 0)') bgcount[c]=(bgcount[c]||0)+1;});
          // font links
          const fonts=[...document.querySelectorAll('link[rel=stylesheet],link[href*=font]')].map(l=>l.href).filter(h=>/font/i.test(h));
          return {body:pick(document.body), ctas, headings, bgcount, fonts, title:document.title};
        }""")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        await b.close()

asyncio.run(main())
