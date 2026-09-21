"""Tests retail/parser.py's extraction LOGIC against a synthetic fixture
that matches its current (unverified) selectors — see the fixture file's
header and retail/parser.py's module docstring for why it's synthetic,
not real árukereső.hu markup, and how to fix that.
"""
from pathlib import Path

from hardverapro_arbitrage.retail.parser import parse_search_results

FIXTURE = Path(__file__).parent / "fixtures" / "sample_retail_search.html"


def test_parses_valid_cards_and_skips_malformed_ones():
    html = FIXTURE.read_text(encoding="utf-8")
    results = parse_search_results(html)

    assert len(results) == 2  # the third card has no price and is skipped

    title, price, currency, url = results[0]
    assert title == "Valve Steam Deck OLED 512 GB kézikonzol"
    assert price == 280_000
    assert currency == "HUF"
    assert url.startswith("https://www.arukereso.hu/")

    assert results[1][1] == 220_000


def test_no_cards_returns_empty_list_without_raising():
    assert parse_search_results("<html><body>nothing here</body></html>") == []
