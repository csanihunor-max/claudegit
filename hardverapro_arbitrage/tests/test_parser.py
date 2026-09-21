"""Tests the parsing/extraction LOGIC against a synthetic fixture that
matches parser.py's current (unverified) selectors. This proves the code
does what it's meant to; it does NOT prove the selectors match the real
site — see the warning in scraper/parser.py.
"""
from pathlib import Path

from hardverapro_arbitrage.scraper.parser import parse_search_results

FIXTURE = Path(__file__).parent / "fixtures" / "sample_search_page.html"


def test_parses_valid_cards_and_skips_malformed_ones():
    html = FIXTURE.read_text(encoding="utf-8")
    listings = parse_search_results(html)

    assert len(listings) == 2  # the third card has no price and is skipped

    first = listings[0]
    assert first.listing_id == "1234567"
    assert first.title == "Eladó iPhone 12 128GB, garanciával"
    assert first.price == 180_000
    assert first.currency == "HUF"
    assert first.location == "Budapest"
    assert first.url.startswith("https://hardverapro.hu/")

    second = listings[1]
    assert second.listing_id == "7654321"
    assert second.price == 120_000


def test_same_item_different_wording_normalizes_to_same_key():
    html = FIXTURE.read_text(encoding="utf-8")
    listings = parse_search_results(html)
    assert listings[0].normalized_key == listings[1].normalized_key == "iphone 12 128gb"


def test_no_cards_returns_empty_list_without_raising():
    assert parse_search_results("<html><body>nothing here</body></html>") == []
