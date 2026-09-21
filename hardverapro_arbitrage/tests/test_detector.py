from datetime import datetime, timezone

from hardverapro_arbitrage.arbitrage.detector import evaluate
from hardverapro_arbitrage.config import Config
from hardverapro_arbitrage.models import Listing, RetailPrice


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


def test_used_median_result_reports_its_basis():
    config = Config(search_urls=["https://example.com"], min_samples_for_reference=3, deal_discount_threshold=0.2)
    result = evaluate(_listing(70_000), recent_prices=[100_000, 100_000, 100_000], config=config)
    assert result.basis == "used_median"


def _retail(price: float, confidence: float = 0.9) -> RetailPrice:
    return RetailPrice(product_title="Some Product", price=price, currency="HUF", url="https://x/1", match_confidence=confidence)


def test_no_used_history_falls_back_to_retail():
    config = Config(search_urls=["https://example.com"], min_samples_for_reference=3, retail_deal_threshold=0.45)
    # no used comparables at all -- can't compute a used-median reference
    result = evaluate(_listing(50_000), recent_prices=[], config=config, retail_price=_retail(price=100_000))
    assert result is not None
    assert result.basis == "retail"
    assert result.retail_reference_price == 100_000
    assert round(result.retail_discount_fraction, 2) == 0.50


def test_used_median_wins_over_retail_when_both_qualify():
    # used-median is the PRIMARY signal: when it qualifies on its own,
    # that's the basis, even if retail would also qualify.
    config = Config(
        search_urls=["https://example.com"],
        min_samples_for_reference=3,
        deal_discount_threshold=0.2,
        retail_deal_threshold=0.1,  # deliberately lenient, so retail would also fire
    )
    result = evaluate(
        _listing(70_000), recent_prices=[100_000, 100_000, 100_000], config=config, retail_price=_retail(price=200_000)
    )
    assert result.basis == "used_median"
    # retail info still attached for display, just not what qualified it
    assert result.retail_reference_price == 200_000


def test_retail_fallback_when_used_median_below_threshold():
    config = Config(
        search_urls=["https://example.com"],
        min_samples_for_reference=3,
        deal_discount_threshold=0.2,
        retail_deal_threshold=0.45,
    )
    # only 5% below used median -- doesn't qualify on its own
    result = evaluate(
        _listing(95_000), recent_prices=[100_000, 100_000, 100_000], config=config, retail_price=_retail(price=200_000)
    )
    assert result is not None
    assert result.basis == "retail"
    assert result.retail_discount_fraction == 0.525


def test_low_confidence_retail_match_is_ignored():
    config = Config(
        search_urls=["https://example.com"],
        min_samples_for_reference=3,
        retail_deal_threshold=0.2,
        retail_min_match_confidence=0.6,
    )
    result = evaluate(
        _listing(50_000), recent_prices=[], config=config, retail_price=_retail(price=200_000, confidence=0.4)
    )
    assert result is None


def test_no_deal_when_neither_comparison_qualifies():
    config = Config(
        search_urls=["https://example.com"], min_samples_for_reference=3,
        deal_discount_threshold=0.2, retail_deal_threshold=0.45,
    )
    result = evaluate(
        _listing(95_000), recent_prices=[100_000, 100_000, 100_000], config=config, retail_price=_retail(price=100_000)
    )
    assert result is None
