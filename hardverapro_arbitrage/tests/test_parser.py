"""Tests the parser against REAL hardverapro.hu markup (see the fixture
file's header comment for provenance — extracted from a live category page,
not hand-written). This proves both the extraction logic and the selectors
actually match the site, not just that the code does what it's meant to.
"""
from pathlib import Path

from hardverapro_arbitrage.scraper.parser import parse_search_results

FIXTURE = Path(__file__).parent / "fixtures" / "sample_search_page.html"


def test_parses_valid_cards_and_skips_malformed_ones():
    html = FIXTURE.read_text(encoding="utf-8")
    listings = parse_search_results(html)

    assert len(listings) == 2  # the third card has its price column stripped and is skipped

    first = listings[0]
    assert first.listing_id == "7717205"
    assert first.title == "Ingyen FOX/GLS/MPL mehet! Új ASUS TUF B850M-PLUS WiFi7 + AMD Ryzen 7 7800X3D"
    assert first.price == 150_000
    assert first.currency == "HUF"
    assert first.location == "XIX. kerület"
    assert first.url == "https://hardverapro.hu/apro/uj_asus_tuf_b850m-plus_wifi7_amd_ryzen_7_7800x3d/friss.html"

    second = listings[1]
    assert second.listing_id == "7714720"
    assert second.price == 39_990


def test_different_items_get_different_normalized_keys():
    html = FIXTURE.read_text(encoding="utf-8")
    listings = parse_search_results(html)
    assert listings[0].normalized_key != listings[1].normalized_key


def test_no_cards_returns_empty_list_without_raising():
    assert parse_search_results("<html><body>nothing here</body></html>") == []
