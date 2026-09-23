"""SQLite storage: listings, their price history, which searches they matched,
and which alerts were already sent."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import Listing

USER_STATUSES = ("interested", "bought", "ignore")

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    source        TEXT NOT NULL,
    listing_id    TEXT NOT NULL,
    title         TEXT NOT NULL,
    price         REAL,
    currency      TEXT NOT NULL,
    price_huf     INTEGER,
    url           TEXT NOT NULL,
    location      TEXT,
    thumbnail_url TEXT,
    category      TEXT,
    first_seen    TEXT NOT NULL,
    last_seen     TEXT NOT NULL,
    last_checked  TEXT,
    status        TEXT NOT NULL DEFAULT 'active',   -- active | gone
    gone_at       TEXT,
    user_status   TEXT,                             -- NULL | interested | bought | ignore
    PRIMARY KEY (source, listing_id)
);

CREATE TABLE IF NOT EXISTS price_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    listing_id  TEXT NOT NULL,
    price       REAL,
    currency    TEXT NOT NULL,
    price_huf   INTEGER,
    seen_at     TEXT NOT NULL,
    FOREIGN KEY (source, listing_id) REFERENCES listings (source, listing_id)
);
CREATE INDEX IF NOT EXISTS idx_price_history_listing ON price_history (source, listing_id, seen_at);

CREATE TABLE IF NOT EXISTS listing_searches (
    source      TEXT NOT NULL,
    listing_id  TEXT NOT NULL,
    search_name TEXT NOT NULL,
    PRIMARY KEY (source, listing_id, search_name)
);

CREATE TABLE IF NOT EXISTS alerts_sent (
    source      TEXT NOT NULL,
    listing_id  TEXT NOT NULL,
    price_huf   INTEGER NOT NULL,   -- -1 when the listing has no price
    kind        TEXT NOT NULL,
    sent_at     TEXT NOT NULL,
    PRIMARY KEY (source, listing_id, price_huf)
);

CREATE TABLE IF NOT EXISTS search_state (
    search_name TEXT NOT NULL,
    source      TEXT NOT NULL,
    seeded_at   TEXT NOT NULL,
    PRIMARY KEY (search_name, source)
);
"""


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class Storage:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")  # dashboard can read while the loop writes
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.conn:
            yield self.conn

    # -- listings ---------------------------------------------------------

    def get(self, source: str, listing_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM listings WHERE source = ? AND listing_id = ?", (source, listing_id)
        ).fetchone()

    def insert(self, listing: Listing, price_huf: int | None, now: str) -> None:
        self.conn.execute(
            """INSERT INTO listings (source, listing_id, title, price, currency, price_huf, url,
                   location, thumbnail_url, category, first_seen, last_seen)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (listing.source, listing.listing_id, listing.title, listing.price, listing.currency, price_huf,
             listing.url, listing.location, listing.thumbnail_url, listing.category, now, now),
        )
        self.add_price_point(listing, price_huf, now)

    def update_seen(self, listing: Listing, price_huf: int | None, now: str) -> None:
        """Refresh a known listing; reactivates it if it had been marked gone."""
        self.conn.execute(
            """UPDATE listings SET title = ?, price = ?, currency = ?, price_huf = ?, url = ?, location = ?,
                   thumbnail_url = ?, category = ?, last_seen = ?, status = 'active', gone_at = NULL
               WHERE source = ? AND listing_id = ?""",
            (listing.title, listing.price, listing.currency, price_huf, listing.url, listing.location,
             listing.thumbnail_url, listing.category, now, listing.source, listing.listing_id),
        )

    def add_price_point(self, listing: Listing, price_huf: int | None, now: str) -> None:
        self.conn.execute(
            "INSERT INTO price_history (source, listing_id, price, currency, price_huf, seen_at) VALUES (?, ?, ?, ?, ?, ?)",
            (listing.source, listing.listing_id, listing.price, listing.currency, price_huf, now),
        )

    def link_search(self, source: str, listing_id: str, search_name: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO listing_searches (source, listing_id, search_name) VALUES (?, ?, ?)",
            (source, listing_id, search_name),
        )

    def active_for_search(self, search_name: str, source: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """SELECT l.* FROM listings l
               JOIN listing_searches s ON s.source = l.source AND s.listing_id = l.listing_id
               WHERE s.search_name = ? AND l.source = ? AND l.status = 'active'""",
            (search_name, source),
        ).fetchall()

    def mark_gone(self, source: str, listing_id: str, now: str) -> None:
        self.conn.execute(
            "UPDATE listings SET status = 'gone', gone_at = ? WHERE source = ? AND listing_id = ? AND status = 'active'",
            (now, source, listing_id),
        )

    def mark_checked(self, source: str, listing_id: str, now: str) -> None:
        self.conn.execute(
            "UPDATE listings SET last_checked = ? WHERE source = ? AND listing_id = ?", (now, source, listing_id)
        )

    def set_user_status(self, source: str, listing_id: str, status: str | None) -> bool:
        if status is not None and status not in USER_STATUSES:
            raise ValueError(f"status must be one of {USER_STATUSES} or None")
        cur = self.conn.execute(
            "UPDATE listings SET user_status = ? WHERE source = ? AND listing_id = ?", (status, source, listing_id)
        )
        self.conn.commit()
        return cur.rowcount > 0

    def price_history(self, source: str, listing_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT price, currency, price_huf, seen_at FROM price_history WHERE source = ? AND listing_id = ? ORDER BY seen_at, id",
            (source, listing_id),
        ).fetchall()

    # -- alerts / seeding ------------------------------------------------

    def alert_already_sent(self, source: str, listing_id: str, price_huf: int | None) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM alerts_sent WHERE source = ? AND listing_id = ? AND price_huf = ?",
            (source, listing_id, -1 if price_huf is None else price_huf),
        ).fetchone() is not None

    def record_alert(self, source: str, listing_id: str, price_huf: int | None, kind: str, now: str) -> None:
        with self.conn:
            self.conn.execute(
                "INSERT OR IGNORE INTO alerts_sent (source, listing_id, price_huf, kind, sent_at) VALUES (?, ?, ?, ?, ?)",
                (source, listing_id, -1 if price_huf is None else price_huf, kind, now),
            )

    def is_seeded(self, search_name: str, source: str) -> bool:
        return self.conn.execute(
            "SELECT 1 FROM search_state WHERE search_name = ? AND source = ?", (search_name, source)
        ).fetchone() is not None

    def mark_seeded(self, search_name: str, source: str, now: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO search_state (search_name, source, seeded_at) VALUES (?, ?, ?)",
            (search_name, source, now),
        )

    # -- dashboard queries ------------------------------------------------

    def dashboard_rows(self, include_gone: bool = False) -> list[dict[str, Any]]:
        where = "" if include_gone else "WHERE l.status = 'active'"
        rows = self.conn.execute(
            f"""SELECT l.*, GROUP_CONCAT(s.search_name, '\x1f') AS searches
                FROM listings l
                LEFT JOIN listing_searches s ON s.source = l.source AND s.listing_id = l.listing_id
                {where}
                GROUP BY l.source, l.listing_id"""
        ).fetchall()
        history: dict[tuple[str, str], list[int | None]] = {}
        for h in self.conn.execute("SELECT source, listing_id, price_huf FROM price_history ORDER BY seen_at, id"):
            points = history.setdefault((h["source"], h["listing_id"]), [])
            if not points or points[-1] != h["price_huf"]:
                points.append(h["price_huf"])
        out = []
        for r in rows:
            d = dict(r)
            d["searches"] = sorted(set(r["searches"].split("\x1f"))) if r["searches"] else []
            d["price_history"] = history.get((r["source"], r["listing_id"]), [])
            out.append(d)
        return out
