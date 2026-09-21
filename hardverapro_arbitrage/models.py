"""Core data types passed between pipeline stages."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone


@dataclass(frozen=True)
class Listing:
    """A single scraped classifieds listing, as it exists right now."""

    listing_id: str  # hardverapro's own ad id, stable across re-scrapes
    url: str
    title: str
    price: float
    currency: str
    location: str | None
    seen_at: datetime

    @property
    def normalized_key(self) -> str:
        from .scraper.normalize import normalize_title

        return normalize_title(self.title)


@dataclass(frozen=True)
class Deal:
    """A listing flagged as priced well below the median of other recent
    listings of the same item on hardverapro.hu itself (see
    `arbitrage/detector.py`).
    """

    listing: Listing

    market_reference_price: float
    discount_fraction: float  # e.g. 0.35 == 35% below the market reference
    sample_size: int

    @property
    def savings(self) -> float:
        return self.market_reference_price - self.listing.price


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
