from datetime import datetime, timezone

import hardverapro_arbitrage.pipeline as pipeline_module
from hardverapro_arbitrage.config import Config
from hardverapro_arbitrage.models import Listing, RetailPrice
from hardverapro_arbitrage.notify.console import ConsoleNotifier
from hardverapro_arbitrage.storage import db


class _FakeHardveraproClient:
    def get(self, url: str) -> str:
        return "<html></html>"  # content ignored; parse_search_results is monkeypatched


def _listing(listing_id: str, price: float, title: str) -> Listing:
    return Listing(
        listing_id=listing_id, url=f"https://hardverapro.hu/x-t{listing_id}", title=title,
        price=price, currency="HUF", location=None, seen_at=datetime.now(timezone.utc),
    )


def test_retail_fallback_deduplicates_lookups_by_normalized_key(monkeypatch):
    # two different listings, same item -- must trigger only ONE retail lookup
    listings = [
        _listing("1", 100_000, "Steam Deck OLED 512GB"),
        _listing("2", 110_000, "Steam Deck OLED 512GB"),
    ]
    monkeypatch.setattr(pipeline_module, "parse_search_results", lambda html: listings)

    calls = []

    def fake_find_retail_price(query_text, client):
        calls.append(query_text)
        return RetailPrice(product_title="Steam Deck OLED 512GB", price=300_000, currency="HUF", url="https://x/1", match_confidence=0.9)

    monkeypatch.setattr(pipeline_module, "find_retail_price", fake_find_retail_price)

    config = Config(search_urls=["https://example.com"], retail_deal_threshold=0.5, max_pages_per_category=1)
    conn = db.connect(":memory:")
    deals = pipeline_module.run_once(config, conn, _FakeHardveraproClient(), [ConsoleNotifier()])

    assert len(calls) == 1  # deduplicated across the two listings sharing a key
    assert len(deals) == 2  # but both listings still get evaluated against it
    assert all(d.basis == "retail" for d in deals)


def test_retail_fallback_reuses_cache_without_a_new_lookup(monkeypatch):
    listing = _listing("1", 100_000, "Steam Deck OLED 512GB")
    monkeypatch.setattr(pipeline_module, "parse_search_results", lambda html: [listing])

    calls = []
    monkeypatch.setattr(
        pipeline_module,
        "find_retail_price",
        lambda query_text, client: calls.append(query_text) or None,
    )

    config = Config(search_urls=["https://example.com"], retail_deal_threshold=0.5, max_pages_per_category=1)
    conn = db.connect(":memory:")
    db.cache_retail_price(
        conn,
        listing.normalized_key,
        RetailPrice(product_title="Steam Deck OLED 512GB", price=300_000, currency="HUF", url="https://x/1", match_confidence=0.9),
    )

    deals = pipeline_module.run_once(config, conn, _FakeHardveraproClient(), [ConsoleNotifier()])

    assert calls == []  # cache hit, no network call
    assert len(deals) == 1
    assert deals[0].basis == "retail"


def test_retail_lookup_budget_is_respected(monkeypatch):
    listings = [_listing(str(i), 10_000, f"Item {i}") for i in range(5)]
    monkeypatch.setattr(pipeline_module, "parse_search_results", lambda html: listings)

    calls = []

    def fake_find_retail_price(query_text, client):
        calls.append(query_text)
        return None  # no match found, so nothing qualifies either way

    monkeypatch.setattr(pipeline_module, "find_retail_price", fake_find_retail_price)

    config = Config(search_urls=["https://example.com"], retail_max_lookups_per_cycle=2, max_pages_per_category=1)
    conn = db.connect(":memory:")
    pipeline_module.run_once(config, conn, _FakeHardveraproClient(), [ConsoleNotifier()])

    assert len(calls) == 2  # capped, even though 5 distinct items needed a lookup


def test_retail_disabled_skips_fallback_entirely(monkeypatch):
    listing = _listing("1", 10_000, "Steam Deck OLED 512GB")
    monkeypatch.setattr(pipeline_module, "parse_search_results", lambda html: [listing])

    calls = []
    monkeypatch.setattr(
        pipeline_module, "find_retail_price", lambda query_text, client: calls.append(query_text)
    )

    config = Config(search_urls=["https://example.com"], retail_enabled=False, max_pages_per_category=1)
    conn = db.connect(":memory:")
    deals = pipeline_module.run_once(config, conn, _FakeHardveraproClient(), [ConsoleNotifier()])

    assert calls == []
    assert deals == []


def test_offset_url_builds_correctly():
    assert pipeline_module._offset_url("https://x.hu/index.html", 0) == "https://x.hu/index.html"
    assert pipeline_module._offset_url("https://x.hu/index.html", 100) == "https://x.hu/index.html?offset=100"
    assert pipeline_module._offset_url("https://x.hu/index.html?a=1", 100) == "https://x.hu/index.html?a=1&offset=100"


class _PagedFakeClient:
    """Returns a distinct dummy html string per page, so a monkeypatched
    parse_search_results can tell pages apart by url/offset without
    needing real HTML.
    """

    def __init__(self):
        self.urls_fetched: list[str] = []

    def get(self, url: str) -> str:
        self.urls_fetched.append(url)
        return url  # parse_search_results below is monkeypatched to treat this as the page url


def test_pagination_stops_when_a_page_returns_no_listings(monkeypatch):
    client = _PagedFakeClient()

    def fake_parse(html):
        # html here IS the url, per _PagedFakeClient.get above
        if "offset=" not in html:
            return [_listing("1", 10_000, "Item 1")]
        return []  # page 2 (offset=100) is empty -- end of category

    monkeypatch.setattr(pipeline_module, "parse_search_results", fake_parse)

    config = Config(search_urls=["https://example.com/index.html"], max_pages_per_category=5, retail_enabled=False)
    conn = db.connect(":memory:")
    pipeline_module.run_once(config, conn, client, [ConsoleNotifier()])

    # page 1 had a listing (kept going), page 2 was empty (stopped there, never tried a 3rd)
    assert client.urls_fetched == [
        "https://example.com/index.html",
        "https://example.com/index.html?offset=100",
    ]


def test_pagination_respects_max_pages_cap(monkeypatch):
    client = _PagedFakeClient()
    # every page has a genuinely NEW listing -- pagination would run
    # forever without the cap, since it would never see "no new listings"
    monkeypatch.setattr(
        pipeline_module,
        "parse_search_results",
        lambda html: [_listing(html, 10_000, "Item")],  # html is the page url here, so each page's id is unique
    )

    config = Config(search_urls=["https://example.com/index.html"], max_pages_per_category=3, retail_enabled=False)
    conn = db.connect(":memory:")
    pipeline_module.run_once(config, conn, client, [ConsoleNotifier()])

    assert client.urls_fetched == [
        "https://example.com/index.html",
        "https://example.com/index.html?offset=100",
        "https://example.com/index.html?offset=200",
    ]


def test_pagination_stops_on_wraparound_not_just_empty_pages(monkeypatch):
    # The real bug this guards against: a category smaller than one page
    # doesn't get an empty result past its end -- the site wraps around
    # and re-serves page 1's exact listings instead (verified against a
    # real fetch). "0 listings" never fires as a stop condition there;
    # only "0 *new* listings" does.
    client = _PagedFakeClient()
    same_listing = _listing("1", 10_000, "Item 1")
    monkeypatch.setattr(pipeline_module, "parse_search_results", lambda html: [same_listing])

    config = Config(search_urls=["https://example.com/index.html"], max_pages_per_category=5, retail_enabled=False)
    conn = db.connect(":memory:")
    pipeline_module.run_once(config, conn, client, [ConsoleNotifier()])

    # page 1: listing "1" is new, kept going. page 2: same listing "1"
    # again -- 0 new, stop. Never reaches page 3, 4, or 5.
    assert client.urls_fetched == [
        "https://example.com/index.html",
        "https://example.com/index.html?offset=100",
    ]

    # and it was only recorded once, not once per page fetched
    cur = conn.execute("SELECT COUNT(*) FROM observations")
    assert cur.fetchone()[0] == 1
