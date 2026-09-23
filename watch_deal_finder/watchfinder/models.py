"""Plain data types shared by sources, storage, notifications and the dashboard.

A Listing deliberately has no seller fields: we only ever keep what describes
the item itself (title, price, where it is, a thumbnail), never who sells it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


@dataclass(frozen=True)
class Listing:
    source: str
    listing_id: str
    title: str
    price: float | None  # in `currency`; None when the ad has no numeric price
    currency: str
    url: str
    location: str | None = None
    thumbnail_url: str | None = None
    category: str | None = None  # e.g. "Divat, ruházat > Férfi ruházat és kiegészítők > Karórák"

    @property
    def key(self) -> tuple[str, str]:
        return (self.source, self.listing_id)


@dataclass
class SearchResult:
    """What one source returned for one configured search.

    `complete` is True only when every sub-query returned its full result set on
    the page(s) we fetched. Only then does "not in the results" mean "gone".
    """

    listings: list[Listing] = field(default_factory=list)
    complete: bool = True


class EventKind(str, Enum):
    NEW = "new"
    PRICE_DROP = "price_drop"


@dataclass(frozen=True)
class Event:
    kind: EventKind
    search_name: str
    listing: Listing
    price_huf: int | None
    old_price_huf: int | None = None
