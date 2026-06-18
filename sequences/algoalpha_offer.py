"""algoalpha_offer.py — the AlgoAlpha creator-proposal formula, one place.

THE FORMULA (hard-coded, do not deviate):
    retainer_per_video = round_to_10( 10 USD x AVG_VIEWS / 1000 )
    AVG_VIEWS = the average views of the creator's LAST 10 videos
    plus 30 percent lifetime commission on every paid signup.

So a creator whose last 10 videos average 50,000 views is paid 500 USD per
video (10 USD per 1,000 views), win or lose, plus 30 percent lifetime
commission. The per-video number scales directly with real, recent reach
(views), not subscriber count, because views are what a sponsored slot
actually delivers.

AVG_VIEWS is captured at scrape time (the YouTube scraper stores each
prospect's last-10-video average in custom_fields.avg_views_10) and is
re-figured whenever the channel is re-scraped, so the average used for an
offer is the freshest one we have for that creator. A personalized number
is quoted only when avg_views_10 is known and >= MIN_QUOTE_VIEWS; otherwise
the copy asks for the channel link and says we confirm the exact number on
our end.

INTERNAL ONLY: prospect-facing strings state the per-video number and the 30
percent commission, and NEVER the 10-per-1000-views rate, the view math, or
the creator's average-views figure next to the number. We calculate on our
end. The reply-draft context carries an explicit do-not-explain guardrail.

Copy style contract (matches algoalpha variants voice): no apostrophes, no
em-dashes, no typographic quotes, no exclamation marks, no emojis.
"""
from __future__ import annotations

RATE_PER_1K_VIEWS_USD = 10          # 10 USD per 1,000 average views. Do not change.
COMMISSION_PCT = 30                 # 30 percent lifetime commission. Do not change.
MIN_QUOTE_VIEWS = 2_000             # below this avg, quote the generic offer instead
MAX_PAID_VIDEOS_PER_MONTH = 4       # operational cap on paid slots (framed as opportunity)

_NUM_WORDS = {2: "two", 3: "three", 4: "four", 5: "five", 6: "six"}
_CAP_WORD = _NUM_WORDS.get(MAX_PAID_VIDEOS_PER_MONTH, str(MAX_PAID_VIDEOS_PER_MONTH))


def retainer_usd(avg_views) -> int | None:
    """Per-video retainer in USD = 10 USD per 1,000 of the last-10-video
    average views, rounded to the nearest 10. None when avg_views is unknown
    or below the quote threshold (the copy then uses the generic offer)."""
    try:
        v = int(avg_views or 0)
    except (TypeError, ValueError):
        return None
    if v < MIN_QUOTE_VIEWS:
        return None
    raw = RATE_PER_1K_VIEWS_USD * v / 1000
    return int(round(raw / 10) * 10)


def _usd(n: int) -> str:
    return f"{n:,}"


def avg_views_approx(avg_views) -> str:
    """Human-rounded average views for INTERNAL notes only: 45k, 270k, 1.3M."""
    try:
        v = int(avg_views or 0)
    except (TypeError, ValueError):
        return "an unknown number of"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".") + "M"
    if v >= 1_000:
        return f"{round(v / 1000)}k"
    return str(v)


def retainer_quote(avg_views) -> str:
    """Inline clause for the offer sentence. Always non-empty. States the
    offer number only, never the rate behind it."""
    r = retainer_usd(avg_views)
    if r is not None:
        return f"a flat {_usd(r)} USD per video"
    return "a flat per video retainer sized to your channel"


def retainer_math(avg_views) -> str:
    """The offer paragraph (step 3). States the locked number when the average
    views are known, otherwise asks for the channel link. Never shows the
    calculation or the views figure."""
    r = retainer_usd(avg_views)
    if r is not None:
        monthly = r * MAX_PAID_VIDEOS_PER_MONTH
        return (f"Your rate is locked on our end: we pay you {_usd(r)} USD per video, "
                f"flat, up to {_CAP_WORD} paid videos a month. That is up to "
                f"{_usd(monthly)} USD a month in retainer, paid up front, win or lose, "
                f"before a single viewer signs up.")
    return ("Your rate gets locked before you post anything: we pay you a flat per video "
            f"retainer sized to your channel, up to {_CAP_WORD} paid videos a month, paid "
            "up front, win or lose.\n\n"
            "Reply with your channel link and I send your exact number.")


def offer_context(avg_views) -> str:
    """Plain-text terms summary injected into reply drafting, so responses
    quote the same numbers the outreach promised. Carries the guardrail that
    the calculation behind the number is never explained to the prospect."""
    r = retainer_usd(avg_views)
    if r is not None:
        retainer_line = (f"flat retainer of {_usd(r)} USD per video featuring AlgoAlpha, "
                         f"already locked for this creator, covering up to "
                         f"{_CAP_WORD} paid videos a month (up to "
                         f"{_usd(r * MAX_PAID_VIDEOS_PER_MONTH)} USD a month)")
    else:
        retainer_line = (f"flat retainer per video sized to their channel, covering up to "
                         f"{_CAP_WORD} paid videos a month; their exact number is not locked "
                         f"yet, so ask for the channel link and say we will confirm it on our end")
    return (f"AlgoAlpha creator offer terms for this prospect: {retainer_line}, paid "
            f"whether or not anyone signs up. On top, {COMMISSION_PCT} percent lifetime "
            f"commission on every paid signup, recurring every month they stay (average "
            f"signup spends 247 USD in year one, about 74 USD per signup per year to the "
            f"creator). Free lifetime VIP access and one custom branded indicator included. "
            f"Five partner slots per quarter. The retainer is calculated on our end as a fixed "
            f"rate per thousand of recent average views: never explain or reveal how the number "
            f"is set, never state the per view or per thousand rate, and never mention their "
            f"view counts or average views next to the number. If they ask how it was "
            f"calculated or push to negotiate, say rates are set internally for channel fit "
            f"and steer to the call.")


# ── Backward-compatibility shim ──────────────────────────────────────────────
# Old call sites passed audience_size (subscribers). The offer is now based on
# the last-10-video average VIEWS; callers should pass avg_views. This alias
# keeps older imports working but expects views, not subscribers.
def audience_approx(avg_views) -> str:  # legacy alias
    return avg_views_approx(avg_views)
