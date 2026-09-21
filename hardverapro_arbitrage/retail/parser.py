"""Parse árukereső.hu search-result HTML into retail price candidates.

UNVERIFIED — same situation hardverapro.hu's own parser started in: this
was written before network access to arukereso.hu was available, so
neither the search URL pattern nor `_SELECTORS` below have been run
against a real page. Before trusting any retail comparison:

    python -m hardverapro_arbitrage.tools.inspect_retail_html <url-or-file>

(mirrors `inspect_html` for hardverapro.hu — see that tool and
`scraper/parser.py`'s docstring for the fix-it workflow; it's the same
process against a different site.)

Returns raw (title, price, currency, url) candidates for a search query —
picking which one, if any, is the same product as a given listing is
`retail/matcher.py`'s job, not this module's.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# GUESSED. Árukereső's product search is commonly reached this way, but
# unverified — check the real query param via a browser search first.
SEARCH_URL_TEMPLATE = "https://www.arukereso.hu/Search.php?st={query}"

# GUESSED selectors — a price-comparison listing card, its title/link, and
# its "from" price. Fix against real markup with the inspect tool above.
_SELECTORS = {
    "product_card": "div.talalati_sor",
    "title": "h3 a",
    "link": "h3 a",
    "price": "div.arlista_ar, span.price",
}

_NON_DIGIT_RE = re.compile(r"[^\d]")


def build_search_url(query: str) -> str:
    return SEARCH_URL_TEMPLATE.format(query=quote_plus(query))


def _parse_price(text: str) -> float | None:
    text = text.strip()
    if not text:
        return None
    digits = _NON_DIGIT_RE.sub("", text)
    if not digits:
        return None
    return float(digits)


def parse_search_results(html: str, base_url: str = "https://www.arukereso.hu") -> list[tuple[str, float, str, str]]:
    """Returns (title, price, currency, url) tuples — currency is always
    "HUF" (árukereső is Hungary-only). A card that doesn't parse cleanly is
    skipped rather than raising, same policy as the hardverapro parser.
    """
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select(_SELECTORS["product_card"])
    if not cards:
        logger.warning(
            "0 product cards matched selector %r on an árukereső page — "
            "the site markup likely changed or the search URL pattern is "
            "wrong. See this module's docstring.",
            _SELECTORS["product_card"],
        )

    results: list[tuple[str, float, str, str]] = []
    for card in cards:
        title_el = card.select_one(_SELECTORS["title"])
        price_el = card.select_one(_SELECTORS["price"])
        link_el = card.select_one(_SELECTORS["link"])
        if title_el is None or price_el is None or link_el is None:
            continue

        price = _parse_price(price_el.get_text())
        if price is None:
            continue

        href = link_el.get("href", "")
        if not href:
            continue
        url = href if href.startswith("http") else f"{base_url.rstrip('/')}/{href.lstrip('/')}"

        results.append((title_el.get_text(strip=True), price, "HUF", url))

    return results
