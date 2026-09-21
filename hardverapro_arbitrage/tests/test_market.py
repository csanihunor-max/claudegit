from hardverapro_arbitrage.pricing.market import market_reference_price


def test_none_when_not_enough_samples():
    assert market_reference_price([100, 200], min_samples=3) is None


def test_median_of_samples():
    assert market_reference_price([100, 200, 300], min_samples=3) == 200


def test_median_is_robust_to_outlier_within_trusted_spread():
    # one modestly high outlier (within max_spread_ratio) shouldn't move
    # the reference much -- explicitly widened here to isolate this from
    # the spread-rejection behavior tested below
    prices = [100, 100, 100, 100, 100, 250]
    assert market_reference_price(prices, min_samples=3, max_spread_ratio=3.0) == 100


def test_none_when_group_spread_is_implausible():
    # real numbers from a genuine false positive: "PS4 játékok" ("PS4
    # games") listings that normalize to the same key but are actually
    # bundles of wildly different game counts -- different real items,
    # not independent pricing of one product
    prices = [3_000, 4_500, 12_345]
    assert market_reference_price(prices, min_samples=2) is None


def test_reference_still_computed_for_a_genuinely_comparable_group():
    # real numbers from a genuine deal: independently-priced listings of
    # one specific product (ASUS ROG Xbox Ally X), max/min ~1.5x
    prices = [260_000, 295_000, 299_000, 320_000, 369_900]
    assert market_reference_price(prices, min_samples=2) == 299_000
