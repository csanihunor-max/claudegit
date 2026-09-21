import sqlite3
from datetime import datetime, timedelta, timezone

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


def test_source_label_stored_and_defaults_to_none():
    conn = db.connect(":memory:")
    db.record_deal(conn, _deal("1", price=80_000, reference=100_000), source_label="Steam Deck")
    db.record_deal(conn, _deal("2", price=80_000, reference=100_000))  # no label passed

    rows = {r["listing_id"]: r for r in db.get_recent_deals(conn, window_days=90, limit=10)}
    assert rows["1"]["source_label"] == "Steam Deck"
    assert rows["2"]["source_label"] is None


def test_recent_deals_freshness_filter_excludes_listing_not_seen_recently():
    # Real bug this catches: a listing flagged as a deal, then marked
    # jegelve (or sold) by the seller afterward -- once that happens the
    # parser stops producing a Listing for it at all (see
    # scraper/parser.py's `_is_iced`), so its last observation stops
    # advancing while the deal row itself just sits there unrevised.
    # Without the freshness join, get_recent_deals kept surfacing it for
    # the full window regardless.
    conn = db.connect(":memory:")
    db.record_observation(conn, _listing("stale", 80_000))
    conn.execute(
        "UPDATE observations SET seen_at = ? WHERE listing_id = ?",
        ((datetime.now(timezone.utc) - timedelta(hours=3)).isoformat(), "stale"),
    )
    conn.commit()
    db.record_deal(conn, _deal("stale", price=80_000, reference=100_000))

    rows = db.get_recent_deals(conn, window_days=90, limit=10, max_listing_age_seconds=3600)
    assert rows == []


def test_recent_deals_freshness_filter_keeps_listing_seen_recently():
    conn = db.connect(":memory:")
    db.record_observation(conn, _listing("fresh", 80_000))
    db.record_deal(conn, _deal("fresh", price=80_000, reference=100_000))

    rows = db.get_recent_deals(conn, window_days=90, limit=10, max_listing_age_seconds=3600)
    assert [r["listing_id"] for r in rows] == ["fresh"]


def test_recent_deals_without_freshness_filter_ignores_staleness():
    # max_listing_age_seconds is opt-in -- omitting it (the default)
    # preserves the old behavior for callers/tests that don't pass it.
    conn = db.connect(":memory:")
    db.record_deal(conn, _deal("no-observation", price=80_000, reference=100_000))

    rows = db.get_recent_deals(conn, window_days=90, limit=10)
    assert [r["listing_id"] for r in rows] == ["no-observation"]


def test_migrates_pre_basis_schema_without_data_loss(tmp_path):
    # The exact `deals` shape from before basis/retail columns ever
    # existed: market_reference_price and discount_fraction were NOT NULL,
    # no basis column at all. Already the current (post-retail-removal)
    # shape, so this must be a no-op migration, not a rebuild.
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
    assert rows[0]["market_reference_price"] == 100000
    assert rows[0]["source_label"] == "Phones"


def test_migrates_dual_basis_schema_dropping_retail_only_deals(tmp_path):
    # The exact `deals`/`retail_prices` shape from when retail comparison
    # existed: basis + nullable retail_* columns. Retail comparison has
    # since been removed entirely (árukereső.hu sits behind a Cloudflare
    # JS challenge no plain HTTP scraper can pass), so migrating must drop
    # retail-only rows (their used-median fields are NULL -- nothing sound
    # to backfill) while keeping used-median rows intact, and must drop
    # the now-unused retail_prices cache table without raising.
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
            basis TEXT NOT NULL DEFAULT 'used_median',
            market_reference_price REAL,
            discount_fraction REAL,
            sample_size INTEGER NOT NULL DEFAULT 0,
            retail_reference_price REAL,
            retail_discount_fraction REAL,
            retail_match_confidence REAL,
            detected_at TEXT NOT NULL,
            source_label TEXT
        );
        CREATE TABLE retail_prices (
            normalized_key TEXT PRIMARY KEY,
            product_title TEXT NOT NULL,
            price REAL NOT NULL,
            currency TEXT NOT NULL,
            url TEXT NOT NULL,
            match_confidence REAL NOT NULL,
            cached_at TEXT NOT NULL
        );
        """
    )
    raw.execute(
        "INSERT INTO deals (listing_id, title, url, price, currency, location, basis, "
        "market_reference_price, discount_fraction, sample_size, detected_at, source_label) "
        "VALUES ('1', 'Used Deal', 'https://x/1', 80000, 'HUF', 'Budapest', 'used_median', "
        "100000, 0.2, 3, '2026-01-01T00:00:00+00:00', 'Phones')"
    )
    raw.execute(
        "INSERT INTO deals (listing_id, title, url, price, currency, location, basis, "
        "retail_reference_price, retail_discount_fraction, retail_match_confidence, detected_at, source_label) "
        "VALUES ('2', 'Retail Deal', 'https://x/2', 50000, 'HUF', 'Budapest', 'retail', "
        "100000, 0.5, 0.9, '2026-01-01T00:00:00+00:00', 'Phones')"
    )
    raw.commit()
    raw.close()

    conn = db.connect(db_path)  # must not raise, and must migrate in place

    rows = db.get_recent_deals(conn, window_days=3650, limit=10)
    assert [r["listing_id"] for r in rows] == ["1"]  # the retail-only row was dropped
    assert rows[0]["market_reference_price"] == 100000

    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='retail_prices'")
    assert cur.fetchone() is None  # the retail cache table is gone too
