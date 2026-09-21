"""SQLite persistence: every scraped price point, every deal we've ever
flagged (for the dashboard), and which deals we've already alerted on (so
the hourly loop doesn't re-notify the same listing at the same price every
single cycle).
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from ..models import Deal, Listing

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
    market_reference_price REAL NOT NULL,
    discount_fraction REAL NOT NULL,
    sample_size INTEGER NOT NULL,
    detected_at TEXT NOT NULL,
    source_label TEXT
);
CREATE INDEX IF NOT EXISTS idx_deals_listing ON deals (listing_id, detected_at);
CREATE INDEX IF NOT EXISTS idx_deals_detected_at ON deals (detected_at);
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # supports both row["col"] and row[0]
    conn.executescript(_SCHEMA)
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
                (listing_id, title, url, price, currency, location,
                 market_reference_price, discount_fraction, sample_size, detected_at, source_label)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                listing.listing_id,
                listing.title,
                listing.url,
                listing.price,
                listing.currency,
                listing.location,
                deal.market_reference_price,
                deal.discount_fraction,
                deal.sample_size,
                listing.seen_at.isoformat(),
                source_label,
            ),
        )
    conn.commit()


def get_recent_deals(conn: sqlite3.Connection, window_days: int, limit: int) -> list[sqlite3.Row]:
    """The best current deals: one row per listing (its most recent
    detection within the window, so a re-scraped-but-still-underpriced
    listing shows up once, not once per cycle), ranked biggest-discount
    first and, for ties, biggest absolute savings first.
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
            ORDER BY d.discount_fraction DESC, (d.market_reference_price - d.price) DESC
            LIMIT ?
            """,
            (since, limit),
        )
        return cur.fetchall()


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
