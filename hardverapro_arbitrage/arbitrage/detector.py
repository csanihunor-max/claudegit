"""Decide whether a single listing counts as a deal.

Two independent comparisons feed this, checked in order:

1. Used-median (PRIMARY): is this priced well below what other resellers
   on hardverapro.hu ask for the same item right now? This is the
   original, better-trusted signal — real comparables from the same
   marketplace, same population of sellers.
2. Retail (secondary, fallback only): is this priced far below what a new
   one costs? Only consulted when the used-median comparison didn't
   qualify — either too few comparable listings exist yet, or the
   used-median discount fell short of its own threshold. This exists
   specifically for items that rarely get re-listed identically (camera
   gear, anything with heavy model/variant diversity), where used-median
   alone has nothing to compare against.

Retail's threshold defaults much higher than used-median's, because
"cheaper than brand new" is true of nearly every used item — it only
means something once the gap is large.
"""
from __future__ import annotations

from ..config import Config
from ..models import Deal, Listing, RetailPrice
from ..pricing.market import market_reference_price


def evaluate(
    listing: Listing,
    recent_prices: list[float],
    config: Config,
    retail_price: RetailPrice | None = None,
) -> Deal | None:
    if config.max_price and listing.price > config.max_price:
        return None

    used_reference = market_reference_price(
        recent_prices, config.min_samples_for_reference, max_spread_ratio=config.max_group_spread_ratio
    )
    used_discount = None
    if used_reference is not None and used_reference > 0:
        used_discount = (used_reference - listing.price) / used_reference

    retail_discount = None
    trusted_retail = (
        retail_price is not None
        and retail_price.price > 0
        and retail_price.match_confidence >= config.retail_min_match_confidence
    )
    if trusted_retail:
        retail_discount = (retail_price.price - listing.price) / retail_price.price

    # Primary path: used-median clears its own threshold.
    if used_discount is not None and used_discount >= config.deal_discount_threshold:
        return Deal(
            listing=listing,
            basis="used_median",
            market_reference_price=used_reference,
            discount_fraction=used_discount,
            sample_size=len(recent_prices),
            retail_reference_price=retail_price.price if trusted_retail else None,
            retail_discount_fraction=retail_discount,
            retail_match_confidence=retail_price.match_confidence if trusted_retail else None,
        )

    # Fallback path: used-median didn't qualify (or couldn't be computed
    # at all), but retail does. Still attach whatever used-market info
    # exists, even non-qualifying, as supplementary context.
    if retail_discount is not None and retail_discount >= config.retail_deal_threshold:
        return Deal(
            listing=listing,
            basis="retail",
            market_reference_price=used_reference,
            discount_fraction=used_discount,
            sample_size=len(recent_prices),
            retail_reference_price=retail_price.price,
            retail_discount_fraction=retail_discount,
            retail_match_confidence=retail_price.match_confidence,
        )

    return None
