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
class RetailPrice:
    """The current lowest new price found for an item on a retail
    price-comparison site, and how confident the matcher is that the
    matched product is really the same item as the listing being compared.
    """

    product_title: str
    price: float
    currency: str
    url: str
    match_confidence: float  # 0..1


@dataclass(frozen=True)
class Deal:
    """A listing flagged as priced well below some reference price.

    `basis` says which comparison qualified it — "used_median" (the
    primary signal: priced below what other resellers on hardverapro.hu
    ask for the same item) or "retail" (a secondary, fallback signal:
    priced far below what a new one costs, used only when there wasn't
    enough used-listing history to trust a used-median comparison, or that
    comparison didn't clear its own threshold). Both sets of fields can be
    populated regardless of `basis` — e.g. a used_median deal can still
    carry retail info for display — but `basis` says which one is why this
    is a Deal at all.
    """

    listing: Listing
    basis: str  # "used_median" | "retail"

    market_reference_price: float | None = None
    discount_fraction: float | None = None  # e.g. 0.35 == 35% below the used-market reference
    sample_size: int = 0

    retail_reference_price: float | None = None
    retail_discount_fraction: float | None = None
    retail_match_confidence: float | None = None

    @property
    def savings(self) -> float:
        """Savings under whichever comparison qualified this as a deal."""
        if self.basis == "used_median" and self.market_reference_price is not None:
            return self.market_reference_price - self.listing.price
        if self.retail_reference_price is not None:
            return self.retail_reference_price - self.listing.price
        return 0.0


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
