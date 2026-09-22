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


def test_implausibly_large_discount_is_rejected():
    # Real false positives this catches: "Samsung Monitor" at 90.9% off
    # (two differently-modeled, unnamed monitors treated as the same
    # product), "Nintendo Switch OLED" at 60%. A real used item
    # essentially never sells at under half its own resale median -- a
    # bad title match is far more likely than a genuine bargain that size.
    config = Config(
        search_urls=["https://example.com"], min_samples_for_reference=2,
        deal_discount_threshold=0.05, max_plausible_discount_fraction=0.5,
    )
    result = evaluate(_listing(1_000), recent_prices=[11_000, 11_000], config=config)  # 90.9% off
    assert result is None


def test_discount_just_under_the_plausibility_cap_is_still_flagged():
    config = Config(
        search_urls=["https://example.com"], min_samples_for_reference=2,
        deal_discount_threshold=0.05, max_plausible_discount_fraction=0.5,
    )
    result = evaluate(_listing(51_000), recent_prices=[100_000, 100_000], config=config)  # 49% off
    assert result is not None
    assert round(result.discount_fraction, 2) == 0.49


def test_plausibility_cap_is_configurable():
    config = Config(
        search_urls=["https://example.com"], min_samples_for_reference=2,
        deal_discount_threshold=0.05, max_plausible_discount_fraction=0.3,
        low_sample_discount_margin=0.0,
    )
    result = evaluate(_listing(75_000), recent_prices=[100_000, 100_000], config=config)  # 25% off, under the cap
    assert result is not None
    result = evaluate(_listing(65_000), recent_prices=[100_000, 100_000], config=config)  # 35% off, over the cap
    assert result is None


# Real problem this whole margin exists to catch: checked against every
# deal ever flagged in production, ALL of them had sample_size 2-4 -- a
# median of 2 prices is just their average, with none of a real median's
# robustness to one price being unusual. The flat threshold alone treated
# that razor-thin coincidence exactly the same as a ten-listing consensus.
def test_low_sample_size_requires_a_bigger_discount():
    config = Config(
        search_urls=["https://example.com"], min_samples_for_reference=2,
        deal_discount_threshold=0.05, low_sample_discount_margin=0.10,
    )
    # sample_size=2 (the floor): required discount is 0.05 + 0.10/1 = 0.15
    result = evaluate(_listing(87_000), recent_prices=[100_000, 100_000], config=config)  # 13% off
    assert result is None
    result = evaluate(_listing(84_000), recent_prices=[100_000, 100_000], config=config)  # 16% off
    assert result is not None


def test_low_sample_margin_shrinks_as_comparables_accumulate():
    config = Config(
        search_urls=["https://example.com"], min_samples_for_reference=2,
        deal_discount_threshold=0.05, low_sample_discount_margin=0.10,
    )
    # sample_size=11: required discount is 0.05 + 0.10/10 = 0.06 -- far
    # closer to the plain threshold than the 2-sample case above.
    prices = [100_000] * 11
    result = evaluate(_listing(93_000), recent_prices=prices, config=config)  # 7% off
    assert result is not None


def test_low_sample_margin_disabled_falls_back_to_flat_threshold():
    config = Config(
        search_urls=["https://example.com"], min_samples_for_reference=2,
        deal_discount_threshold=0.05, low_sample_discount_margin=0.0,
    )
    result = evaluate(_listing(94_000), recent_prices=[100_000, 100_000], config=config)  # 6% off
    assert result is not None
