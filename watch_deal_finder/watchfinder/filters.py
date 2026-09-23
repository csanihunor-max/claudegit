"""Deciding which scraped listings are real candidates for a search.

All matching is case- and accent-insensitive, so "raketa" matches "Rakéta"
and the blacklist word "okosóra" also catches "OKOSORA".
"""

from __future__ import annotations

import re
import unicodedata
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from .config import AppConfig, SearchConfig
    from .models import Listing

_NON_WORD = re.compile(r"[^0-9a-z]+")


def normalize(text: str) -> str:
    """Lowercase, strip accents (ő -> o, ű -> u) and collapse punctuation to single spaces."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_WORD.sub(" ", stripped).strip()


def blacklisted(title: str, blacklist: Iterable[str]) -> str | None:
    """Return the blacklist word found in the title, or None.

    Substring match on purpose: "gyerek" should also catch "gyerekóra".
    """
    norm_title = normalize(title)
    for word in blacklist:
        norm_word = normalize(word)
        if norm_word and norm_word in norm_title:
            return word
    return None


def title_matches(title: str, keywords: Iterable[str]) -> bool:
    """True if every word of at least one keyword appears in the title.

    Sites also match on the ad body, so "raketa" returns rocket stoves and
    vacuum cleaners; requiring the keyword in the title removes most of that.
    """
    title_words = normalize(title).split()
    for keyword in keywords:
        parts = normalize(keyword).split()
        # Each keyword word must start a title word: "raketa" matches "Rakéta" and
        # "Raketas", but "omega" does not match "Homega".
        if parts and all(any(w.startswith(p) for w in title_words) for p in parts):
            return True
    return False


def category_allowed(category: str | None, allowed: Iterable[str]) -> bool:
    """With an empty allow-list, or a listing with no category info, everything passes."""
    allowed = [normalize(a) for a in allowed if a]
    if not allowed or not category:
        return True
    norm = normalize(category)
    return any(a in norm for a in allowed)


def filter_listings(listings: Iterable[Listing], search: SearchConfig, config: AppConfig) -> list[Listing]:
    """Drop blacklisted, off-topic and wrong-category listings. Max price is NOT applied here:
    over-budget listings are still stored (a later price drop can bring them under budget)."""
    kept: list[Listing] = []
    for listing in listings:
        if blacklisted(listing.title, config.blacklist):
            continue
        if config.title_must_match and not title_matches(listing.title, search.keywords):
            continue
        if not category_allowed(listing.category, config.category_filter):
            continue
        kept.append(listing)
    return kept
