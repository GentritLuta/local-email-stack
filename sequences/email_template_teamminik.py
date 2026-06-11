"""Custom email template for Team Minik — matches teamminik.com.

Design tokens pulled LIVE from the site (2026-06-07, computed styles):
  - LIGHT theme. White bg, black/#333/#555 text
  - Primary navy rgb(16,41,90) = #10295A
  - Accent crimson/magenta rgb(219,18,99) = #DB1263 (NOT gold)
  - Font: Figtree (with safe fallbacks)
  - Buttons: SQUARE (0 radius), navy or crimson fill, white text, UPPERCASE
  - Tagline: "Unlock your Real Estate Potential"

Reply-based steps (1, 6, 7) omit the CTA button; persuasion steps (2-5) show a
square navy "SCHEDULE A CALL" button. Dispatched when
brand.template == "teamminik-custom".
"""
from __future__ import annotations
import html as _html
from typing import Optional

PAL = {
    "page":     "#EEF1F5",   # soft grey page framing the card
    "sheet":    "#FFFFFF",   # white card
    "ink":      "#0A0A0A",   # near-black headings (site uses pure black)
    "body":     "#333333",   # site body text
    "body_2":   "#555555",   # site secondary text
    "muted":    "#9E9E9E",   # muted grey
    "rule":     "#E4E7EC",   # hairline
    "navy":     "#10295A",   # primary brand navy (live)
    "crimson":  "#DB1263",   # accent crimson/magenta (live)
}
SANS = "'Figtree', 'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"


def _esc(s: str) -> str:
    return _html.escape(s, quote=True) if s else ""


def _body_html(body: str) -> str:
    out = []
    for para in [p for p in body.strip().split("\n\n") if p.strip()]:
        escaped = _esc(para).replace("\n", "<br>")
        out.append(
            f'<p style="margin:0 0 18px 0;font-family:{SANS};font-size:16px;'
            f'line-height:1.7;color:{PAL["body"]};font-weight:400;">{escaped}</p>'
        )
    return "".join(out)


def _tm_logo_inline() -> str:
    """Inline SVG mark: navy square with a crimson roofline (real brand colors)."""
    return (
        '<svg width="22" height="22" viewBox="0 0 22 22" xmlns="http://www.w3.org/2000/svg" '
        'style="vertical-align:middle;display:inline-block;margin-right:9px;">'
        '<rect x="0" y="0" width="22" height="22" fill="#10295A"/>'
        '<path d="M4 16 V9 L11 4 L18 9 V16" fill="none" stroke="#DB1263" stroke-width="1.9" '
        'stroke-linejoin="round"/>'
        '</svg>'
    )


def render_html_teamminik(*, body: str, persona: dict,
                          unsubscribe_token: Optional[str] = None,
                          brand: Optional[dict] = None,
                          step_n: int = 1) -> str:
    brand = brand or {}
    legal = brand.get("legal") or {}

    body_html = _body_html(body)

    sig_raw = persona.get("signature") or persona.get("from_name", "")
    sig_lines = [_esc(l.strip()) for l in sig_raw.split("\n") if l.strip()]
    sig_name = sig_lines[0] if sig_lines else _esc(persona.get("from_name", ""))
    sig_rest = sig_lines[1:]

    site = brand.get("site", "teamminik.com")
    site_url = f"https://{site}"
    cta_url = brand.get("cta_url") or site_url
    contact_email = _esc(legal.get("contact_email", "michelle@teamminik.com"))
    company = _esc(legal.get("company_name", "Team Minik"))
    addr = legal.get("address_lines") or []
    addr_line = " · ".join(_esc(a) for a in addr)
    priv = _esc(legal.get("privacy_policy_url", f"{site_url}/privacy"))
    terms = _esc(legal.get("terms_of_service_url", f"{site_url}/terms"))

    tpl = brand.get("unsubscribe_url_template",
                    "https://gentritluta.github.io/local-email-stack/unsubscribe/teamminik.html?t={token}")
    unsub_url = _esc(tpl.replace("{token}", unsubscribe_token or "preview"))

    # CTA only on persuasion steps (2-5). Square navy button, uppercase (site style).
    cta = ""
    if step_n in (2, 3, 4, 5):
        cta = f"""
      <tr><td style="background:{PAL['sheet']};padding:2px 36px 12px 36px;">
        <table role="presentation" cellspacing="0" cellpadding="0" border="0">
          <tr><td style="background:{PAL['navy']};">
            <a href="{cta_url}" style="display:inline-block;padding:14px 30px;font-family:{SANS};
               font-size:12.5px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;
               color:#ffffff;text-decoration:none;">Schedule a call &nbsp;&rarr;</a>
          </td></tr>
        </table>
      </td></tr>"""

    # Navy promise band (matches the site's dark section / footer).
    dark_strip = f"""
      <tr><td style="background:{PAL['navy']};padding:14px 36px;">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="font-family:{SANS};font-size:13px;font-weight:700;color:#ffffff;letter-spacing:-0.2px;">
              Unlock your Real Estate Potential<span style="color:{PAL['crimson']};">.</span>
            </td>
            <td align="right" style="font-family:{SANS};font-size:10px;font-weight:400;color:#A9B6CE;letter-spacing:0.3px;">
              Team Minik &middot; teamminik.com
            </td>
          </tr>
        </table>
      </td></tr>"""

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=Figtree:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <title>Team Minik</title>
</head>
<body style="margin:0;padding:0;background:{PAL['page']};font-family:{SANS};">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:{PAL['page']};">
  <tr><td align="center" style="padding:28px 12px;">
    <table role="presentation" width="620" cellspacing="0" cellpadding="0" border="0"
           style="max-width:620px;width:100%;background:{PAL['sheet']};border:1px solid {PAL['rule']};">

      <!-- HEADER -->
      <tr><td style="padding:18px 36px 14px 36px;border-bottom:2px solid {PAL['navy']};">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="line-height:1;">
              {_tm_logo_inline()}<span style="font-family:{SANS};font-size:20px;font-weight:800;
                                                  color:{PAL['navy']};letter-spacing:-0.3px;
                                                  vertical-align:middle;">TEAM MINIK</span>
            </td>
            <td align="right" style="font-family:{SANS};font-size:10px;font-weight:600;
                       color:{PAL['muted']};letter-spacing:1.4px;text-transform:uppercase;">
              Realty of America
            </td>
          </tr>
        </table>
      </td></tr>

      <!-- BODY -->
      <tr><td style="padding:20px 36px 6px 36px;">
        {body_html}
      </td></tr>
{cta}
      <!-- SIGNATURE -->
      <tr><td style="padding:10px 36px 18px 36px;border-top:1px solid {PAL['rule']};">
        <div style="font-family:{SANS};font-size:15px;font-weight:700;color:{PAL['navy']};
                    letter-spacing:-0.2px;">{sig_name}</div>
        {"".join(f'<div style="font-family:{SANS};font-size:12px;font-weight:400;color:{PAL["body_2"]};margin-top:2px;">{l}</div>' for l in sig_rest)}
        <div style="font-family:{SANS};font-size:12px;margin-top:6px;font-weight:600;">
          <a href="{site_url}" style="color:{PAL['crimson']};text-decoration:none;">{_esc(site)} &rarr;</a>
        </div>
      </td></tr>

      <!-- NAVY PROMISE STRIP -->
{dark_strip}

      <!-- FOOTER -->
      <tr><td style="background:{PAL['sheet']};padding:12px 36px 16px 36px;border-top:1px solid {PAL['rule']};">
        <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0">
          <tr>
            <td style="font-family:{SANS};font-size:10px;color:{PAL['muted']};line-height:1.5;">
              <strong style="color:{PAL['navy']};font-weight:700;">{company}</strong> &middot; {addr_line} &middot;
              <a href="mailto:{contact_email}" style="color:{PAL['crimson']};text-decoration:none;">{contact_email}</a>
            </td>
            <td align="right" style="font-family:{SANS};font-size:10px;color:{PAL['muted']};white-space:nowrap;">
              <a href="{priv}" style="color:{PAL['muted']};text-decoration:underline;">Privacy</a> &middot;
              <a href="{terms}" style="color:{PAL['muted']};text-decoration:underline;">Terms</a> &middot;
              <a href="{unsub_url}" style="color:{PAL['muted']};text-decoration:underline;">Unsubscribe</a>
            </td>
          </tr>
        </table>
      </td></tr>

    </table>
  </td></tr>
</table>
</body>
</html>"""
