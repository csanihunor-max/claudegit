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

# Bump whenever _SCHEMA changes a table's shape in a way `CREATE TABLE IF
# NOT EXISTS` can't apply to an existing database on its own — a new
# column, or (as here) a NOT NULL constraint that needs relaxing, which
# SQLite's ALTER TABLE can't do directly. `_migrate` rebuilds only the
# specific tables that need it; a brand-new database is created at the
# current shape by `_SCHEMA` above and never touches `_migrate` at all.
_SCHEMA_VERSION = 3


def _migrate(conn: sqlite3.Connection) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    if current >= _SCHEMA_VERSION:
        return

    columns = {row["name"] for row in conn.execute("PRAGMA table_info(deals)")}
    if "basis" in columns:
        # Retail (árukereső.hu) comparison, and the `basis` column that
        # distinguished it from used-median, have been removed entirely —
        # árukereső.hu sits behind a Cloudflare JS challenge no plain HTTP
        # scraper can pass (confirmed directly: a fetch gets a "Just a
        # moment..." challenge page, not product markup), so it never
        # worked as a real comparison source. Rebuild `deals` back to
        # used-median-only shape. Retail-basis rows have NULL
        # market_reference_price/discount_fraction (there's no sound value
        # to backfill them with) and represented a comparison method that
        # no longer exists, so they're dropped rather than migrated.
        conn.execute("ALTER TABLE deals RENAME TO deals_old")
        conn.executescript(_SCHEMA)  # recreates `deals` at the current shape
        conn.execute(
            """
            INSERT INTO deals (listing_id, title, url, price, currency, location,
                                market_reference_price, discount_fraction, sample_size,
                                detected_at, source_label)
            SELECT listing_id, title, url, price, currency, location,
                   market_reference_price, discount_fraction, sample_size,
                   detected_at, source_label
            FROM deals_old
            WHERE basis = 'used_median'
            """
        )
        conn.execute("DROP TABLE deals_old")

    conn.execute("DROP TABLE IF EXISTS retail_prices")  # the retail-price cache, no longer used
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
                (listing_id, title, url, price, currency, location,
                 market_reference_price, discount_fraction, sample_size,
                 detected_at, source_label)
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


def get_recent_deals(
    conn: sqlite3.Connection,
    window_days: int,
    limit: int,
    *,
    max_listing_age_seconds: float | None = None,
) -> list[sqlite3.Row]:
    """The best current deals: one row per listing (its most recent
    detection within the window, so a re-scraped-but-still-underpriced
    listing shows up once, not once per cycle), ranked by discount desc.

    `max_listing_age_seconds`, when given, additionally requires the
    listing to have been freshly re-observed within that many seconds of
    now — i.e. it still parses as an active, non-jegelve listing (see
    `scraper/parser.py`'s `_is_iced`, which skips a reserved card before
    it ever becomes an observation). Without this, a listing flagged as a
    deal once keeps showing for the full `window_days` even after the
    seller marks it jegelve or sells it, since a deal row is never
    updated or removed after the fact — a real false positive this
    caught (a Meta Quest listing that had gone jegelve since being
    flagged, but kept showing as an active deal).
    """
    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).isoformat()
    query = """
        SELECT d.* FROM deals d
        INNER JOIN (
            SELECT listing_id, MAX(detected_at) AS latest_detected_at
            FROM deals
            WHERE detected_at >= ?
            GROUP BY listing_id
        ) latest
            ON d.listing_id = latest.listing_id AND d.detected_at = latest.latest_detected_at
    """
    params: list = [since]
    if max_listing_age_seconds is not None:
        fresh_since = (datetime.now(timezone.utc) - timedelta(seconds=max_listing_age_seconds)).isoformat()
        query += """
        INNER JOIN (
            SELECT listing_id, MAX(seen_at) AS last_seen_at
            FROM observations
            GROUP BY listing_id
        ) fresh
            ON fresh.listing_id = d.listing_id AND fresh.last_seen_at >= ?
        """
        params.append(fresh_since)
    query += """
        ORDER BY d.discount_fraction DESC
        LIMIT ?
    """
    params.append(limit)
    with closing(conn.cursor()) as cur:
        cur.execute(query, params)
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
