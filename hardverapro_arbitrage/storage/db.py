"""SQLite persistence: every scraped price point, every deal we've ever
flagged (for the dashboard), and which deals we've already alerted on (so
the hourly loop doesn't re-notify the same listing at the same price every
single cycle).
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from ..models import Deal, Listing, RetailPrice

_SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id TEXT NOT NULL,
    normalized_key TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    location TEXT,
    seen_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_observations_key ON observations (normalized_key, seen_at);
CREATE INDEX IF NOT EXISTS idx_observations_listing ON observations (listing_id, seen_at);

CREATE TABLE IF NOT EXISTS notified_deals (
    listing_id TEXT NOT NULL,
    price REAL NOT NULL,
    notified_at TEXT NOT NULL,
    PRIMARY KEY (listing_id, price)
);

-- Every time evaluate() flags a listing as a deal, regardless of whether
-- it had already been notified on — this is what the web dashboard reads,
-- independent of notification history.
CREATE TABLE IF NOT EXISTS deals (
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
CREATE INDEX IF NOT EXISTS idx_deals_listing ON deals (listing_id, detected_at);
CREATE INDEX IF NOT EXISTS idx_deals_detected_at ON deals (detected_at);

-- Retail (árukereső) lookups are cached per normalized item, not per
-- listing: many listings share one normalized_key, and retail prices
-- barely move hour to hour, so there's no reason to re-search for every
-- re-scrape of every listing.
CREATE TABLE IF NOT EXISTS retail_prices (
    normalized_key TEXT PRIMARY KEY,
    product_title TEXT NOT NULL,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    url TEXT NOT NULL,
    match_confidence REAL NOT NULL,
    cached_at TEXT NOT NULL
);
"""

# Bump whenever _SCHEMA changes a table's shape in a way `CREATE TABLE IF
# NOT EXISTS` can't apply to an existing database on its own — a new
# column, or (as here) a NOT NULL constraint that needs relaxing, which
# SQLite's ALTER TABLE can't do directly. `_migrate` rebuilds only the
# specific tables that need it; a brand-new database is created at the
# current shape by `_SCHEMA` above and never touches `_migrate` at all.
_SCHEMA_VERSION = 2


def _migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= _SCHEMA_VERSION:
        return

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(deals)")}
    if "basis" not in columns:
        # Pre-dates the retail-comparison feature: market_reference_price
        # and discount_fraction were NOT NULL, which ALTER TABLE ADD
        # COLUMN can't retrofit around — rebuild the table instead.
        # Every existing row was scored by used-median (the only
        # comparison that existed then), so backfilling basis is exact,
        # not a guess.
        conn.execute("ALTER TABLE deals RENAME TO deals_old")
        conn.executescript(_SCHEMA)  # recreates `deals` (and any other new table) at the current shape
        conn.execute(
            """
            INSERT INTO deals (listing_id, title, url, price, currency, location,
                                basis, market_reference_price, discount_fraction, sample_size,
                                detected_at, source_label)
            SELECT listing_id, title, url, price, currency, location,
                   'used_median', market_reference_price, discount_fraction, sample_size,
                   detected_at, source_label
            FROM deals_old
            """
        )
        conn.execute("DROP TABLE deals_old")

    conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # supports both row["col"] and row[0]
    conn.executescript(_SCHEMA)  # no-ops on tables that already exist, whatever shape they're in
    _migrate(conn)
    conn.commit()
    return conn


def record_observation(conn: sqlite3.Connection, listing: Listing) -> None:
    with closing(conn.cursor()) as cur:
        cur.execute(
            """
            INSERT INTO observations
                (listing_id, normalized_key, title, url, price, currency, location, seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing.listing_id,
                listing.normalized_key,
                listing.title,
                listing.url,
                listing.price,
                listing.currency,
                listing.location,
                listing.seen_at.isoformat(),
            ),
        )
    conn.commit()


def get_recent_prices(
    conn: sqlite3.Connection,
    normalized_key: str,
    window_days: int,
    *,
    exclude_listing_id: str | None = None,
) -> list[float]:
    """Prices observed for this normalized item within the reference
    window, most-recent observation per listing_id only (so one item that
    got re-scraped 90 times doesn't dominate the median over 90 distinct
    items each scraped once).
    """
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    with closing(conn.cursor()) as cur:
        cur.execute(
            """
            SELECT price FROM (
                SELECT listing_id, price, MAX(seen_at) AS latest_seen
                FROM observations
                WHERE normalized_key = ? AND seen_at >= ?
                GROUP BY listing_id
            )
            WHERE (? IS NULL OR listing_id != ?)
            """,
            (normalized_key, since, exclude_listing_id, exclude_listing_id),
        )
        return [row[0] for row in cur.fetchall()]


def record_deal(conn: sqlite3.Connection, deal: Deal, *, source_label: str | None = None) -> None:
    listing = deal.listing
    with closing(conn.cursor()) as cur:
        cur.execute(
            """
            INSERT INTO deals
                (listing_id, title, url, price, currency, location, basis,
                 market_reference_price, discount_fraction, sample_size,
                 retail_reference_price, retail_discount_fraction, retail_match_confidence,
                 detected_at, source_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing.listing_id,
                listing.title,
                listing.url,
                listing.price,
                listing.currency,
                listing.location,
                deal.basis,
                deal.market_reference_price,
                deal.discount_fraction,
                deal.sample_size,
                deal.retail_reference_price,
                deal.retail_discount_fraction,
                deal.retail_match_confidence,
                listing.seen_at.isoformat(),
                source_label,
            ),
        )
    conn.commit()


def get_recent_deals(conn: sqlite3.Connection, window_days: int, limit: int) -> list[sqlite3.Row]:
    """The best current deals: one row per listing (its most recent
    detection within the window, so a re-scraped-but-still-underpriced
    listing shows up once, not once per cycle). Ranked with used-median
    deals first (the primary signal), by their own discount desc, then
    retail-only deals after, by their retail discount desc — never
    interleaved by raw number, since a 25% used-median discount and a 50%
    retail discount aren't the same kind of signal.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    with closing(conn.cursor()) as cur:
        cur.execute(
            """
            SELECT d.* FROM deals d
            INNER JOIN (
                SELECT listing_id, MAX(detected_at) AS latest_detected_at
                FROM deals
                WHERE detected_at >= ?
                GROUP BY listing_id
            ) latest
                ON d.listing_id = latest.listing_id AND d.detected_at = latest.latest_detected_at
            ORDER BY
                CASE WHEN d.basis = 'used_median' THEN 0 ELSE 1 END ASC,
                CASE WHEN d.basis = 'used_median' THEN d.discount_fraction ELSE d.retail_discount_fraction END DESC
            LIMIT ?
            """,
            (since, limit),
        )
        return cur.fetchall()


def get_cached_retail_price(conn: sqlite3.Connection, normalized_key: str, max_age_days: int) -> RetailPrice | None:
    since = (datetime.now(timezone.utc) - timedelta(days=max_age_days)).isoformat()
    with closing(conn.cursor()) as cur:
        cur.execute(
            "SELECT * FROM retail_prices WHERE normalized_key = ? AND cached_at >= ?",
            (normalized_key, since),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return RetailPrice(
        product_title=row["product_title"],
        price=row["price"],
        currency=row["currency"],
        url=row["url"],
        match_confidence=row["match_confidence"],
    )


def cache_retail_price(conn: sqlite3.Connection, normalized_key: str, retail_price: RetailPrice) -> None:
    with closing(conn.cursor()) as cur:
        cur.execute(
            """
            INSERT INTO retail_prices (normalized_key, product_title, price, currency, url, match_confidence, cached_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(normalized_key) DO UPDATE SET
                product_title = excluded.product_title,
                price = excluded.price,
                currency = excluded.currency,
                url = excluded.url,
                match_confidence = excluded.match_confidence,
                cached_at = excluded.cached_at
            """,
            (
                normalized_key,
                retail_price.product_title,
                retail_price.price,
                retail_price.currency,
                retail_price.url,
                retail_price.match_confidence,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    conn.commit()


def has_been_notified(conn: sqlite3.Connection, listing_id: str, price: float) -> bool:
    with closing(conn.cursor()) as cur:
        cur.execute(
            "SELECT 1 FROM notified_deals WHERE listing_id = ? AND price = ?",
            (listing_id, price),
        )
        return cur.fetchone() is not None


def mark_notified(conn: sqlite3.Connection, listing_id: str, price: float) -> None:
    with closing(conn.cursor()) as cur:
        cur.execute(
            "INSERT OR IGNORE INTO notified_deals (listing_id, price, notified_at) VALUES (?, ?, ?)",
            (listing_id, price, datetime.now(timezone.utc).isoformat()),
        )
    conn.commit()
