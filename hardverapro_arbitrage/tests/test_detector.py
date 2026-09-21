from datetime import datetime, timezone

from hardverapro_arbitrage.arbitrage.detector import evaluate
from hardverapro_arbitrage.config import Config
from hardverapro_arbitrage.models import Listing


def _listing(price: float, title: str = "iPhone 12 128GB") -> Listing:
    return Listing(
        listing_id="123",
        url="https://hardverapro.hu/x-t123",
        title=title,
        price=price,
        currency="HUF",
        location="Budapest",
        seen_at=datetime.now(timezone.utc),
    )


def test_no_deal_without_enough_history():
    config = Config(search_urls=["https://example.com"], min_samples_for_reference=3)
    result = evaluate(_listing(50_000), recent_prices=[100_000, 100_000], config=config)
    assert result is None


def test_no_deal_when_price_close_to_reference():
    config = Config(search_urls=["https://example.com"], min_samples_for_reference=3, deal_discount_threshold=0.2)
    # reference = 100_000, price = 95_000 -> only 5% below, threshold is 20%
    result = evaluate(_listing(95_000), recent_prices=[100_000, 100_000, 100_000], config=config)
    assert result is None


def test_deal_flagged_when_below_threshold():
    config = Config(search_urls=["https://example.com"], min_samples_for_reference=3, deal_discount_threshold=0.2)
    result = evaluate(_listing(70_000), recent_prices=[100_000, 100_000, 100_000], config=config)
    assert result is not None
    assert result.market_reference_price == 100_000
    assert round(result.discount_fraction, 2) == 0.30


def test_max_price_cap_excludes_listing():
    config = Config(search_urls=["https://example.com"], min_samples_for_reference=1, max_price=50_000)
    result = evaluate(_listing(70_000), recent_prices=[100_000], config=config)
    assert result is None
