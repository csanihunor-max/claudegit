"""Decide whether a single listing counts as a deal: is it priced well
below what other resellers on hardverapro.hu ask for the same item right
now? The reference price is the median of other recent listings of the
same normalized item title — real comparables from the same marketplace,
same population of sellers.

(An earlier version of this also fell back to comparing against
árukereső.hu retail prices when there wasn't enough used-listing history.
Dropped: árukereső.hu sits behind a Cloudflare JS challenge that a plain
HTTP scraper can never pass, confirmed by fetching it directly and getting
a "Just a moment..." challenge page instead of any product markup — not a
selector problem, a hard block. See git history if reviving retail
comparison against a different, actually-scrapable source.)
"""
from __future__ import annotations

from ..config import Config
from ..models import Deal, Listing
from ..pricing.market import market_reference_price


def evaluate(listing: Listing, recent_prices: list[float], config: Config) -> Deal | None:
    if config.max_price and listing.price > config.max_price:
        return None

    reference = market_reference_price(
        recent_prices, config.min_samples_for_reference, max_spread_ratio=config.max_group_spread_ratio
    )
    if reference is None or reference <= 0:
        return None

    discount = (reference - listing.price) / reference
    if discount < config.deal_discount_threshold:
        return None
    if discount >= config.max_plausible_discount_fraction:
        # A real, genuinely-priced used item essentially never sells at
        # less than half its own recent resale median -- when the math
        # says otherwise, a bad title match or a data entry error in one
        # of the listings is far more likely than an extraordinary
        # bargain. See config.py's max_plausible_discount_fraction for
        # the real examples this is built from.
        return None

    return Deal(
        listing=listing,
        market_reference_price=reference,
        discount_fraction=discount,
        sample_size=len(recent_prices),
    )
