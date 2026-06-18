# -*- coding: utf-8 -*-
"""Shared email sanitiser for the scrapers.

Scraped HTML carries two kinds of junk that the raw extraction regexes happily
captured as if they were the local-part of an address:

  * JSON-escaped markup that was never decoded, so `\\u003e` (an escaped `>`)
    survived as the literal text `u003e` and got glued onto the front of an
    address, e.g. `u003ealsterhaus@beisser.de`.
  * Label prefixes printed next to the address (`E-Mail: info@x.de`) and
    deliberately obfuscated addresses (`ma**@*****ee.com`) pulled straight out
    of a `mailto:` href without validation.

`clean_email` decodes the escapes/entities, strips those artefacts, and returns
a lower-cased address only if what remains is actually a valid email; otherwise
it returns None. Apostrophes are allowed in the local-part because they are
valid (RFC 5321) and real people have them (e.g. `carlie.o'brien@...`).
"""
import html as _html
import re as _re

# Full-match validator. Local-part allows the apostrophe; obfuscation chars
# (`*`, `<`, `>`, whitespace) are deliberately excluded so masked addresses fail.
_EMAIL_FULL = _re.compile(r"[A-Za-z0-9._%+\-']+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
# `E-Mail:` / `Mail >` / `mailto:` style labels printed before the address.
_LABEL_RX = _re.compile(r"(?i)^(?:e-?mail|mail|mailto|email\s*address)\s*[:>\s]+")
# Leftover unicode-escape artefacts that ended up as the literal prefix of the
# local-part (`u003e` from `>`, `x3e` from `\x3e`).
_ESC_PREFIX_RX = _re.compile(r"(?i)^(?:u00[0-9a-f]{2}|x[0-9a-f]{2})+")


def clean_email(raw):
    """Return a normalised, validated email address, or None if `raw` cannot be
    cleaned into a valid one."""
    if not raw:
        return None
    a = _html.unescape(str(raw))                                   # &gt; -> >, &#64; -> @
    a = _re.sub(r"\\u([0-9a-fA-F]{4})",
                lambda m: chr(int(m.group(1), 16)), a)             # > -> >
    a = _re.sub("(?i)%40", "@", a)                                 # URL-encoded @ in mailto hrefs
    a = a.strip().strip("<>\"' \t")
    a = _LABEL_RX.sub("", a)                                       # drop "E-Mail:" labels
    a = _ESC_PREFIX_RX.sub("", a)                                  # drop u003e-style artefacts
    a = a.strip().strip("<>\"' \t").lower()
    if not _EMAIL_FULL.fullmatch(a):
        return None
    if ".." in a or a.startswith(".") or "@." in a or a.endswith("."):
        return None
    return a
