"""Decide whether a single listing is priced well enough below its item's
market reference to count as an arbitrage deal.
"""
from __future__ import annotations

from ..config import Config
from ..models import Deal, Listing
from ..pricing.market import market_reference_price


def evaluate(listing: Listing, recent_prices: list[float], config: Config) -> Deal | None:
    if config.max_price and listing.price > config.max_price:
        return None

    reference = market_reference_price(recent_prices, config.min_samples_for_reference)
    if reference is None or reference <= 0:
        return None

    discount = (reference - listing.price) / reference
    if discount < config.deal_discount_threshold:
        return None

    return Deal(
        listing=listing,
        market_reference_price=reference,
        discount_fraction=discount,
        sample_size=len(recent_prices),
    )
