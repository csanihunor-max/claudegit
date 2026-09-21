from datetime import datetime, timezone

from hardverapro_arbitrage.models import Deal, Listing
from hardverapro_arbitrage.storage import db


def _listing(listing_id: str, price: float, key_title: str = "iPhone 12 128GB") -> Listing:
    return Listing(
        listing_id=listing_id,
        url=f"https://hardverapro.hu/x-t{listing_id}",
        title=key_title,
        price=price,
        currency="HUF",
        location=None,
        seen_at=datetime.now(timezone.utc),
    )


def test_record_and_fetch_recent_prices():
    conn = db.connect(":memory:")
    db.record_observation(conn, _listing("1", 100_000))
    db.record_observation(conn, _listing("2", 110_000))
    db.record_observation(conn, _listing("3", 90_000))

    prices = db.get_recent_prices(conn, "iphone 12 128gb", window_days=90)
    assert sorted(prices) == [90_000, 100_000, 110_000]


def test_exclude_listing_id():
    conn = db.connect(":memory:")
    db.record_observation(conn, _listing("1", 100_000))
    db.record_observation(conn, _listing("2", 110_000))

    prices = db.get_recent_prices(conn, "iphone 12 128gb", window_days=90, exclude_listing_id="1")
    assert prices == [110_000]


def test_notified_dedup():
    conn = db.connect(":memory:")
    assert db.has_been_notified(conn, "1", 100_000) is False
    db.mark_notified(conn, "1", 100_000)
    assert db.has_been_notified(conn, "1", 100_000) is True
    # a further price drop on the same listing is a distinct (id, price) pair
    assert db.has_been_notified(conn, "1", 90_000) is False


def test_same_listing_rescraped_keeps_only_latest_price_per_listing():
    conn = db.connect(":memory:")
    db.record_observation(conn, _listing("1", 100_000))
    db.record_observation(conn, _listing("1", 80_000))  # price dropped on re-scrape

    prices = db.get_recent_prices(conn, "iphone 12 128gb", window_days=90)
    assert prices == [80_000]


def _deal(listing_id: str, price: float, reference: float) -> Deal:
    listing = _listing(listing_id, price)
    return Deal(
        listing=listing,
        market_reference_price=reference,
        discount_fraction=(reference - price) / reference,
        sample_size=3,
    )


def test_recent_deals_ranked_by_discount_descending():
    conn = db.connect(":memory:")
    db.record_deal(conn, _deal("1", price=80_000, reference=100_000))  # 20% off
    db.record_deal(conn, _deal("2", price=50_000, reference=100_000))  # 50% off
    db.record_deal(conn, _deal("3", price=70_000, reference=100_000))  # 30% off

    rows = db.get_recent_deals(conn, window_days=90, limit=10)
    assert [r["listing_id"] for r in rows] == ["2", "3", "1"]


def test_recent_deals_dedup_keeps_only_latest_per_listing():
    conn = db.connect(":memory:")
    db.record_deal(conn, _deal("1", price=90_000, reference=100_000))  # 10% off, detected first
    db.record_deal(conn, _deal("1", price=60_000, reference=100_000))  # price dropped further, detected later

    rows = db.get_recent_deals(conn, window_days=90, limit=10)
    assert len(rows) == 1
    assert rows[0]["price"] == 60_000


def test_recent_deals_respects_limit():
    conn = db.connect(":memory:")
    for i in range(5):
        db.record_deal(conn, _deal(str(i), price=90_000, reference=100_000))

    rows = db.get_recent_deals(conn, window_days=90, limit=2)
    assert len(rows) == 2
