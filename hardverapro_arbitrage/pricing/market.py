"""Compute a "second-hand market price" reference for an item from the
scraper's own price history — the median of recent listings for the same
normalized item. Median (not mean) so one wildly over/underpriced outlier
listing doesn't drag the reference around.
"""
from __future__ import annotations

import statistics


def market_reference_price(recent_prices: list[float], min_samples: int) -> float | None:
    """Returns None when there isn't enough history yet to trust a
    reference price (too easy to "arbitrage" against a sample of one).
    """
    if len(recent_prices) < min_samples:
        return None
    return statistics.median(recent_prices)
