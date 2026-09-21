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

    config = Config(search_urls=["https://example.com"], retail_deal_threshold=0.5)
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

    config = Config(search_urls=["https://example.com"], retail_deal_threshold=0.5)
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

    config = Config(search_urls=["https://example.com"], retail_max_lookups_per_cycle=2)
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

    config = Config(search_urls=["https://example.com"], retail_enabled=False)
    conn = db.connect(":memory:")
    deals = pipeline_module.run_once(config, conn, _FakeHardveraproClient(), [ConsoleNotifier()])

    assert calls == []
    assert deals == []
