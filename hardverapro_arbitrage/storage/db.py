"""SQLite persistence: every scraped price point, and which deals we've
already alerted on (so the hourly loop doesn't re-notify the same listing
at the same price every single cycle).
"""
from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

from ..models import Listing

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
"""


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
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
