"""email_render.py — shared HTML/text renderer for all outbound mail.

Single source of truth for the wire format. Both `resend-pool-send.py` and
`sequence-runner.py` call into this module so a body always renders the same
way regardless of code path.

Brand-driven. Each profile owns a `brand` block (fonts, colors, wordmark,
unsubscribe URL template). The renderer applies that brand per-send, so a
new client with a different palette gets emails that look like THEIR site,
not Aureon's.

Falls back to a neutral default brand when no brand block is provided
(e.g. ad-hoc test sends without a profile context).
"""
from __future__ import annotations

import uuid
import time
from typing import Optional

DEFAULT_BRAND = {
    "wordmark":  "",
    "site":      "",
    "tagline":   "",
    "font_stack": "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif",
    "font_url":   "",
    "colors": {
        "accent":   "#1f2937",
        "accent_2": "#374151",
        "text":     "#111827",
        "text_2":   "#4b5563",
        "muted":    "#9ca3af",
        "bg_page":  "#f5f5f5",
        "bg_card":  "#ffffff",
        "rule":     "#e5e7eb",
    },
    "unsubscribe_url_template": "https://gentritluta.github.io/local-email-stack/unsubscribe.html?t={token}",
}

FALLBACK_UNSUB_MAILTO = "info@aureonglobal.de?subject=unsubscribe"


def unsubscribe_url(token: Optional[str], brand: dict | None = None) -> str:
    """Build the per-prospect unsubscribe URL. Always returns a URL (not a
    mailto:) so the recipient gets a real button. When the token is missing
    we strip it from the template — the static page handles the no-token
    case with a clean error + a fallback contact line."""
    b = brand or DEFAULT_BRAND
    template = b.get("unsubscribe_url_template") or DEFAULT_BRAND["unsubscribe_url_template"]
    if token:
        return template.format(token=token)
    # No token: strip ?t={token} (or &t={token}) from template, keep base URL.
    base = template.split("?")[0]
    return base


def _esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _body_paragraphs_html(body: str, font_stack: str, text_color: str) -> str:
    """`\\n\\n`-separated text paragraphs → <p> blocks with email-safe inline
    styling. Single newlines inside a paragraph become <br>."""
    parts = [p.strip() for p in body.strip().split("\n\n") if p.strip()]
    out = []
    for p in parts:
        escaped = _esc(p).replace("\n", "<br>")
        out.append(
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.65;'
            f'color:{text_color};font-family:{font_stack};">{escaped}</p>'
        )
    return "".join(out)


def render_html(*, body: str, persona: dict, unsubscribe_token: Optional[str] = None,
                brand: dict | None = None) -> str:
    b = {**DEFAULT_BRAND, **(brand or {})}
    # Deep-merge colors so a profile can override one color without losing the rest.
    b["colors"] = {**DEFAULT_BRAND["colors"], **((brand or {}).get("colors") or {})}
    c = b["colors"]
    font = b["font_stack"]
    wordmark = b.get("wordmark") or ""
    tagline = b.get("tagline") or ""
    site = b.get("site") or ""
    unsub = unsubscribe_url(unsubscribe_token, b)

    # Professional signature block:
    #   • Full name (bold, body text size)
    #   • Title (or any subsequent lines from persona.signature) in slightly
    #     smaller, muted secondary color
    # The company line below this is the site only — the wordmark already
    # sits in the top header and the bottom logo block, no need to repeat it.
    sig_lines = [line.strip() for line in (persona.get("signature") or "").split("\n") if line.strip()]
    if not sig_lines:
        sig_lines = [persona.get("from_name", "")]
    name_line = _esc(sig_lines[0])
    title_lines = [_esc(l) for l in sig_lines[1:]]
    sig_html = (
        f'<div style="font-family:{font};font-size:14px;font-weight:600;color:{c["text"]};">{name_line}</div>'
        + "".join(
            f'<div style="font-family:{font};font-size:13px;color:{c["text_2"]};margin-top:1px;">{l}</div>'
            for l in title_lines
        )
    )

    header_html = ""
    if wordmark:
        header_html = f'''
        <tr><td style="padding:32px 36px 0;">
          <div style="font-family:{font};font-size:18px;font-weight:600;letter-spacing:.01em;color:{c['text']};">
            <span style="color:{c['accent']};">{_esc(wordmark)}</span>
          </div>
          {f'<div style="font-family:{font};font-size:12px;color:{c["muted"]};margin-top:2px;">{_esc(tagline)}</div>' if tagline else ''}
          <div style="height:1px;background:{c['accent']};opacity:.35;margin-top:18px;"></div>
        </td></tr>'''

    body_html = _body_paragraphs_html(body, font, c['text'])

    # Quiet website link directly under the signature. No wordmark here — it's
    # already in the top header + bottom logo block. Triple-stating it reads
    # marketing-y, not professional.
    company_line = (f'<a href="https://{_esc(site)}" style="color:{c["text_2"]};text-decoration:none;">{_esc(site)}</a>'
                    if site else "")

    # Corporate footer (the user's preferred style) — only renders when the
    # profile has a brand.legal block. Otherwise we fall back to the simpler
    # accent-rule + unsubscribe footer below.
    legal = (brand or {}).get("legal") or {}
    if legal.get("company_name"):
        footer_html = _corporate_footer_html(legal, unsub, accent=c["accent"])
    else:
        footer_html = _simple_footer_html(c, font, wordmark, tagline, unsub)

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="x-apple-disable-message-reformatting">
  <title>{_esc(wordmark or 'Email')}</title>
</head>
<body style="margin:0;padding:0;background:{c['bg_page']};font-family:{font};">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" style="background:{c['bg_page']};">
    <tr><td align="center" style="padding:32px 12px;">
      <table role="presentation" width="600" cellspacing="0" cellpadding="0" border="0" style="max-width:600px;width:100%;background:{c['bg_card']};border-radius:6px;">
        {header_html}
        <tr><td style="padding:28px 36px 8px;">
          {body_html}
        </td></tr>
        <tr><td style="padding:0 36px 24px;">
          <div style="font-family:{font};font-size:14px;line-height:1.5;color:{c['text']};">
            {sig_html}
          </div>
          <div style="font-family:{font};font-size:13px;line-height:1.5;color:{c['text_2']};margin-top:4px;">
            {company_line}
          </div>
        </td></tr>
        {footer_html}
      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _simple_footer_html(c: dict, font: str, wordmark: str, tagline: str, unsub: str) -> str:
    """The old minimal footer — wordmark + accent rule + small unsubscribe.
    Used when a profile hasn't filled in its brand.legal block yet."""
    bottom = ""
    if wordmark:
        bottom = f'''
        <tr><td style="padding:32px 36px 8px;border-top:1px solid {c['rule']};text-align:center;">
          <div style="font-family:{font};font-size:20px;font-weight:700;letter-spacing:.04em;color:{c['accent']};">
            {_esc(wordmark).upper()}
          </div>
          {f'<div style="font-family:{font};font-size:11px;color:{c["muted"]};margin-top:4px;letter-spacing:.02em;">{_esc(tagline)}</div>' if tagline else ''}
          <div style="height:2px;width:40px;background:{c['accent']};margin:14px auto 0;opacity:.7;"></div>
        </td></tr>'''
    return bottom + f'''
        <tr><td style="padding:16px 36px 28px;text-align:center;font-family:{font};font-size:12px;line-height:1.5;color:{c['muted']};">
          You're receiving this because we believe it's relevant to your business.<br>
          <a href="{_esc(unsub)}" style="color:{c['accent_2']};text-decoration:underline;">Unsubscribe with one click</a>
          and we won't contact you again.
        </td></tr>'''


def _corporate_footer_html(legal: dict, unsub: str, accent: str = "#d4af37") -> str:
    """Two-tier corporate email footer matching the user's spec:

      1. Light Arial block: company name, address, email, CEO, VAT, Reg,
         long confidentiality disclaimer.
      2. Dark Verdana block: logo + uppercase wordmark, address, email,
         Website | Privacy | Terms | Unsubscribe row, copyright + reg
         numbers, partner-notice line.

    The per-prospect unsubscribe URL is slotted into the link row so legal
    compliance + the existing one-click unsubscribe flow both apply.
    """
    name      = _esc(legal.get("company_name", ""))
    addr_lines = legal.get("address_lines") or []
    email     = _esc(legal.get("contact_email", ""))
    ceo       = _esc(legal.get("ceo", ""))
    vat       = _esc(legal.get("vat_number", ""))
    reg       = _esc(legal.get("registration_number", ""))
    year      = str(legal.get("copyright_year") or 2026)
    logo_url  = _esc(legal.get("logo_url", ""))
    logo_w    = int(legal.get("logo_width") or 50)
    privacy   = _esc(legal.get("privacy_policy_url", ""))
    terms     = _esc(legal.get("terms_of_service_url", ""))
    website   = "https://" + _esc(legal.get("contact_email", "").split("@")[-1]) if email else ""
    disclaim  = _esc(legal.get("legal_disclaimer", ""))
    partner   = _esc(legal.get("partner_notice", ""))

    # Wordmark text in the dark block — uppercase, strip the legal-form dots
    # so "Aureon Global L.L.C." reads as "AUREON GLOBAL LLC".
    wordmark_dark = name.replace(".", "").upper().strip()

    # Light block: street, city, country on one inline line.
    addr_inline = ", ".join(_esc(l) for l in addr_lines)
    # Dark block: collapse all but the last line (country) into one row with a
    # trailing comma, then country on its own line. Mirrors the user's spec.
    if len(addr_lines) >= 2:
        addr_block = ", ".join(_esc(l) for l in addr_lines[:-1]) + f",<br>{_esc(addr_lines[-1])}"
    elif addr_lines:
        addr_block = _esc(addr_lines[0])
    else:
        addr_block = ""

    # ── LIGHT confidentiality block ────────────────────────────────────────
    light = f'''
        <tr><td style="padding:0 36px 16px;">
          <div style="font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:1.45;color:#333333;border-top:1px solid #ececec;padding-top:18px;">
            <div style="font-weight:700;color:#111111;margin:0 0 2px;">{name}</div>
            {f'<div>Address: {addr_inline}</div>' if addr_inline else ''}
            {f'<div>Email: <a href="mailto:{email}" style="color:#333333;text-decoration:none;">{email}</a></div>' if email else ''}
            {f'<div style="margin-top:8px;">CEO: {ceo}</div>' if ceo else ''}
            {f'<div>VAT Number: {vat}</div>' if vat else ''}
            {f'<div style="margin-bottom:8px;">Registration Number: {reg}</div>' if reg else ''}
            <div>© {year} {name} {disclaim}</div>
          </div>
        </td></tr>'''

    # ── DARK Verdana brand block ───────────────────────────────────────────
    logo_img = (
        f'<img src="{logo_url}" alt="{name} Logo" width="{logo_w}" '
        f'style="display:block;margin:0 auto 10px auto;border:0;">'
        if logo_url else ""
    )
    # Links row: Website | Privacy | Terms | Unsubscribe — only show what we have.
    parts = []
    if website:  parts.append(f'<a href="{website}" style="color:{accent};text-decoration:none;margin:0 8px;font-weight:500;">Website</a>')
    if privacy:  parts.append(f'<a href="{privacy}" style="color:{accent};text-decoration:none;margin:0 8px;font-weight:500;">Privacy Policy</a>')
    if terms:    parts.append(f'<a href="{terms}" style="color:{accent};text-decoration:none;margin:0 8px;font-weight:500;">Terms of Service</a>')
    if unsub:    parts.append(f'<a href="{_esc(unsub)}" style="color:{accent};text-decoration:none;margin:0 8px;font-weight:500;">Unsubscribe</a>')
    sep = '<span style="color:#333333;margin:0 4px;">|</span>'
    links_row = sep.join(parts)

    dark = f'''
        <tr><td style="padding:0;">
          <div style="background-color:#050505;padding:40px 30px;text-align:center;color:#999999;border-top:4px solid {accent};font-family:Verdana,sans-serif;">
            <table width="100%" border="0" cellspacing="0" cellpadding="0">
              <tr>
                <td align="center">
                  <div style="margin-bottom:20px;padding-top:20px;border-top:1px solid #1a1a1a;">
                    <a href="{website or '#'}" style="text-decoration:none;">
                      {logo_img}
                      <span style="color:#ffffff;font-weight:800;text-transform:uppercase;letter-spacing:1px;display:block;margin-bottom:5px;font-family:Verdana,sans-serif;font-size:16px;">{wordmark_dark}</span>
                    </a>
                  </div>
                  <p style="font-size:12px;line-height:1.6;margin:5px 0;color:#888888;font-family:Verdana,sans-serif;">
                    <b style="color:#ffffff;">{name}</b><br>
                    {addr_block}
                  </p>
                  {f'<p style="font-size:12px;line-height:1.6;margin:5px 0;font-family:Verdana,sans-serif;"><a href="mailto:{email}" style="color:{accent};text-decoration:none;font-weight:500;">{email}</a></p>' if email else ''}
                  <p style="font-size:12px;line-height:1.6;margin:10px 0;font-family:Verdana,sans-serif;">
                    {links_row}
                  </p>
                  <div style="margin-top:25px;padding-top:25px;border-top:1px solid #1a1a1a;">
                    <p style="font-size:10px;color:#555555;margin:0;font-family:Verdana,sans-serif;">
                      © {year} {wordmark_dark}. All rights reserved.<br>
                      {f'VAT ID: {vat} | Reg. No: {reg}' if vat or reg else ''}
                    </p>
                    {f'<p style="font-size:10px;color:#444444;margin-top:10px;line-height:1.4;font-family:Verdana,sans-serif;">{partner}</p>' if partner else ''}
                  </div>
                </td>
              </tr>
            </table>
          </div>
        </td></tr>'''

    return light + dark


def render_text(*, body: str, persona: dict, unsubscribe_token: Optional[str] = None,
                brand: dict | None = None) -> str:
    b = {**DEFAULT_BRAND, **(brand or {})}
    sig = (persona.get("signature") or persona.get("from_name", "")).strip()
    site_line = f"\n{b.get('wordmark','')} · {b.get('site','')}" if b.get("site") else ""
    unsub = unsubscribe_url(unsubscribe_token, b)
    return (
        body.strip()
        + "\n\n" + sig
        + site_line
        + "\n\n---"
        + f"\nDon't want these emails? Unsubscribe: {unsub}"
    )


def build_payload(*, persona: dict, to_addr: str, subject: str, body: str,
                  unsubscribe_token: Optional[str] = None,
                  brand: dict | None = None,
                  tags: list[dict] | None = None) -> tuple[dict, str]:
    """Build the Resend API JSON payload + the Message-ID we generated."""
    domain = persona["from_addr"].split("@", 1)[1]
    msg_id = f"<{uuid.uuid4().hex}.{int(time.time())}@{domain}>"
    unsub = unsubscribe_url(unsubscribe_token, brand)
    html = render_html(body=body, persona=persona, unsubscribe_token=unsubscribe_token, brand=brand)
    text = render_text(body=body, persona=persona, unsubscribe_token=unsubscribe_token, brand=brand)
    headers = {
        "Message-ID":            msg_id,
        # Gmail prefers URL form (RFC 8058 one-click); mailto fallback for older clients.
        "List-Unsubscribe":      f"<{unsub}>, <mailto:{FALLBACK_UNSUB_MAILTO}>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }
    payload = {
        "from":     f'{persona["from_name"]} <{persona["from_addr"]}>',
        "to":       [to_addr],
        "reply_to": persona.get("reply_to", persona["from_addr"]),
        "subject":  subject,
        "text":     text,
        "html":     html,
        "headers":  headers,
        "tags":     tags or [],
    }
    return payload, msg_id
