"""One full scrape-compare-notify cycle."""
from __future__ import annotations

import logging
import sqlite3
from collections import defaultdict

from .arbitrage.detector import evaluate
from .categories import label_for_url
from .config import Config
from .models import Deal, Listing
from .notify.base import Notifier
from .retail.client import ArukeresoClient
from .retail.lookup import find_retail_price
from .scraper.client import FetchError, HardveraproClient
from .scraper.parser import parse_search_results
from .storage import db

logger = logging.getLogger(__name__)

_PAGE_SIZE = 100  # hardverapro.hu's category pages show this many listings per page


def _offset_url(base_url: str, offset: int) -> str:
    if offset <= 0:
        return base_url
    sep = "&" if "?" in base_url else "?"
    return f"{base_url}{sep}offset={offset}"


def _handle_deal(
    conn: sqlite3.Connection, deal: Deal, source_label: str, notifiers: list[Notifier], deals: list[Deal]
) -> None:
    db.record_deal(conn, deal, source_label=source_label)  # feeds the dashboard, independent of notification dedup

    if db.has_been_notified(conn, deal.listing.listing_id, deal.listing.price):
        return
    for notifier in notifiers:
        notifier.notify(deal)
    db.mark_notified(conn, deal.listing.listing_id, deal.listing.price)
    deals.append(deal)


def _retail_fallback_pass(
    config: Config,
    conn: sqlite3.Connection,
    pending: dict[str, list[tuple[Listing, str]]],
    notifiers: list[Notifier],
    deals: list[Deal],
) -> None:
    """For listings that didn't qualify via used-median, try retail
    comparison — one lookup per distinct normalized_key (many listings can
    share one), cached, and budget-capped per cycle. `pending` maps
    normalized_key -> [(listing, source_label), ...].
    """
    if not config.retail_enabled or not pending:
        return

    lookups_done = 0
    retail_client: ArukeresoClient | None = None

    try:
        for normalized_key, entries in pending.items():
            retail_price = db.get_cached_retail_price(conn, normalized_key, config.retail_cache_days)

            if retail_price is None:
                if lookups_done >= config.retail_max_lookups_per_cycle:
                    continue  # budget spent this cycle; try again next cycle
                if retail_client is None:
                    retail_client = ArukeresoClient(config)
                retail_price = find_retail_price(normalized_key, retail_client)
                lookups_done += 1
                if retail_price is not None:
                    db.cache_retail_price(conn, normalized_key, retail_price)

            if retail_price is None:
                continue

            for listing, source_label in entries:
                recent_prices = db.get_recent_prices(
                    conn, normalized_key, config.reference_window_days, exclude_listing_id=listing.listing_id
                )
                deal = evaluate(listing, recent_prices, config, retail_price=retail_price)
                if deal is not None:
                    _handle_deal(conn, deal, source_label, notifiers, deals)
    finally:
        if retail_client is not None:
            retail_client.close()


def run_once(config: Config, conn: sqlite3.Connection, client: HardveraproClient, notifiers: list[Notifier]) -> list[Deal]:
    """Fetch every configured search URL, record what we saw, and return
    the deals newly flagged this cycle (already de-duplicated against
    previously-notified listing/price pairs, and already sent to every
    notifier).

    Two passes: used-median comparison first (the primary signal, cheap —
    no network beyond the hardverapro fetch itself already needed). Then,
    only for listings that didn't qualify that way, a budget-capped retail
    comparison pass (see `_retail_fallback_pass`).
    """
    deals: list[Deal] = []
    pending_for_retail: dict[str, list[tuple[Listing, str]]] = defaultdict(list)

    for url in config.search_urls:
        source_label = label_for_url(url)

        for page in range(config.max_pages_per_category):
            page_url = _offset_url(url, page * _PAGE_SIZE)
            try:
                html = client.get(page_url)
            except FetchError:
                logger.exception("failed to fetch %s, skipping any further pages of this category this cycle", page_url)
                break

            listings = parse_search_results(html)
            logger.info("%s: %d listings parsed", page_url, len(listings))
            if not listings:
                break  # reached the end of the category (or, rarely, a page that's entirely jegelve/malformed)

            for listing in listings:
                db.record_observation(conn, listing)

                recent_prices = db.get_recent_prices(
                    conn, listing.normalized_key, config.reference_window_days, exclude_listing_id=listing.listing_id
                )
                deal = evaluate(listing, recent_prices, config)
                if deal is not None:
                    _handle_deal(conn, deal, source_label, notifiers, deals)
                else:
                    pending_for_retail[listing.normalized_key].append((listing, source_label))

    _retail_fallback_pass(config, conn, pending_for_retail, notifiers, deals)

    return deals
