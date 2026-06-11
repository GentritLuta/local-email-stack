"""algoalpha_offer.py — the AlgoAlpha creator-proposal formula, one place.

Per-influencer proposal = FIXED per-video retainer (scales with audience)
+ 30 percent lifetime commission on top. Imported by sequence-runner.py
(outbound merge fields) and reply-autodraft.py (response drafting) so the
emails and the replies always quote the same numbers.

The formula
    retainer_per_video(S) = clamp( round50( 4 USD x S/1000 ), 200, 5000 )
    paid videos capped at 4 per month
    S = audience_size (subscribers/followers, scraped per prospect)

Why 4 USD per 1,000 subscribers: a featured integration averages ~10 percent
of subscribers in views, so 4/1k subs is ~40 USD CPM on expected views —
solid market rate for finance/crypto integrations, deliberately NOT top of
market. The math favors AlgoAlpha: break-even on the retainer is a constant
~0.023 percent of expected views converting (avg paid signup = 247 USD year
one, creator keeps 30 percent lifetime = ~74 USD per signup per year,
AlgoAlpha nets ~173 USD year one), and the commission only ever pays on
revenue that actually arrived, so it is self-funding by construction. The
deal stays strong for the creator because the upside is the commission: a
converting channel out-earns any flat sponsorship within months, and the
copy stacks the monthly retainer potential (rate x 4 videos) so the offer
still reads big.

Floor 200 USD keeps micro-channel quotes credible; cap 5,000 USD bounds
mega-channel risk (cap reached at ~1.25M); the 4-paid-videos-per-month cap
bounds total monthly exposure (worst case 20,000 USD/month at the cap) and
is framed in copy as opportunity ("up to four paid videos a month").
Reference points: 50k -> 200, 100k -> 400, 250k -> 1,000, 500k -> 2,000,
1M -> 4,000. The legacy copy's case study (4 videos, 14,000 USD retainer =
3,500/video) maps to a ~875k channel, inside its stated 250k-1M band, so
that claim stays true.

A personalized number is quoted only when audience_size is known and
>= MIN_QUOTE_AUDIENCE; otherwise the copy falls back to the generic range
and asks for the channel link.

IMPORTANT: the formula is INTERNAL ONLY. Prospect-facing strings state the
offer (the number / the range) and never the rate, the per-subscriber math,
or their audience figure next to the quote — we calculate on our end. The
reply-draft context carries an explicit do-not-explain guardrail.

Copy style contract (matches algoalpha variants voice): no apostrophes, no
em-dashes, no typographic quotes, no exclamation marks, no emojis.
"""
from __future__ import annotations

RATE_PER_1K_USD = 4
FLOOR_USD = 200
CAP_USD = 5000
COMMISSION_PCT = 30
MIN_QUOTE_AUDIENCE = 10_000
MAX_PAID_VIDEOS_PER_MONTH = 4

# Prose form of the monthly cap, so copy reads "four" while the math uses 4.
_NUM_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
_CAP_WORD = _NUM_WORDS.get(MAX_PAID_VIDEOS_PER_MONTH, str(MAX_PAID_VIDEOS_PER_MONTH))


def retainer_usd(audience_size) -> int | None:
    """Per-video retainer in USD, or None when the audience is unknown or
    below the quote threshold (the copy then uses the generic range)."""
    try:
        s = int(audience_size or 0)
    except (TypeError, ValueError):
        return None
    if s < MIN_QUOTE_AUDIENCE:
        return None
    raw = RATE_PER_1K_USD * s / 1000
    return int(min(max(round(raw / 50) * 50, FLOOR_USD), CAP_USD))


def _usd(n: int) -> str:
    return f"{n:,}"


def audience_approx(audience_size) -> str:
    """Human-rounded audience for copy: 45k, 270k, 1.3M. Never falsely
    precise — scraped counts drift."""
    s = int(audience_size or 0)
    if s >= 1_000_000:
        return f"{s / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if s >= 100_000:
        return f"{round(s / 10_000) * 10}k"
    return f"{max(round(s / 5_000) * 5, 5)}k"


def retainer_quote(audience_size) -> str:
    """Inline clause for the offer sentence. Always non-empty. States the
    offer only — never the rate behind it."""
    r = retainer_usd(audience_size)
    if r is not None:
        return f"a flat {_usd(r)} USD per video"
    return (f"a flat per video retainer, {_usd(FLOOR_USD)} USD up to "
            f"{_usd(CAP_USD)} USD, sized to your channel")


def retainer_math(audience_size) -> str:
    """The offer paragraph (step 3). States the locked number when the
    audience is known, otherwise the range + an ask for the channel link.
    Never shows the calculation — that stays on our end."""
    r = retainer_usd(audience_size)
    if r is not None:
        monthly = r * MAX_PAID_VIDEOS_PER_MONTH
        return (f"Your rate is locked on our end: we pay you {_usd(r)} USD per video, "
                f"flat, up to {_CAP_WORD} paid videos a month. That is up to "
                f"{_usd(monthly)} USD a month in retainer, paid up front, win or lose, "
                f"before a single viewer signs up.")
    return (f"Your rate gets locked before you post anything: we pay you a flat "
            f"retainer between {_usd(FLOOR_USD)} USD and {_usd(CAP_USD)} USD per video, "
            f"sized to your channel, up to {_CAP_WORD} paid videos a month. "
            f"Paid up front, win or lose.\n\n"
            f"Reply with your channel link and I send your exact number.")


def offer_context(audience_size) -> str:
    """Plain-text terms summary injected into reply drafting, so responses
    quote the same numbers the outreach promised. Carries the guardrail that
    the calculation behind the number is never explained to the prospect."""
    r = retainer_usd(audience_size)
    if r is not None:
        retainer_line = (f"flat retainer of {_usd(r)} USD per video featuring AlgoAlpha, "
                         f"already locked for this creator, covering up to "
                         f"{_CAP_WORD} paid videos a month (up to "
                         f"{_usd(r * MAX_PAID_VIDEOS_PER_MONTH)} USD a month)")
    else:
        retainer_line = (f"flat retainer per video between {_usd(FLOOR_USD)} USD and "
                         f"{_usd(CAP_USD)} USD, sized to their channel, covering up to "
                         f"{_CAP_WORD} paid videos a month; their exact number "
                         f"is not locked yet, so ask for the channel link and say we will "
                         f"confirm it on our end")
    return (f"AlgoAlpha creator offer terms for this prospect: {retainer_line}, paid "
            f"whether or not anyone signs up. On top, {COMMISSION_PCT} percent lifetime "
            f"commission on every paid signup, recurring every month they stay (average "
            f"signup spends 247 USD in year one, about 74 USD per signup per year to the "
            f"creator). Free lifetime VIP access and one custom branded indicator included. "
            f"Five partner slots per quarter. The retainer is calculated on our end: never "
            f"explain or reveal how the number is set, never state a per subscriber rate or "
            f"mention their audience size next to the number. If they ask how it was "
            f"calculated or push to negotiate, say rates are set internally for channel fit "
            f"and steer to the call.")
