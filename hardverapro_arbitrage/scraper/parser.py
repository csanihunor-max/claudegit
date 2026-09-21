"""Parse hardverapro.hu search-result HTML into Listing objects.

IMPORTANT — the CSS selectors below are BEST-EFFORT GUESSES, not verified
against the live site. This sandbox has no network access to hardverapro.hu,
so nothing here has been run against real HTML. Before relying on this:

    1. Save a real search-result page's HTML locally.
    2. Run `parse_search_results()` against it and compare the output to
       what you see in the browser.
    3. Fix the selectors in `_SELECTORS` below to match — everything else
       (grouping, pricing, arbitrage detection) is independent of them.

All parsing is defensive: a listing card that doesn't match the expected
shape is skipped and logged rather than crashing the whole scrape cycle.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup, Tag

from ..models import Listing

logger = logging.getLogger(__name__)

# Centralized so a site markup change means editing one place. Update these
# once you've inspected real page source (browser devtools → Inspect on a
# listing card).
_SELECTORS = {
    "listing_card": "div.media.media-image-with-icon",  # one ad card in the results list
    "title": "div.media-heading a",
    "price": "div.media-price",
    "location": "div.media-city",
    "link": "div.media-heading a",
}

_PRICE_NUMBER_RE = re.compile(r"[\d\s .,]+")
_NON_DIGIT_RE = re.compile(r"[^\d]")
_LISTING_ID_RE = re.compile(r"-t(\d+)(?:[/?#]|$)")


def _extract_listing_id(url: str) -> str | None:
    """hardverapro ad URLs end in something like '...-tNNNNNNN'; NNNNNNN is
    the stable ad id we key storage on. Falls back to the full URL if the
    pattern isn't found, so a markup change degrades to "keyed by URL"
    rather than dropping listings silently.
    """
    match = _LISTING_ID_RE.search(url)
    return match.group(1) if match else None


def _parse_price(text: str) -> tuple[float, str] | None:
    text = text.strip()
    if not text:
        return None
    currency = "HUF" if ("Ft" in text or "HUF" in text) else "HUF"
    digits = _NON_DIGIT_RE.sub("", text)
    if not digits:
        return None
    return float(digits), currency


def _parse_card(card: Tag, base_url: str) -> Listing | None:
    title_el = card.select_one(_SELECTORS["title"])
    price_el = card.select_one(_SELECTORS["price"])
    link_el = card.select_one(_SELECTORS["link"])

    if title_el is None or price_el is None or link_el is None:
        logger.debug("skipping card missing title/price/link: %s", card)
        return None

    href = link_el.get("href", "")
    if not href:
        return None
    url = href if href.startswith("http") else f"{base_url.rstrip('/')}/{href.lstrip('/')}"

    price_parsed = _parse_price(price_el.get_text())
    if price_parsed is None:
        logger.debug("skipping card with unparseable price: %r", price_el.get_text())
        return None
    price, currency = price_parsed

    listing_id = _extract_listing_id(url) or url

    location_el = card.select_one(_SELECTORS["location"])
    location = location_el.get_text(strip=True) if location_el else None

    return Listing(
        listing_id=listing_id,
        url=url,
        title=title_el.get_text(strip=True),
        price=price,
        currency=currency,
        location=location,
        seen_at=datetime.now(timezone.utc),
    )


def parse_search_results(html: str, base_url: str = "https://hardverapro.hu") -> list[Listing]:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(_SELECTORS["listing_card"])
    if not cards:
        logger.warning(
            "0 listing cards matched selector %r — the site markup likely "
            "changed, or this isn't a search-results page. See the module "
            "docstring for how to fix the selectors.",
            _SELECTORS["listing_card"],
        )

    listings: list[Listing] = []
    for card in cards:
        listing = _parse_card(card, base_url)
        if listing is not None:
            listings.append(listing)
    return listings
