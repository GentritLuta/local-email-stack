"""Custom HTML email template — UNIQUE design based on https://diraya.ca.

Design DNA pulled live from diraya.ca via Playwright computed styles:
  - Fonts: 'Inter Tight' (heavy display headlines, up to 900 wt) + 'Kanit'
    (uppercase labels / nav / kickers / buttons)
  - Palette: stark black #101010 / pure white #ffffff, body grey #454545,
    hairline rgba on dark = rgba(255,255,255,0.12)
  - border-radius: 0 everywhere (sharp brutalist corners), no shadows
  - Thin horizontal arrow + small uppercase Kanit kicker above big headline
  - Black wordmark top-left ("Atal Solidrocks") with a small square mark
  - CTA = solid black block, white uppercase Kanit label, square corners

Standalone — does NOT depend on the local-email-stack profile pipeline.
Company data is passed in via the BRAND dict at the bottom of the sequence file.
"""
from __future__ import annotations
import html as _html
from typing import Optional

# ---- diraya.ca palette ----
INK   = "#101010"   # near-black (headlines, dark sections)
BLACK = "#000000"
WHITE = "#ffffff"
BODY  = "#454545"   # body grey
MUTED = "#8a8a8a"   # muted footer grey
RULE  = "#e6e6e6"   # light hairline on white
RULE_D = "rgba(255,255,255,0.18)"  # hairline on dark

DISPLAY = "'Inter Tight', 'Helvetica Neue', Arial, sans-serif"   # headlines
LABEL   = "'Kanit', 'Helvetica Neue', Arial, sans-serif"          # uppercase labels/CTA
BODYFF  = "'Inter Tight', 'Helvetica Neue', Arial, sans-serif"    # body


def _esc(s: str) -> str:
    return _html.escape(s, quote=True) if s else ""


def _body_html(body: str) -> str:
    out = []
    for para in [p for p in body.strip().split("\n\n") if p.strip()]:
        escaped = _esc(para).replace("\n", "<br>")
        out.append(
            f'<p style="margin:0 0 20px 0;font-family:{BODYFF};font-size:16px;'
            f'line-height:1.7;color:{BODY};font-weight:400;">{escaped}</p>'
        )
    return "".join(out)


def render(*, headline: str, kicker: str, body: str, cta_label: str,
           cta_url: str, signature: list[str], brand: dict,
           show_cta: bool = True, step_n: int = 1) -> str:
    """Render one email. headline = the big Inter Tight display line.
    kicker = small uppercase Kanit label above it. signature = list of lines.
    """
    legal = brand.get("legal", {})
    company = _esc(legal.get("company_name", "Atal Solidrocks"))
    reg = _esc(legal.get("reg_number", ""))
    addr = " · ".join(_esc(a) for a in legal.get("address_lines", []))
    contact = _esc(legal.get("contact_email", ""))
    site = brand.get("site", "atalsolidrocks.com")
    site_url = f"https://{site}"
    year = str(legal.get("copyright_year", 2026))
    unsub = _esc(brand.get("unsubscribe_url", f"{site_url}/abmelden"))
    wordmark = _esc(brand.get("wordmark", "Atal Solidrocks"))
    tagline = _esc(brand.get("tagline", ""))

    sig_name = _esc(signature[0]) if signature else ""
    sig_rest = signature[1:]

    body_html = _body_html(body)

    cta_block = ""
    if show_cta:
        cta_block = f"""
      <tr><td style="padding:8px 44px 40px 44px;background:{WHITE};">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0">
          <tr><td style="background:{INK};">
            <a href="{_esc(cta_url)}" style="display:inline-block;padding:17px 38px;
               font-family:{LABEL};font-size:13px;font-weight:600;letter-spacing:1.6px;
               text-transform:uppercase;color:{WHITE};text-decoration:none;">{_esc(cta_label)} &nbsp;&#8594;</a>
          </td></tr>
        </table>
      </td></tr>"""

    return f"""<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter+Tight:wght@400;500;600;700;900&family=Kanit:wght@400;500;600;700&display=swap" rel="stylesheet">
  <title>{company}</title>
</head>
<body style="margin:0;padding:0;background:#dcdcdc;font-family:{BODYFF};-webkit-font-smoothing:antialiased;">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:#dcdcdc;">
  <tr><td align="center" style="padding:30px 12px;">
    <table role="presentation" width="620" cellspacing="0" cellpadding="0" border="0"
           style="max-width:620px;width:100%;background:{WHITE};border-radius:0;">

      <!-- HEADER BAR: black wordmark left, uppercase Kanit label right -->
      <tr><td style="padding:22px 44px;border-bottom:1px solid {INK};">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0"><tr>
          <td style="vertical-align:middle;">
            <table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr>
              <td style="vertical-align:middle;"><div style="width:18px;height:18px;background:{INK};"></div></td>
              <td style="vertical-align:middle;padding-left:10px;font-family:{DISPLAY};
                  font-size:19px;font-weight:700;color:{INK};letter-spacing:-0.4px;">{wordmark}</td>
            </tr></table>
          </td>
          <td align="right" style="vertical-align:middle;font-family:{LABEL};font-size:11px;
              font-weight:500;letter-spacing:2px;text-transform:uppercase;color:{INK};">Prävention · DACH</td>
        </tr></table>
      </td></tr>

      <!-- HERO: thin arrow + kicker, then big Inter Tight headline (diraya.ca signature) -->
      <tr><td style="padding:46px 44px 14px 44px;background:{WHITE};">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr>
          <td style="vertical-align:middle;"><div style="width:44px;height:1px;background:{INK};"></div></td>
          <td style="vertical-align:middle;padding-left:14px;font-family:{LABEL};font-size:11px;
              font-weight:500;letter-spacing:2.4px;text-transform:uppercase;color:{INK};">{_esc(kicker)}</td>
        </tr></table>
        <div style="font-family:{DISPLAY};font-size:42px;line-height:1.02;font-weight:900;
             color:{INK};letter-spacing:-1.4px;margin-top:20px;">{_esc(headline)}</div>
      </td></tr>

      <!-- BODY -->
      <tr><td style="padding:28px 44px 4px 44px;background:{WHITE};">
        {body_html}
      </td></tr>
{cta_block}
      <!-- SIGNATURE -->
      <tr><td style="padding:8px 44px 36px 44px;background:{WHITE};border-top:1px solid {RULE};">
        <div style="height:18px;"></div>
        <div style="font-family:{DISPLAY};font-size:17px;font-weight:700;color:{INK};">{sig_name}</div>
        {"".join(f'<div style="font-family:{BODYFF};font-size:13px;color:{MUTED};margin-top:3px;">{_esc(l)}</div>' for l in sig_rest)}
        <div style="margin-top:10px;font-family:{LABEL};font-size:11px;font-weight:500;letter-spacing:1.4px;text-transform:uppercase;">
          <a href="{site_url}" style="color:{INK};text-decoration:none;">{_esc(site)}</a>
        </div>
      </td></tr>

      <!-- FOOTER: dark block, diraya.ca contact-section feel -->
      <tr><td style="background:{INK};padding:34px 44px 30px 44px;">
        <div style="font-family:{DISPLAY};font-size:24px;font-weight:900;color:{WHITE};letter-spacing:-0.6px;line-height:1.1;">{tagline}</div>
        <div style="height:1px;background:{RULE_D};margin:22px 0 18px 0;"></div>
        <div style="font-family:{BODYFF};font-size:12px;color:#bdbdbd;line-height:1.8;">
          {company}{(" · " + reg) if reg else ""}<br>
          {addr}<br>
          <a href="mailto:{contact}" style="color:{WHITE};text-decoration:none;">{contact}</a>
        </div>
        <div style="margin-top:16px;font-family:{LABEL};font-size:10px;font-weight:500;letter-spacing:1.2px;text-transform:uppercase;">
          <a href="{unsub}" style="color:{MUTED};text-decoration:underline;">Abmelden</a>
          <span style="color:{MUTED};">&nbsp;·&nbsp; © {year} {company}</span>
        </div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
