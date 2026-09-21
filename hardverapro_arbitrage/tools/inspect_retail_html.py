"""Check retail/parser.py's guessed selectors and search-URL pattern
against a REAL árukereső.hu page — mirrors inspect_html.py for
hardverapro.hu. Neither has been run against real markup yet.

Usage:

    # search live for a query...
    python -m hardverapro_arbitrage.tools.inspect_retail_html "Steam Deck OLED 512GB"

    # ...or against a URL or a page you saved locally
    python -m hardverapro_arbitrage.tools.inspect_retail_html "https://www.arukereso.hu/..."
    python -m hardverapro_arbitrage.tools.inspect_retail_html path/to/saved_page.html

Prints every product candidate extracted, plus — when given a query
string rather than a URL/file — the match score against that same query,
so you can see in one step both whether the parser found the right
products AND whether the matcher would pick the right one.
"""
from __future__ import annotations

import sys

from ..config import Config
from ..retail.client import ArukeresoClient
from ..retail.matcher import score_match
from ..retail.parser import build_search_url, parse_search_results


def _load_html(source: str) -> tuple[str, str | None]:
    """Returns (html, query_used_or_None)."""
    if source.startswith("http://") or source.startswith("https://"):
        with ArukeresoClient(Config()) as client:
            return client.get(source), None
    if source.endswith(".html") or source.endswith(".htm"):
        with open(source, encoding="utf-8") as fh:
            return fh.read(), None
    # treat as a search query
    with ArukeresoClient(Config()) as client:
        return client.get(build_search_url(source)), source


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        print(__doc__)
        return 2

    html, query = _load_html(argv[0])
    candidates = parse_search_results(html)

    print(f"\n{len(candidates)} product candidate(s) parsed.\n")
    for title, price, currency, url in candidates:
        line = f"- {title}\n    price: {price:,.0f} {currency}\n    url:   {url}"
        if query:
            line += f"\n    match score vs {query!r}: {score_match(query, title):.2f}"
        print(line)
        print()

    if not candidates:
        print(
            "No candidates extracted — see this module's docstring "
            "(`python -m hardverapro_arbitrage.tools.inspect_retail_html` "
            "with no args) and retail/parser.py's docstring for what to fix."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
