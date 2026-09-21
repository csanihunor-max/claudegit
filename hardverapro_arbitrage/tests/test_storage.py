import sqlite3
from datetime import datetime, timedelta, timezone

from hardverapro_arbitrage.models import Deal, Listing, RetailPrice
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
        basis="used_median",
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


def test_source_label_stored_and_defaults_to_none():
    conn = db.connect(":memory:")
    db.record_deal(conn, _deal("1", price=80_000, reference=100_000), source_label="Steam Deck")
    db.record_deal(conn, _deal("2", price=80_000, reference=100_000))  # no label passed

    rows = {r["listing_id"]: r for r in db.get_recent_deals(conn, window_days=90, limit=10)}
    assert rows["1"]["source_label"] == "Steam Deck"
    assert rows["2"]["source_label"] is None


def _retail_deal(listing_id: str, price: float, retail_reference: float) -> Deal:
    listing = _listing(listing_id, price)
    return Deal(
        listing=listing,
        basis="retail",
        retail_reference_price=retail_reference,
        retail_discount_fraction=(retail_reference - price) / retail_reference,
        retail_match_confidence=0.9,
    )


def test_used_median_deals_rank_before_retail_deals_regardless_of_raw_percent():
    conn = db.connect(":memory:")
    # a modest 25% used-median discount...
    db.record_deal(conn, _deal("used", price=75_000, reference=100_000))
    # ...must still outrank a much bigger 60% retail-only discount, since
    # used-median is the primary signal and retail is only a fallback.
    db.record_deal(conn, _retail_deal("retail", price=40_000, retail_reference=100_000))

    rows = db.get_recent_deals(conn, window_days=90, limit=10)
    assert [r["listing_id"] for r in rows] == ["used", "retail"]


def test_retail_price_cache_roundtrip():
    conn = db.connect(":memory:")
    assert db.get_cached_retail_price(conn, "steam deck oled 512gb", max_age_days=7) is None

    price = RetailPrice(product_title="Valve Steam Deck OLED 512GB", price=280_000, currency="HUF", url="https://x/1", match_confidence=0.95)
    db.cache_retail_price(conn, "steam deck oled 512gb", price)

    cached = db.get_cached_retail_price(conn, "steam deck oled 512gb", max_age_days=7)
    assert cached is not None
    assert cached.price == 280_000
    assert cached.match_confidence == 0.95


def test_retail_price_cache_upserts():
    conn = db.connect(":memory:")
    db.cache_retail_price(
        conn, "k", RetailPrice(product_title="A", price=100, currency="HUF", url="https://x/1", match_confidence=0.5)
    )
    db.cache_retail_price(
        conn, "k", RetailPrice(product_title="B", price=200, currency="HUF", url="https://x/2", match_confidence=0.9)
    )
    cached = db.get_cached_retail_price(conn, "k", max_age_days=7)
    assert cached.product_title == "B"
    assert cached.price == 200


def test_retail_price_cache_expires():
    conn = db.connect(":memory:")
    with conn:
        conn.execute(
            "INSERT INTO retail_prices (normalized_key, product_title, price, currency, url, match_confidence, cached_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "k",
                "Old Price",
                100,
                "HUF",
                "https://x/1",
                0.9,
                (datetime.now(timezone.utc) - timedelta(days=30)).isoformat(),
            ),
        )
    assert db.get_cached_retail_price(conn, "k", max_age_days=7) is None


def test_migrates_pre_retail_schema_without_data_loss(tmp_path):
    # The exact `deals` shape from before basis/retail columns existed:
    # market_reference_price and discount_fraction were NOT NULL, which
    # `CREATE TABLE IF NOT EXISTS` can't retrofit around on its own.
    db_path = str(tmp_path / "old.sqlite3")
    raw = sqlite3.connect(db_path)
    raw.executescript(
        """
        CREATE TABLE deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            price REAL NOT NULL,
            currency TEXT NOT NULL,
            location TEXT,
            market_reference_price REAL NOT NULL,
            discount_fraction REAL NOT NULL,
            sample_size INTEGER NOT NULL,
            detected_at TEXT NOT NULL,
            source_label TEXT
        );
        """
    )
    raw.execute(
        "INSERT INTO deals (listing_id, title, url, price, currency, location, "
        "market_reference_price, discount_fraction, sample_size, detected_at, source_label) "
        "VALUES ('1', 'Old Deal', 'https://x/1', 80000, 'HUF', 'Budapest', 100000, 0.2, 3, '2026-01-01T00:00:00+00:00', 'Phones')"
    )
    raw.commit()
    raw.close()

    conn = db.connect(db_path)  # must not raise, and must migrate in place

    rows = db.get_recent_deals(conn, window_days=3650, limit=10)
    assert len(rows) == 1
    assert rows[0]["basis"] == "used_median"  # backfilled, the only comparison that existed then
    assert rows[0]["market_reference_price"] == 100000
    assert rows[0]["source_label"] == "Phones"

    # a retail-only deal (NULL used-median fields) must now be insertable
    # -- this is exactly what crashed before the migration existed
    retail_deal = Deal(
        listing=_listing("2", 50_000),
        basis="retail",
        retail_reference_price=100_000,
        retail_discount_fraction=0.5,
        retail_match_confidence=0.9,
    )
    db.record_deal(conn, retail_deal)  # must not raise
