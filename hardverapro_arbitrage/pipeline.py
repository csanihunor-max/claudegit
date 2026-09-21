"""One full scrape-compare-notify cycle."""
from __future__ import annotations

import logging
import sqlite3

from .arbitrage.detector import evaluate
from .config import Config
from .models import Deal
from .notify.base import Notifier
from .scraper.client import FetchError, HardveraproClient
from .scraper.parser import parse_search_results
from .storage import db

logger = logging.getLogger(__name__)


def run_once(config: Config, conn: sqlite3.Connection, client: HardveraproClient, notifiers: list[Notifier]) -> list[Deal]:
    """Fetch every configured search URL, record what we saw, and return
    the deals newly flagged this cycle (already de-duplicated against
    previously-notified listing/price pairs, and already sent to every
    notifier).
    """
    deals: list[Deal] = []

    for url in config.search_urls:
        try:
            html = client.get(url)
        except FetchError:
            logger.exception("failed to fetch %s, skipping this cycle", url)
            continue

        listings = parse_search_results(html)
        logger.info("%s: %d listings parsed", url, len(listings))

        for listing in listings:
            db.record_observation(conn, listing)

            recent_prices = db.get_recent_prices(
                conn,
                listing.normalized_key,
                config.reference_window_days,
                exclude_listing_id=listing.listing_id,
            )
            deal = evaluate(listing, recent_prices, config)
            if deal is None:
                continue
            if db.has_been_notified(conn, listing.listing_id, listing.price):
                continue

            for notifier in notifiers:
                notifier.notify(deal)
            db.mark_notified(conn, listing.listing_id, listing.price)
            deals.append(deal)

    return deals
