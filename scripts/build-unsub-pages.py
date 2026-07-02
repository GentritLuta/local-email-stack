#!/usr/bin/env python3
"""Generate the GitHub-Pages unsubscribe page for any/every client from its
profile brand+legal. STANDARD: every client gets a working unsub page that
matches the brand, calls the RLS-safe unsubscribe_by_token RPC, and never 404s.

The page filename is derived from the profile's brand.unsubscribe_url_template
(the .../unsubscribe/<file>.html part), so the generated file always matches the
URL the emails actually link to.

Usage:
  py scripts/build-unsub-pages.py            # all profiles
  py scripts/build-unsub-pages.py mark-eting # one profile
"""
import json
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent))
from site_style import extract_site_style  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = (h or "#000000").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return 0, 0, 0


def _rgb_hex(r: int, g: int, b: int) -> str:
    return "#%02x%02x%02x" % (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def _lighten(hexc: str, amt: float) -> str:
    """Move a color toward white (amt 0..1). For light bgs this nudges toward
    a subtle card; for dark bgs it lifts the card above the page."""
    r, g, b = _hex_rgb(hexc)
    # If the base is light, darken slightly instead so the card stays distinct.
    if (0.2126 * r + 0.7152 * g + 0.0722 * b) > 180:
        return _rgb_hex(int(r * (1 - amt)), int(g * (1 - amt)), int(b * (1 - amt)))
    return _rgb_hex(int(r + (255 - r) * amt), int(g + (255 - g) * amt), int(b + (255 - b) * amt))


def _mix(a: str, b: str, t: float) -> str:
    ar, ag, ab = _hex_rgb(a); br, bg_, bb = _hex_rgb(b)
    return _rgb_hex(int(ar + (br - ar) * t), int(ag + (bg_ - ag) * t), int(ab + (bb - ab) * t))


def _rgba(hexc: str, a: float) -> str:
    r, g, b = _hex_rgb(hexc)
    return f"rgba({r},{g},{b},{a})"
# GitHub Pages serves this repo from the ROOT, so the live
# /unsubscribe/<slug>.html URLs resolve to the root unsubscribe/ dir — NOT
# docs/unsubscribe/. Write there so the generated pages actually go live.
OUT_DIR = REPO / "unsubscribe"

SUPABASE_URL = "https://zmzolkijhiaedzcmdfji.supabase.co"
SUPABASE_ANON = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inptem9sa2lqaGlhZWR6Y21kZmppIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI4OTkyOTgsImV4cCI6MjA5ODQ3NTI5OH0.xedlcfQT4DR7wxZDcblQB03s4q5f4k2JlbnPqo9EwiM"


def esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def page_filename(brand: dict, slug: str) -> str:
    tpl = brand.get("unsubscribe_url_template", "")
    if "/unsubscribe/" in tpl:
        return tpl.split("/unsubscribe/")[-1].split("?")[0]
    return f"{slug}.html"


def find_logo(brand: dict) -> str | None:
    """STANDARD: always look for the client's brand logo FIRST, in priority
    order, and return the first URL that actually loads as an image. Falls back
    to None (caller renders the wordmark) so a dead logo URL never ships a broken
    image. Checked: legal.logo_url -> brand.logo_url -> brand.logo."""
    legal = brand.get("legal", {})
    candidates = [legal.get("logo_url"), brand.get("logo_url"), brand.get("logo")]
    for url in candidates:
        if not url or not str(url).startswith("http"):
            continue
        try:
            import httpx
            r = httpx.head(url, follow_redirects=True, timeout=10)
            ct = r.headers.get("content-type", "")
            if r.status_code == 200 and ct.startswith("image"):
                return url
            # Some CDNs reject HEAD — confirm with a tiny ranged GET.
            r = httpx.get(url, follow_redirects=True, timeout=10,
                          headers={"Range": "bytes=0-0"})
            if r.status_code in (200, 206) and r.headers.get("content-type", "").startswith("image"):
                return url
        except Exception:
            continue
    return None


def render(slug: str, profile: dict) -> str:
    brand = profile.get("brand", {})
    legal = brand.get("legal", {})
    wordmark = esc(brand.get("wordmark") or profile.get("company", {}).get("name") or slug)
    tagline = esc(brand.get("tagline") or "")
    company = esc(legal.get("company_name") or brand.get("wordmark") or slug)
    addr = esc(", ".join(legal.get("address_lines", [])[1:]) or legal.get("address_lines", [""])[0] if legal.get("address_lines") else "")
    contact = esc(legal.get("contact_email") or "")
    site = brand.get("site") or profile.get("company", {}).get("site") or ""
    site_url = site if site.startswith("http") else f"https://{site}"
    year = legal.get("copyright_year", 2026)

    # STANDARD: pull the client's REAL site style (logo, font, colors) from the
    # live website, falling back to the profile brand. Same look as their site.
    style = extract_site_style(site_url, profile)
    accent = style["accent"]
    bg = style["bg"]
    text = style["text"]
    font = style["font_stack"]
    font_url = style.get("font_url")
    logo_url = style.get("logo_url")

    def _lum(h):
        r, g, b = _hex_rgb(h)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    # Accent contrast guard: if the accent is too close to the page bg in
    # luminance (e.g. a near-black accent on a dark site -> wordmark+button
    # vanish), fall back to the profile's accent_2, then to text color.
    pcolors = brand.get("colors", {})
    if abs(_lum(accent) - _lum(bg)) < 60:
        alt = pcolors.get("accent_2")
        if alt and abs(_lum(alt) - _lum(bg)) >= 60:
            accent = alt
        else:
            accent = text  # last resort: readable wordmark/button

    bg_is_light = _lum(bg) > 150
    card_bg = _lighten(bg, 0.06)   # card sits just above the page bg
    border = _mix(_lighten(bg, 0.12), accent, 0.18)  # accent-tinted border
    muted = _mix(text, bg, 0.45)
    mix_text = _mix(text, bg, 0.18)  # body copy, slightly softened from pure text
    # Button label: dark on a light accent, light on a dark accent (contrast).
    btn_text = "#0a0a0a" if _lum(accent) > 150 else "#ffffff"
    btn_hover = _lighten(accent, 0.12) if not bg_is_light else _mix(accent, "#000000", 0.12)

    # CUSTOM-PER-CLIENT, STANDARDIZED: the page background is a soft radial wash
    # of the brand accent over the brand bg, so each client's page feels distinct
    # but every page is built from the same formula. Card carries a faint accent
    # tint + an accent glow behind it.
    page_bg = (f"radial-gradient(1100px 620px at 50% -8%, {_rgba(accent, 0.16)} 0%, "
               f"{_rgba(accent, 0.0)} 60%), {bg}")
    card_tint = _mix(card_bg, accent, 0.05)        # card surface gets a whisper of accent
    glow = _rgba(accent, 0.22 if not bg_is_light else 0.16)
    font_link = (f'<link rel="preconnect" href="https://fonts.googleapis.com">'
                 f'<link href="{esc(font_url)}" rel="stylesheet">') if font_url else ""

    # Logo backing: some logos have dark text that disappears on a dark page bg
    # (e.g. Diraya). Opt-in per profile via brand.logo_needs_backing=true so the
    # already-good light/colorful logos (algoalpha, lk, mark-eting...) stay clean.
    logo_chip = ("background:#ffffff;padding:10px 12px;border-radius:6px;display:inline-block;"
                 if brand.get("logo_needs_backing") and _lum(bg) < 90 else "")

    logo_width = legal.get("logo_width") or brand.get("logo_width") or 150
    if logo_url:
        header_html = (f'<img class="logo" src="{esc(logo_url)}" alt="{wordmark}" '
                       f'style="max-width:{int(logo_width)}px;height:auto;display:block;'
                       f'margin-bottom:4px;{logo_chip}">')
    else:
        header_html = f'<div class="wordmark">{wordmark}</div>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>Unsubscribe · {wordmark}</title>
{font_link}
<style>
  *, *::before, *::after {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: {bg}; min-height: 100vh; }}
  body {{ font-family: {font}; color: {text}; padding: 40px 18px;
         display: grid; place-items: center; background: {page_bg}; background-attachment: fixed; }}
  .card {{ position: relative; width: 100%; max-width: 540px; background: {card_tint};
          border: 1px solid {border}; border-radius: 22px; overflow: hidden;
          box-shadow: 0 24px 70px {glow}, 0 2px 8px rgba(0,0,0,.18); }}
  .accent-rule {{ height: 4px; background: linear-gradient(90deg, {accent}, {_rgba(accent,0.35)}); }}
  .body {{ padding: 40px 38px 30px; }}
  .logo {{ max-width: 170px; height: auto; border-radius: 10px; }}
  .wordmark {{ font-size: 21px; font-weight: 700; color: {accent}; letter-spacing: .3px; }}
  .tagline {{ font-size: 12px; color: {muted}; margin-top: 8px; text-transform: uppercase; letter-spacing: 1.5px; }}
  h1 {{ font-size: 25px; font-weight: 700; margin: 28px 0 12px; color: {text}; letter-spacing: -.2px; }}
  p {{ font-size: 15px; line-height: 1.7; margin: 0 0 14px; color: {mix_text}; }}
  .btn {{ display: inline-block; margin-top: 16px; padding: 15px 30px; background: {accent};
         color: {btn_text}; font-size: 14.5px; font-weight: 700; border: none; border-radius: 14px;
         cursor: pointer; letter-spacing: .3px; transition: background .15s ease, transform .1s ease;
         box-shadow: 0 8px 22px {_rgba(accent,0.3)}; }}
  .btn:hover {{ background: {btn_hover}; transform: translateY(-1px); }}
  .btn:disabled {{ opacity: .5; cursor: not-allowed; box-shadow: none; }}
  .success {{ display: none; margin-top: 18px; padding: 15px 18px; background: {_rgba(accent,0.1)};
             border: 1px solid {_rgba(accent,0.4)}; font-size: 14px; line-height: 1.5; color: {accent}; border-radius: 14px; }}
  .err {{ display: none; margin-top: 18px; padding: 15px 18px; background: rgba(220,38,38,.1);
         border: 1px solid rgba(220,38,38,.4); font-size: 13.5px; line-height: 1.5; color: #fca5a5; border-radius: 14px; }}
  .footer {{ padding: 22px 38px 30px; border-top: 1px solid {border}; font-size: 12px; color: {muted}; line-height: 1.7; }}
  .footer a {{ color: {accent}; text-decoration: none; }}
</style>
</head>
<body>
  <div class="card">
    <div class="accent-rule"></div>
    <div class="body">
      {header_html}
      <div class="tagline">{tagline}</div>
      <h1>Unsubscribe from {wordmark}</h1>
      <p id="lead">Click below and we will remove your address from every {wordmark}
        campaign. No follow-up, no second attempt.</p>
      <button class="btn" id="btn" type="button">Confirm unsubscribe</button>
      <div class="success" id="success-state">
        <b><span id="email">Your address</span></b> has been unsubscribed. You will not hear from us again.
      </div>
      <div class="err" id="error-state"></div>
    </div>
    <div class="footer">
      {company}{(' · ' + addr) if addr else ''}<br>
      <a href="mailto:{contact}">{contact}</a> &nbsp;·&nbsp; <a href="{esc(site_url)}">{esc(site)}</a><br>
      © {year} {company}
    </div>
  </div>
<script>
const SUPABASE_URL  = "{SUPABASE_URL}";
const SUPABASE_ANON = "{SUPABASE_ANON}";
const token = new URLSearchParams(location.search).get("t") || "";
const btn = document.getElementById("btn");
const lead = document.getElementById("lead");
const successWrap = document.getElementById("success-state");
const errorWrap = document.getElementById("error-state");
function showSuccess() {{ successWrap.style.display="block"; btn.style.display="none"; lead.style.display="none"; }}
function showError(m) {{ errorWrap.textContent=m; errorWrap.style.display="block"; btn.disabled=false; }}
async function doUnsub() {{
  btn.disabled = true;
  try {{
    const r = await fetch(`${{SUPABASE_URL}}/rest/v1/rpc/unsubscribe_by_token`, {{
      method:"POST",
      headers:{{ apikey:SUPABASE_ANON, Authorization:"Bearer "+SUPABASE_ANON, "Content-Type":"application/json" }},
      body: JSON.stringify({{ p_token: token }})
    }});
    if (!r.ok) throw new Error("HTTP "+r.status);
    showSuccess();
  }} catch (e) {{ showError("Something went wrong: "+e.message); }}
}}
if (!token) {{ showError("This link is incomplete. Please use the link from the email."); btn.disabled = true; }}
btn.addEventListener("click", doUnsub);
</script>
</body>
</html>
"""


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    profiles = []
    for f in sorted((REPO / "profiles").glob("*.json")):
        if f.name.endswith(".private.json"):
            continue
        slug = f.stem
        if only and slug != only:
            continue
        try:
            profiles.append((slug, json.loads(f.read_text(encoding="utf-8"))))
        except Exception as e:
            print(f"  ! {slug}: load error {e}")
    written = 0
    for slug, prof in profiles:
        fn = page_filename(prof.get("brand", {}), slug)
        (OUT_DIR / fn).write_text(render(slug, prof), encoding="utf-8")
        print(f"  wrote {OUT_DIR.name}/{fn}  ({slug}, logo={'yes' if find_logo(prof.get('brand', {})) else 'wordmark'})")
        written += 1
    print(f"\n{written} unsubscribe page(s) generated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
