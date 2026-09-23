"""The interface every marketplace source implements.

To add a site: subclass Source, implement `search` (and ideally `is_gone`),
then register it in `watchfinder/sources/__init__.py` and `config.KNOWN_SOURCES`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from ..config import SearchConfig
from ..models import Listing, SearchResult


class SourceError(RuntimeError):
    """A source could not produce results this pass (network, blocked, markup changed)."""


class Source(ABC):
    name: str = ""
    label: str = ""  # human-readable, shown in alerts and the dashboard

    @abstractmethod
    def search(self, search: SearchConfig) -> SearchResult:
        """Return the current listings for all keywords of one configured search.

        Must raise SourceError rather than return an empty result when the fetch
        failed; an empty result is taken to mean "nothing listed right now".
        """

    def is_gone(self, listing: Listing) -> bool | None:
        """Check a single listing directly. True = removed, False = still up, None = can't tell."""
        return None
