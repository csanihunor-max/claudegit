"""Parse hardverapro.hu search-result HTML into Listing objects.

Selectors verified against real hardverapro.hu category/search pages
(fetched 2026-09-21). Each ad card is a `<li class="media" data-uadid="...">`
— the `data-uadid` attribute is the site's own stable ad id, so we read it
directly instead of trying to regex it out of the URL. A "featured"
("Előresorolva") card is `<li class="media featured" ...>` and additionally
repeats the price inside the title column; we read the price from
`.uad-col-price` specifically to avoid picking up that duplicate. A
"jegelve" ("on ice") card, `<li class="media uad-status-iced" ...>`, means
the seller has marked it reserved for another buyer — excluded entirely
(see `_is_iced`), not just flagged, since it's not actually available and
its price shouldn't count as a market comparable either.

If the site markup changes later, `python -m
hardverapro_arbitrage.tools.inspect_html <url-or-file>` shows exactly what
this extracts, to compare against the page and fix `_SELECTORS` below.

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
# listing card), or with the inspect_html tool (see module docstring).
_SELECTORS = {
    "listing_card": "li.media[data-uadid]",  # one ad card in the results list
    "title": "div.uad-col-title h1 a",  # also doubles as the ad's link
    "price": "div.uad-col-price .uad-price",  # NOT .uad-col-title .uad-price (duplicated on featured ads)
    "location": "div.uad-cities",
}

_NON_DIGIT_RE = re.compile(r"[^\d]")


def _parse_price(text: str) -> tuple[float, str] | None:
    text = text.strip()
    if not text:
        return None
    digits = _NON_DIGIT_RE.sub("", text)
    if not digits:
        return None
    return float(digits), "HUF"


def _is_iced(card: Tag) -> bool:
    """"Jegelve" ("on ice", marked with a snowflake icon and that literal
    word on the site) means the seller has told the site this item is
    reserved for another buyer — pending a sale, not actually available.
    Marked on the card itself (`<li class="media uad-status-iced" ...>`)
    and again on the price element (`uad-price-iced`); the card-level
    class is the more direct signal.

    Excluded entirely rather than just flagged, because its price
    shouldn't count as a market comparable either: a reserved item's
    asking price reflects an already-agreed (or about-to-be) deal, not
    what the item is currently obtainable for.
    """
    return "uad-status-iced" in card.get("class", [])


def _parse_card(card: Tag, base_url: str) -> Listing | None:
    listing_id = card.get("data-uadid")

    if _is_iced(card):
        logger.debug("skipping jegelve (reserved) listing %s", listing_id)
        return None

    title_el = card.select_one(_SELECTORS["title"])
    price_el = card.select_one(_SELECTORS["price"])

    if not listing_id or title_el is None or price_el is None:
        logger.debug("skipping card missing id/title/price: %s", card)
        return None

    href = title_el.get("href", "")
    if not href:
        return None
    url = href if href.startswith("http") else f"{base_url.rstrip('/')}/{href.lstrip('/')}"

    price_parsed = _parse_price(price_el.get_text())
    if price_parsed is None:
        logger.debug("skipping card with unparseable price: %r", price_el.get_text())
        return None
    price, currency = price_parsed

    location_el = card.select_one(_SELECTORS["location"])
    location = location_el.get_text(strip=True) if location_el else None

    return Listing(
        listing_id=str(listing_id),
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
