"""Check the parser's guessed selectors against a REAL hardverapro.hu page.

This is the one step this project needs before it actually works — it was
built somewhere with no network access to hardverapro.hu, so
scraper/parser.py's CSS selectors were never run against real markup.

Usage, once you're on a machine that can reach the site:

    # straight from a live search-results URL
    python -m hardverapro_arbitrage.tools.inspect_html "https://hardverapro.hu/index.php?st=..."

    # or against a page you saved locally (browser -> Save Page As -> .html)
    python -m hardverapro_arbitrage.tools.inspect_html path/to/saved_page.html

It prints exactly what the parser extracted from the page. Compare that to
what the page actually shows in your browser:

  - 0 listings printed, with a "0 listing cards matched selector" warning:
    the `listing_card` selector in scraper/parser.py's `_SELECTORS` doesn't
    match — open the page's devtools, inspect one ad card, and update it.
  - Listings printed, but titles/prices/urls look wrong or missing: the
    `title`/`price`/`link`/`location` selectors need adjusting instead —
    same file, same dict.

Nothing else in the project depends on these selectors being right, so
fixing them here is the whole job.
"""
from __future__ import annotations

import sys

from ..config import Config
from ..scraper.client import HardveraproClient
from ..scraper.parser import parse_search_results


def _load_html(source: str) -> str:
    if source.startswith("http://") or source.startswith("https://"):
        with HardveraproClient(Config()) as client:
            return client.get(source)
    with open(source, encoding="utf-8") as fh:
        return fh.read()


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2

    html = _load_html(argv[0])
    listings = parse_search_results(html)

    print(f"\n{len(listings)} listing(s) parsed.\n")
    for listing in listings:
        print(f"- {listing.title}")
        print(f"    price:      {listing.price:,.0f} {listing.currency}")
        print(f"    location:   {listing.location}")
        print(f"    url:        {listing.url}")
        print(f"    listing_id: {listing.listing_id}")
        print(f"    grouped as: {listing.normalized_key!r}")
        print()

    if not listings:
        print(
            "No listings extracted — see this module's docstring "
            "(`python -m hardverapro_arbitrage.tools.inspect_html` with no "
            "args) for how to fix the selectors."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
