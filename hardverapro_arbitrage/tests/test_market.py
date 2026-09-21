from hardverapro_arbitrage.pricing.market import market_reference_price


def test_none_when_not_enough_samples():
    assert market_reference_price([100, 200], min_samples=3) is None


def test_median_of_samples():
    assert market_reference_price([100, 200, 300], min_samples=3) == 200


def test_median_is_robust_to_outlier():
    # one extremely cheap or expensive outlier shouldn't move the reference much
    prices = [100, 100, 100, 100, 100, 1000]
    assert market_reference_price(prices, min_samples=3) == 100
