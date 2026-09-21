from datetime import datetime, timezone

from hardverapro_arbitrage.models import Listing
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
