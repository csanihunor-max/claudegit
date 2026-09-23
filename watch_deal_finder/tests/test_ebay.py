import json

import pytest

from tests.conftest import FIXTURES, make_config
from watchfinder.config import EbayConfig, Secrets
from watchfinder.http import HttpClient
from watchfinder.pricing import to_huf
from watchfinder.sources import build_sources
from watchfinder.sources.base import SourceError
from watchfinder.sources.ebay import SEARCH_URL, TOKEN_URL, EbaySource, parse_search_response

DATA = json.loads((FIXTURES / "ebay_search.json").read_text(encoding="utf-8"))


def test_parse_search_response():
    result = parse_search_response(DATA)
    assert result.complete is True
    a, b, c = result.listings
    assert a.listing_id == "v1|226512345678|0" and a.price == 64.99 and a.currency == "EUR"
    assert a.url == "https://www.ebay.de/itm/226512345678"
    assert a.thumbnail_url.endswith("s-l225.jpg") and a.location == "DE"
    assert a.category == "Armbanduhren"
    assert b.price == 31.0 and b.location == "Wien, AT"          # auction: current bid
    assert b.thumbnail_url.endswith("def/s-l225.jpg")
    assert c.currency == "GBP" and to_huf(c.price, c.currency, 400) is None
    assert "SENTINEL" not in repr(result.listings)


def test_partial_when_more_than_one_page():
    assert parse_search_response({**DATA, "total": 500}).complete is False


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class FakeHttp:
    def __init__(self, script):
        self.script, self.calls = script, []

    def post(self, url, **kw):
        self.calls.append(("POST", url, kw))
        return self.script[url].pop(0)

    def get(self, url, **kw):
        self.calls.append(("GET", url, kw))
        return self.script[url].pop(0)


def source(script, now=[1000.0]):
    return EbaySource(FakeHttp(script), EbayConfig(enabled=True), "id", "secret", clock=lambda: now[0])


def test_search_uses_oauth_token_and_marketplace_header():
    src = source({
        TOKEN_URL: [Resp(200, {"access_token": "T1", "expires_in": 7200})],
        SEARCH_URL: [Resp(200, DATA), Resp(200, DATA)],
    })
    cfg = make_config()
    search = cfg.search("Raketa")
    assert len(src.search(search).listings) == 3
    src.search(search)   # token is cached: only one POST
    posts = [c for c in src.http.calls if c[0] == "POST"]
    assert len(posts) == 1 and posts[0][2]["auth"] == ("id", "secret")
    method, url, kw = src.http.calls[1]
    assert kw["headers"] == {"Authorization": "Bearer T1", "X-EBAY-C-MARKETPLACE-ID": "EBAY_DE"}
    assert kw["params"]["q"] == "raketa" and kw["params"]["category_ids"] == "31387"
    assert kw["check_robots"] is False


def test_expired_token_401_refreshes_once():
    src = source({
        TOKEN_URL: [Resp(200, {"access_token": "T1"}), Resp(200, {"access_token": "T2"})],
        SEARCH_URL: [Resp(401, {}), Resp(200, DATA)],
    })
    assert len(src.search(make_config().search("Raketa")).listings) == 3
    assert src.http.calls[-1][2]["headers"]["Authorization"] == "Bearer T2"


def test_bad_credentials_raise_source_error():
    src = source({TOKEN_URL: [Resp(401, {"error": "invalid_client", "error_description": "client authentication failed"})]})
    with pytest.raises(SourceError, match="client authentication failed"):
        src.search(make_config().search("Raketa"))


def test_ebay_switched_off_without_keys():
    http = HttpClient("x")
    enabled = make_config(sources={"ebay": {"enabled": True}})
    assert "ebay" not in build_sources(enabled, http)          # no keys -> off, with a warning
    from dataclasses import replace
    with_keys = replace(enabled, secrets=Secrets(ebay_client_id="a", ebay_client_secret="b"))
    assert "ebay" in build_sources(with_keys, http)
    assert "ebay" not in build_sources(replace(with_keys, ebay=EbayConfig(enabled=False)), http)
