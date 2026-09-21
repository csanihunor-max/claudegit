"""Hardverapro arbitrage scraper.

Polls hardverapro.hu classifieds listings on a schedule, tracks prices per
normalized item, and flags listings priced well below the item's own
recent second-hand market price (a rolling reference computed from the
scraper's own price history) as arbitrage opportunities.
"""

__version__ = "0.1.0"
