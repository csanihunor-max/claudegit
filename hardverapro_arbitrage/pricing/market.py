"""Compute a "second-hand market price" reference for an item from the
scraper's own price history — the median of recent listings for the same
normalized item. Median (not mean) so one wildly over/underpriced outlier
listing doesn't drag the reference around.
"""
from __future__ import annotations

import statistics


def market_reference_price(recent_prices: list[float], min_samples: int, max_spread_ratio: float = 3.0) -> float | None:
    """Returns None when there isn't enough history yet to trust a
    reference price (too easy to "arbitrage" against a sample of one), or
    when the comparables disagree with each other far more than a single
    well-defined product ever should.

    That second case is real, not theoretical: a generic title like "PS4
    játékok" ("PS4 games") normalizes identically across listings that are
    actually bundles of wildly different game counts/titles — different
    real items that just happen to share vague wording. Checked against
    both known-genuine groups (a specific console/headset model, ~1.5x
    max/min across independent sellers) and known-spurious ones (exactly
    this games-bundle case, ~3.6-4.1x): 3.0 sits cleanly between them.
    This is a heuristic, not a guarantee — a deliberately conservative
    dividing line, not a claim that every group under it is genuinely
    comparable or every group over it isn't.
    """
    if len(recent_prices) < min_samples:
        return None

    lo, hi = min(recent_prices), max(recent_prices)
    if lo > 0 and hi / lo > max_spread_ratio:
        return None

    return statistics.median(recent_prices)
