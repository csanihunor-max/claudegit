"""Parser tests against real (trimmed, seller data removed) Jófogás search pages saved 2026-09-23."""

import dataclasses

import pytest

from tests.conftest import fixture_text
from watchfinder.config import JofogasConfig
from watchfinder.models import Listing
from watchfinder.sources.base import SourceError
from watchfinder.sources.jofogas import JofogasSource, parse_search_page, search_url


def test_search_url():
    assert search_url("raketa", "karorak-") == "https://www.jofogas.hu/magyarorszag/karorak-?q=raketa"
    assert search_url("karóra") == "https://www.jofogas.hu/magyarorszag?q=kar%C3%B3ra"
    assert search_url("seiko 5", "") == "https://www.jofogas.hu/magyarorszag?q=seiko%205"


def test_parse_raketa_page():
    result = parse_search_page(fixture_text("jofogas_raketa.html"))
    assert len(result.listings) == 36
    assert result.complete is False  # 39 results over 2 pages; we only read page 1

    first = result.listings[0]
    assert first.source == "jofogas"
    assert first.listing_id.isdigit()
    assert first.url.startswith("https://www.jofogas.hu/") and first.url.endswith(f"_{first.listing_id}.htm")
    assert first.currency == "HUF"
    assert all(l.category and l.category.endswith("Karórák") for l in result.listings)
    assert len({l.listing_id for l in result.listings}) == 36


def test_parse_known_listing_fields():
    listings = {l.listing_id: l for l in parse_search_page(fixture_text("jofogas_seiko.html")).listings}
    seiko = listings["162199588"]
    assert seiko.title == "Seiko 5, szerviz után"
    assert seiko.price == 39000
    assert seiko.location == "Kaposvár, Somogy"
    assert seiko.thumbnail_url == "https://img.jofogas.hu/bigthumbs/Seiko_5__szerviz_utan_406532860018571.jpg"
    assert seiko.url == "https://www.jofogas.hu/somogy/Seiko_5__szerviz_utan_162199588.htm"


def test_parser_never_copies_seller_data():
    html = fixture_text("jofogas_raketa.html")
    assert "SENTINEL SELLER NAME" in html  # the fixture's first ad carries a fake seller name
    fields = {f.name for f in dataclasses.fields(Listing)}
    assert not fields & {"seller", "seller_name", "company_name", "phone", "user_name"}
    for listing in parse_search_page(html).listings:
        assert "SENTINEL" not in repr(listing)


def test_parse_empty_result_page():
    result = parse_search_page(fixture_text("jofogas_empty.html"))
    assert result.listings == []
    assert result.complete is True


def test_page_without_next_data_raises():
    with pytest.raises(SourceError):
        parse_search_page("<html><body><h1>Access denied</h1></body></html>")


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text


class FakeHttp:
    def __init__(self, pages: dict[str, FakeResponse]):
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        return self.pages[url]


def test_source_searches_every_keyword_and_category_and_dedupes(config):
    page = fixture_text("jofogas_raketa.html")
    http = FakeHttp({
        search_url("raketa", "karorak-"): FakeResponse(200, page),
        search_url("raketa", "karorak"): FakeResponse(200, fixture_text("jofogas_empty.html")),
        search_url("rakéta", "karorak-"): FakeResponse(200, page),
        search_url("rakéta", "karorak"): FakeResponse(200, fixture_text("jofogas_empty.html")),
    })
    source = JofogasSource(http, JofogasConfig(categories=("karorak-", "karorak")))
    search = dataclasses.replace(config.search("Raketa"), keywords=("raketa", "rakéta"))
    result = source.search(search)
    assert len(http.requested) == 4
    assert len(result.listings) == 36          # same ads from both keywords, stored once
    assert result.complete is False


def test_source_raises_on_http_error(config):
    http = FakeHttp({search_url("raketa", "karorak-"): FakeResponse(403)})
    with pytest.raises(SourceError):
        JofogasSource(http, JofogasConfig()).search(config.search("Raketa"))


@pytest.mark.parametrize("status, expected", [(410, True), (404, True), (200, False), (302, None)])
def test_is_gone(status, expected):
    listing = Listing("jofogas", "1", "x", 1, "HUF", "https://www.jofogas.hu/budapest/x_1.htm")
    http = FakeHttp({listing.url: FakeResponse(status)})
    assert JofogasSource(http, JofogasConfig()).is_gone(listing) is expected
