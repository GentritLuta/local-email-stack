"""Custom email template for LK Advertising.

Rebuilt 2026-06-12 to match the REAL live brand at https://lk-advertising.com
(the .site domain does not exist and was sending-only):
  - DARK NAVY theme (#0a1b2b page, #0d2236 card) pulled straight from the site's
    --color-bg tokens
  - The REAL logo: the white serif "LK / ADVERTISING" monogram, hotlinked from the
    site's own CDN (onecdn) the same way aureon/diraya hotlink their domain logo
  - Elegant serif display (Cormorant/Playfair stack) for the brand mark area to
    echo the upscale serif logo; Inter for body for readability
  - ALL links point to https://lk-advertising.com (NOT .site)
  - Gold-ish warm accent for the CTA so it reads against the navy

Copy (the 7-email US real-estate sequence) is unchanged. No em dashes anywhere
(hard rule). Colors still read from brand.colors when present so the profile can
override; PAL is the fallback that matches the live site.
"""
from __future__ import annotations
import html as _html
from typing import Optional

# Real lk-advertising.com palette (from the site's --color-bg / --color-text tokens).
PAL = {
    "page":   "#0a1b2b",   # deep navy page bg (site --color-bg 10,27,43)
    "card":   "#0d2236",   # slightly lifted navy card
    "ink":    "#ffffff",   # white headings (logo is white serif on navy)
    "text":   "#e7edf3",   # near-white body
    "text_2": "#aebccb",   # muted slate-blue
    "accent": "#c9a25a",   # warm gold accent (CTA / rules), reads on navy
    "rule":   "#1d344c",   # navy rule tint
    "border": "#1c3a55",   # navy card border
    "muted":  "#7f93a6",
}

SERIF = ("'Cormorant Garamond', 'Playfair Display', Georgia, 'Times New Roman', serif")
FONT = ("'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
        "'Helvetica Neue', Arial, sans-serif")
BOOKING_URL = "https://lk-advertising.com"
SITE = "lk-advertising.com"
SITE_URL = "https://lk-advertising.com"
# The real white serif "LK / ADVERTISING" logo, hosted on the site's CDN.
# Solidified, content-cropped LK logo. The original onecdn asset anti-aliased to
# ~50% opacity at the small email size and read as "almost transparent"; this one
# is opaque white on transparent (see out/lk-logo-fixed.png), hosted on our own box.
LOGO_URL = "https://aureonglobal.de/assets/lk-logo.png"


def _pal(brand: dict) -> dict:
    """Merge any profile brand.colors over the navy fallback. The profile may not
    carry navy tokens yet, so PAL (the live-site navy) is the default."""
    c = (brand or {}).get("colors") or {}
    return {
        "page":   c.get("bg_page", PAL["page"]),
        "card":   c.get("bg_card", PAL["card"]),
        "ink":    c.get("heading", PAL["ink"]),
        "text":   c.get("text", PAL["text"]),
        "text_2": c.get("text_2", PAL["text_2"]),
        "accent": c.get("accent", PAL["accent"]),
        "rule":   PAL["rule"],
        "border": PAL["border"],
        "muted":  c.get("muted", PAL["muted"]),
    }


def _esc(s: str) -> str:
    return _html.escape(s, quote=True) if s else ""


def _body_html(body: str, pal: dict) -> str:
    paragraphs = [p for p in body.strip().split("\n\n") if p.strip()]
    out = []
    for para in paragraphs:
        lines = [l for l in para.split("\n") if l.strip()]
        is_bullets = len(lines) >= 2 and all(
            l.strip().startswith("* ") or l.strip().startswith("- ") for l in lines
        )
        if is_bullets:
            bullet_html = ""
            for line in lines:
                stripped = line.strip()
                content = stripped[2:].strip() if stripped[:2] in ("* ", "- ") else stripped
                bullet_html += (
                    f'<tr><td valign="top" style="padding:6px 0;font-family:{FONT};'
                    f'font-size:15px;line-height:1.6;color:{pal["text"]};">'
                    f'<span style="display:inline-block;width:22px;color:{pal["accent"]};'
                    f'font-weight:800;font-size:16px;">+</span>'
                    f'<span>{_esc(content)}</span>'
                    f'</td></tr>'
                )
            out.append(
                f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
                f'style="margin:8px 0 16px 0;"><tbody>{bullet_html}</tbody></table>'
            )
        else:
            escaped = _esc(para).replace("\n", "<br>")
            out.append(
                f'<p style="margin:0 0 16px 0;font-family:{FONT};font-size:15px;'
                f'line-height:1.7;color:{pal["text"]};">{escaped}</p>'
            )
    return "".join(out)


def render_html_lk(*, body: str, persona: dict,
                   unsubscribe_token: Optional[str] = None,
                   brand: Optional[dict] = None,
                   step_n: int = 1) -> str:
    brand = brand or {}
    legal = brand.get("legal") or {}
    pal = _pal(brand)
    body_html = _body_html(body, pal)

    sig_raw = (persona.get("signature") or persona.get("from_name", ""))
    sig_lines = [_esc(l.strip()) for l in sig_raw.split("\n") if l.strip()]
    sig_name = sig_lines[0] if sig_lines else _esc(persona.get("from_name", ""))
    sig_title_lines = sig_lines[1:]

    tagline = _esc(brand.get("tagline",
                   "More listing appointments for real estate agents, performance based"))

    tpl = brand.get("unsubscribe_url_template",
                    "https://gentritluta.github.io/local-email-stack/unsubscribe/lk-advertising.html?t={token}")
    unsub_url = tpl.replace("{token}", unsubscribe_token or "preview")

    contact_email = _esc(legal.get("contact_email", "info@lk-advertising.com"))
    addr = "<br>".join(_esc(l) for l in (legal.get("address_lines") or []))
    year = str(legal.get("copyright_year") or 2026)

    # CTA only on persuasion steps (2 to 5); step 1 opens, 6 and 7 are value/breakup.
    show_cta = step_n not in (1, 6, 7)
    cta_block = "" if not show_cta else f'''
      <tr><td style="padding:0 36px 8px 36px;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0">
          <tr><td style="border-radius:8px;background:{pal['accent']};">
            <a href="{BOOKING_URL}"
               style="display:inline-block;padding:13px 28px;font-family:{FONT};font-size:14px;
                      font-weight:700;color:#0a1b2b;text-decoration:none;border-radius:8px;
                      letter-spacing:.3px;">
              Book a 15 minute call
            </a>
          </td></tr>
        </table>
      </td></tr>'''

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <title>LK Advertising</title>
</head>
<body style="margin:0;padding:0;background:{pal['page']};font-family:{FONT};">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"
       style="background:{pal['page']};">
  <tr><td align="center" style="padding:32px 12px;">
    <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0"
           style="max-width:600px;width:100%;background:{pal['card']};border-radius:14px;
                  overflow:hidden;border:1px solid {pal['border']};">

      <!-- GOLD TOP RULE -->
      <tr><td style="background:{pal['accent']};height:4px;line-height:4px;font-size:0;">&nbsp;</td></tr>

      <!-- HERO: real white serif logo centered on navy -->
      <tr><td align="center" style="padding:36px 32px 8px 32px;background:{pal['card']};">
        <img src="{LOGO_URL}" alt="LK Advertising" width="200"
             style="display:block;margin:0 auto;max-width:200px;height:auto;border:0;outline:none;">
        <div style="font-family:{FONT};font-size:12px;color:{pal['text_2']};margin-top:14px;
                    font-weight:500;letter-spacing:1.2px;text-transform:uppercase;">
          {tagline}
        </div>
        <div style="height:1px;width:64px;background:{pal['accent']};margin:20px auto 0;"></div>
      </td></tr>

      <!-- BODY -->
      <tr><td style="padding:22px 36px 6px 36px;background:{pal['card']};">
        {body_html}
      </td></tr>
      {cta_block}

      <!-- SIGNATURE -->
      <tr><td style="padding:20px 36px 30px 36px;background:{pal['card']};">
        <div style="font-family:{FONT};font-size:15px;font-weight:700;color:{pal['ink']};">{sig_name}</div>
        {"".join(f'<div style="font-family:{FONT};font-size:13px;color:{pal["text_2"]};margin-top:1px;">{l}</div>' for l in sig_title_lines)}
        <div style="font-family:{FONT};font-size:13px;margin-top:4px;">
          <a href="{SITE_URL}" style="color:{pal['accent']};text-decoration:none;font-weight:600;">{SITE}</a>
        </div>
      </td></tr>

      <!-- FOOTER (darker navy) -->
      <tr><td style="background:{pal['page']};padding:24px 36px;border-top:1px solid {pal['border']};">
        <div style="font-family:{FONT};font-size:13px;line-height:1.6;color:{pal['text_2']};">
          <b style="color:{pal['ink']};">LK Advertising</b><br>
          {addr and addr + '<br>'}
          <a href="mailto:{contact_email}" style="color:{pal['accent']};text-decoration:none;
                                                   font-weight:600;">{contact_email}</a>
        </div>
        <div style="font-family:{FONT};font-size:12.5px;margin-top:14px;">
          <a href="{SITE_URL}" style="color:{pal['text_2']};text-decoration:none;margin:0 8px 0 0;">Website</a>
          <span style="color:{pal['muted']};">·</span>
          <a href="{SITE_URL}" style="color:{pal['text_2']};text-decoration:none;margin:0 8px;">Privacy</a>
          <span style="color:{pal['muted']};">·</span>
          <a href="{_esc(unsub_url)}" style="color:{pal['text_2']};text-decoration:none;margin:0 8px;">Unsubscribe</a>
        </div>
        <div style="font-family:{FONT};font-size:11px;color:{pal['muted']};margin-top:14px;
                    line-height:1.5;">
          © {year} LK Advertising. All rights reserved.
        </div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
