from pathlib import Path

from hardverapro_arbitrage.http import FetchError
from hardverapro_arbitrage.retail.lookup import find_retail_price

FIXTURE = Path(__file__).parent / "fixtures" / "sample_retail_search.html"


class _FakeClient:
    def __init__(self, html: str | None = None, raises: bool = False):
        self._html = html
        self._raises = raises

    def get(self, url: str) -> str:
        if self._raises:
            raise FetchError("boom")
        return self._html


def test_find_retail_price_wires_client_parser_and_matcher():
    html = FIXTURE.read_text(encoding="utf-8")
    result = find_retail_price("Steam Deck OLED 512GB", _FakeClient(html=html))

    assert result is not None
    assert result.price == 280_000
    assert result.match_confidence > 0.8


def test_find_retail_price_returns_none_on_fetch_error():
    result = find_retail_price("Steam Deck OLED 512GB", _FakeClient(raises=True))
    assert result is None


def test_find_retail_price_returns_none_with_no_candidates():
    result = find_retail_price("Steam Deck OLED 512GB", _FakeClient(html="<html><body></body></html>"))
    assert result is None
