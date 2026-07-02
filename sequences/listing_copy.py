# -*- coding: utf-8 -*-
"""listing_copy.py — the ONE place that turns a prospect realtor's stored listing
research (`enriched_context.listing`, written by listing_research.py) into
LK Advertising's give-first content-plan offer.

Two consumers import this so the phrasing lives in a single spot:
  - sequence-runner.py -> listing_ps()    : the email-1 P.S. that names one of the
                                            realtor's REAL active listings and
                                            offers a content plan built for it.
  - fulfill-magnets.py -> listing_block() : the full personalised content plan
                                            delivered when they reply the keyword.

Design rules (match seo_copy.py + house style):
  - Never fabricate. Every specific (address, price, type) comes from what
    listing_research actually scraped. If research is missing or thin, both
    functions fall back to a generic, claim-free version so a normal email still
    goes out and still offers a content plan for "one of your listings".
  - Plain human prose. No em dashes.

The `enriched_context.listing` shape this reads:
  {
    "status": "ok" | "no_company" | "no_geo" | "no_results" | "thin_data" | "error",
    "address": "123 Oak St, Austin, TX",   # short, human, from the result title
    "listing_desc": "3 bed single-family" | "",
    "price": "$450,000" | "",
    "source": "zillow.com" | "realtor.com" | own-domain,
    "url": "https://...",
    "city": "Austin",
    "queries": ["..."],
    "engine": "ddg",
    "researched_at": "..."
  }
"""
from __future__ import annotations

# The reply keyword LK's copy asks for. "plan" is the new content-plan trigger;
# the magnet spec also keeps "teardown" so anyone told the old word still works.
KEYWORD = "plan"

# Fallback P.S. when we could not pin a real listing. Still a give-first offer,
# just not address-specific, so an un-researched send is still strong.
_FALLBACK_PS = (
    "P.S. Pick one listing you want more showings on and reply plan. I will send "
    "back a week of ready-to-post content built for that exact property, free."
)


def usable(listing: dict | None) -> bool:
    """True only when research pinned a real listing we can name (an address)."""
    if not isinstance(listing, dict):
        return False
    if listing.get("status") != "ok":
        return False
    return bool((listing.get("address") or "").strip())


def _company(prospect: dict) -> str:
    return (prospect.get("company") or "").strip() or "you"


def _addr(listing: dict) -> str:
    return (listing.get("address") or "").strip()


def _desc_clause(listing: dict) -> str:
    """A short, human descriptor of the listing when we have one, else ''."""
    d = (listing.get("listing_desc") or "").strip()
    p = (listing.get("price") or "").strip()
    if d and p:
        return f"the {d} at {p}"
    if d:
        return f"the {d}"
    if p:
        return f"the one listed at {p}"
    return ""


def listing_ps(listing: dict | None, prospect: dict) -> str:
    """Email-1 P.S. Names the realtor's real listing and offers a content plan
    built for it. Falls back to the generic (still give-first) P.S. when there is
    no usable research, so other clients and un-researched prospects are safe."""
    if not usable(listing):
        return _FALLBACK_PS
    addr = _addr(listing)
    extra = _desc_clause(listing)
    tail = f" ({extra})" if extra else ""
    return (
        f"P.S. I had a look at your site and pulled one of the listings on it, "
        f"{addr}{tail}. Reply {KEYWORD} and I will send you a week of ready-to-post "
        f"content built for that exact property, the posts, a reel script, and one "
        f"ad angle to get it more showings. Free, nothing to install."
    )


def listing_block(listing: dict | None, prospect: dict) -> str:
    """The deliverable body for the reply (the magnet cover email). When we have a
    real listing this is the personalised 7-day content plan; when we do not it is
    the generic version that asks for one listing so it still closes cleanly. Only
    LK's cover_email contains {listing_block}, so this never renders for others."""
    company = _company(prospect)
    if not usable(listing):
        return (
            "Here is how this works. Reply with one listing you want more showings "
            "on, a link or just the address, and I will send back a full week of "
            "content built for that exact property: a Just Listed post, a short "
            "walkthrough reel script, a three-frame story, a neighborhood angle, "
            "and one Meta ad angle to put it in front of local buyers. Written for "
            "the property, not a template. No charge and nothing to install.")
    addr = _addr(listing)
    extra = _desc_clause(listing)
    what = f"{addr}" + (f", {extra.replace('the ', '', 1)}" if extra else "")

    paras = [
        f"Here is the week of content I built for {addr}. Post it as is or hand it "
        f"to whoever runs your socials.",
        (f"Day 1, Just Listed post. Lead with the one thing a local buyer would "
         f"scroll back for about {what}, not the feature list. Three photos, the "
         f"neighborhood name in the first line, and a single call to action: book a "
         f"private tour."),
        (f"Day 2, walkthrough reel (30 to 45 seconds). Open on the strongest room, "
         f"talk to one buyer not a crowd, end on the address and 'DM me for a "
         f"private showing this week'. Vertical video, captions on."),
        (f"Day 3, three-frame story. Frame 1 the exterior with the price, frame 2 "
         f"the best interior detail, frame 3 a poll: 'Would you tour this?' Yes/No. "
         f"The poll is what feeds you the warm names."),
        (f"Day 4, neighborhood angle. One post about the area around {addr}, the "
         f"commute, a coffee spot, the school catchment, whatever a buyer relocating "
         f"actually asks. Sell the life, not the drywall."),
        (f"Day 5, one Meta ad angle. Audience: adults 30 to 55 within about 15 miles "
         f"who show home-buying intent. Creative: the Day 2 reel. Objective: get them "
         f"onto a one-question 'want a private tour of {addr}?' form, not a generic "
         f"valuation page. Budget it small and let the booked tours tell you to scale."),
        (f"Day 6, social proof or urgency. A line about interest so far ('three "
         f"tours booked, two slots left this weekend') if it is true, or a first-"
         f"open-house push if it is not. Never invent the numbers."),
        (f"Day 7, the soft close. 'Still thinking about {addr}? Here is what the "
         f"first month of ownership looks like.' End on book-a-tour again."),
    ]
    paras.append(
        f"That is the free week for one listing. The paid version is where I run the "
        f"Day 5 ad for you and only get paid when it books real seller and buyer "
        f"appointments onto your calendar. Reply with the area you work most and I "
        f"will map what a full month for {company} would look like.")
    return "\n\n".join(paras)
