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

    sig_lines = [_esc(line) for line in (persona.get("signature") or "").split("\n") if line.strip()]
    sig_html = "<br>".join(sig_lines) or _esc(persona.get("from_name", ""))

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

    company_line = (f'{_esc(b.get("wordmark") or "")} · '
                    f'<a href="https://{_esc(site)}" style="color:{c["text_2"]};text-decoration:none;">{_esc(site)}</a>'
                    if site else _esc(b.get("wordmark") or ""))

    # Bottom logo block — the wordmark repeated in the brand accent color,
    # centered, gives the email a clear "this is from <brand>" close. Matches
    # the site's repeated wordmark pattern.
    bottom_logo_html = ""
    if wordmark:
        bottom_logo_html = f'''
        <tr><td style="padding:32px 36px 8px;border-top:1px solid {c['rule']};text-align:center;">
          <div style="font-family:{font};font-size:20px;font-weight:700;letter-spacing:.04em;color:{c['accent']};">
            {_esc(wordmark).upper()}
          </div>
          {f'<div style="font-family:{font};font-size:11px;color:{c["muted"]};margin-top:4px;letter-spacing:.02em;">{_esc(tagline)}</div>' if tagline else ''}
          <div style="height:2px;width:40px;background:{c['accent']};margin:14px auto 0;opacity:.7;"></div>
        </td></tr>'''

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
        <tr><td style="padding:0 36px 28px;">
          <div style="font-family:{font};font-size:14px;line-height:1.5;color:{c['text']};">
            {sig_html}
          </div>
          <div style="font-family:{font};font-size:13px;line-height:1.5;color:{c['text_2']};margin-top:4px;">
            {company_line}
          </div>
        </td></tr>
        {bottom_logo_html}
        <tr><td style="padding:16px 36px 28px;text-align:center;font-family:{font};font-size:12px;line-height:1.5;color:{c['muted']};">
          You're receiving this because we believe it's relevant to your business.<br>
          <a href="{_esc(unsub)}" style="color:{c['accent_2']};text-decoration:underline;">Unsubscribe with one click</a>
          and we won't contact you again.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>"""


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
