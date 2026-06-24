"""Custom email template for Mark-eting — matches mark-eting.co 1:1 (verified 2026-06-14).

Pulled from the live site source + logo file:
  - Logo: orange tile, white rounded-bold "Mark-eting" wordmark
    (https://www.mark-eting.co/images/mark-eting-logo.jpg, 360x360)
  - Brand orange: #f07307 (sampled from the logo tile; site button #ef6c22)
  - Hero gradient (premium dark): linear-gradient(135deg, #1a1a2e 0%,
    #16213e 25%, #1a1a2e 50%, #2d1810 75%, #1a1a2e 100%) — verified from site CSS
  - Site font: Geist (near-identical to Inter; Inter used as the email-safe match)
  - Visual language: clean white content sheet, orange accents, premium navy
    sections. The footer reproduces the site's exact hero gradient.

Header carries the real logo. The navy footer echoes the site hero 1:1.
Reply-based steps (1, 3, 6, 7) omit the CTA button to keep the give-first,
"just reply AUDIT" tone. Booking steps (2, 4, 5) get the orange CTA button.
"""
from __future__ import annotations
import html as _html
from typing import Optional

PAL = {
    "page":     "#f5f5f5",   # site page grey
    "sheet":    "#ffffff",   # white content sheet
    "ink":      "#0b0b0b",   # near-black headings (site)
    "body":     "#333333",   # body text
    "muted":    "#8f8f8f",   # muted grey (kicker / footer meta)
    "rule":     "#ececec",   # hairline rule
    "orange":   "#f07307",   # Mark-eting brand orange (sampled from logo)
    "orange_d": "#c25608",   # darker orange for depth
    "navy":     "#1a1a2e",   # hero navy (site)
    "navy_2":   "#16213e",   # hero navy variant (site)
}
SANS = "'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"
# Site hero gradient, reproduced 1:1 for the footer block.
NAVY_GRADIENT = ("linear-gradient(135deg, #1a1a2e 0%, #16213e 25%, "
                 "#1a1a2e 50%, #2d1810 75%, #1a1a2e 100%)")
LOGO = "https://www.mark-eting.co/images/mark-eting-logo.jpg"


def _esc(s: str) -> str:
    return _html.escape(s, quote=True) if s else ""


def _strip_signoff(body: str) -> str:
    """Drop a trailing standalone signoff line (the copy ends in 'Mark' /
    'Mark-eting') so the template's signature block is the single signoff and
    matches the sending persona. Conservative: only strips a short final line
    that is a bare name, never real content."""
    paras = [p for p in body.strip().split("\n\n") if p.strip()]
    if paras:
        last = paras[-1].strip()
        if last.lower() in {"mark", "mark-eting", "mark\nmark-eting",
                             "the mark-eting team", "team mark-eting"}:
            paras = paras[:-1]
    return "\n\n".join(paras)


def _body_html(body: str) -> str:
    out = []
    for para in [p for p in body.strip().split("\n\n") if p.strip()]:
        escaped = _esc(para).replace("\n", "<br>")
        out.append(
            f'<p style="margin:0 0 18px 0;font-family:{SANS};font-size:16px;'
            f'line-height:1.7;color:{PAL["body"]};font-weight:400;">{escaped}</p>'
        )
    return "".join(out)


def render_html_mark_eting(*, body: str, persona: dict,
                           unsubscribe_token: Optional[str] = None,
                           brand: Optional[dict] = None,
                           step_n: int = 1) -> str:
    brand = brand or {}
    legal = brand.get("legal") or {}

    body_html = _body_html(_strip_signoff(body))

    sig_raw = persona.get("signature") or persona.get("from_name", "")
    sig_lines = [_esc(l.strip()) for l in sig_raw.split("\n") if l.strip()]
    sig_name = sig_lines[0] if sig_lines else _esc(persona.get("from_name", ""))
    sig_rest = sig_lines[1:]

    site = brand.get("site", "mark-eting.co")
    site_url = f"https://{site}"
    cta_url = brand.get("cta_url") or ""
    logo = legal.get("logo_url") or LOGO
    contact_email = _esc(legal.get("contact_email", "mark@mark-eting.co"))
    company = _esc(legal.get("company_name", "Mark-eting B.V."))
    addr = legal.get("address_lines") or []
    addr_line = " · ".join(_esc(a) for a in addr)
    year = str(legal.get("copyright_year") or 2026)
    priv = _esc(legal.get("privacy_policy_url", site_url))
    terms = _esc(legal.get("terms_of_service_url", site_url))
    tagline = _esc(brand.get("tagline", ""))

    tpl = brand.get("unsubscribe_url_template",
                    "https://gentritluta.github.io/local-email-stack/unsubscribe/mark-eting.html?t={token}")
    unsub_url = _esc(tpl.replace("{token}", unsubscribe_token or "preview"))

    # CTA only on the booking steps (2, 4, 5) and only with a real booking URL,
    # so give-first reply steps (1, 3, 6, 7) stay clean text.
    cta = ""
    if cta_url and step_n in (2, 4, 5):
        cta = f"""
      <tr><td style="background:{PAL['sheet']};padding:4px 36px 14px 36px;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0">
          <tr><td style="background:{PAL['orange']};border-radius:8px;">
            <a href="{cta_url}" style="display:inline-block;padding:12px 26px;font-family:{SANS};
               font-size:13px;font-weight:600;letter-spacing:0.2px;
               color:#ffffff;text-decoration:none;">Book a 15-minute call &nbsp;&rarr;</a>
          </td></tr>
        </table>
      </td></tr>"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
  <title>Mark-eting</title>
</head>
<body style="margin:0;padding:0;background:{PAL['page']};font-family:{SANS};">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:{PAL['page']};">
  <tr><td align="center" style="padding:28px 12px;">
    <table role="presentation" width="620" cellspacing="0" cellpadding="0" border="0"
           style="max-width:620px;width:100%;background:{PAL['sheet']};border:1px solid {PAL['rule']};border-radius:10px;overflow:hidden;">

      <!-- HEADER: the logo wordmark-tile (carries the name) + kicker -->
      <tr><td style="padding:18px 36px 16px 36px;border-bottom:1px solid {PAL['rule']};">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="line-height:1;">
              <img src="{logo}" width="52" height="52" alt="Mark-eting"
                   style="display:inline-block;vertical-align:middle;border-radius:11px;border:0;outline:none;">
            </td>
            <td align="right" style="font-family:{SANS};font-size:10px;font-weight:600;
                       color:{PAL['orange']};letter-spacing:1.4px;text-transform:uppercase;">
              Get found on Google
            </td>
          </tr>
        </table>
      </td></tr>

      <!-- BODY -->
      <tr><td style="padding:22px 36px 4px 36px;">
        {body_html}
      </td></tr>
{cta}
      <!-- SIGNATURE -->
      <tr><td style="padding:6px 36px 18px 36px;border-top:1px solid {PAL['rule']};">
        <div style="font-family:{SANS};font-size:15px;font-weight:700;color:{PAL['ink']};
                    letter-spacing:-0.2px;">{sig_name}</div>
        {"".join(f'<div style="font-family:{SANS};font-size:12px;font-weight:400;color:{PAL["muted"]};margin-top:2px;">{l}</div>' for l in sig_rest)}
        <div style="font-family:{SANS};font-size:12px;margin-top:6px;font-weight:600;">
          <a href="{site_url}" style="color:{PAL['orange']};text-decoration:none;">{_esc(site)} &rarr;</a>
        </div>
      </td></tr>

      <!-- FOOTER: site hero gradient (navy), reproduced 1:1 -->
      <tr><td style="background:{PAL['navy']};background:{NAVY_GRADIENT};padding:22px 36px 22px 36px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="line-height:1;">
              <img src="{logo}" width="40" height="40" alt="Mark-eting"
                   style="display:inline-block;vertical-align:middle;border-radius:9px;border:0;outline:none;">
            </td>
            <td align="right" style="font-family:{SANS};font-size:10px;font-weight:400;
                       color:rgba(255,255,255,0.6);letter-spacing:0.3px;">
              {tagline}
            </td>
          </tr>
        </table>
        <div style="font-family:{SANS};font-size:10px;color:rgba(255,255,255,0.5);line-height:1.6;margin-top:14px;">
          <strong style="color:rgba(255,255,255,0.8);font-weight:600;">{company}</strong> &middot; {addr_line}<br>
          <a href="mailto:{contact_email}" style="color:rgba(255,255,255,0.7);text-decoration:none;">{contact_email}</a> &middot;
          &copy; {year} Mark-eting B.V.
        </div>
        <div style="font-family:{SANS};font-size:10px;color:rgba(255,255,255,0.5);margin-top:10px;">
          <a href="{priv}" style="color:rgba(255,255,255,0.6);text-decoration:underline;">Privacy</a> &middot;
          <a href="{terms}" style="color:rgba(255,255,255,0.6);text-decoration:underline;">Terms</a> &middot;
          <a href="{unsub_url}" style="color:{PAL['orange']};text-decoration:underline;">Unsubscribe</a>
        </div>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
