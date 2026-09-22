"""One full scrape-compare-notify cycle."""
from __future__ import annotations

import logging
import sqlite3

from .arbitrage.detector import evaluate
from .categories import label_for_url
from .config import Config
from .models import Deal
from .notify.base import Notifier
from .scraper.client import FetchError, HardveraproClient
from .scraper.normalize import is_bundle_or_generic_key, is_digital_good
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


def run_once(config: Config, conn: sqlite3.Connection, client: HardveraproClient, notifiers: list[Notifier]) -> list[Deal]:
    """Fetch every configured search URL, record what we saw, and return
    the deals newly flagged this cycle (already de-duplicated against
    previously-notified listing/price pairs, and already sent to every
    notifier).
    """
    deals: list[Deal] = []

    for url in config.search_urls:
        source_label = label_for_url(url)
        seen_ids: set[str] = set()

        for page in range(config.max_pages_per_category):
            page_url = _offset_url(url, page * _PAGE_SIZE)
            try:
                html = client.get(page_url)
            except FetchError:
                logger.exception("failed to fetch %s, skipping any further pages of this category this cycle", page_url)
                break

            page_listings = parse_search_results(html)
            # A page whose offset exceeds the category's real size doesn't
            # come back empty — the site wraps around and re-serves page 1
            # (verified against a real fetch), so "0 listings" never fires
            # as a stop condition for a small category. Stop instead the
            # moment a page introduces no listing we haven't already
            # recorded this cycle, and only process the genuinely new ones.
            listings = [listing for listing in page_listings if listing.listing_id not in seen_ids]
            logger.info("%s: %d listings parsed (%d new)", page_url, len(page_listings), len(listings))
            if not listings:
                break
            seen_ids.update(listing.listing_id for listing in listings)

            for listing in listings:
                db.record_observation(conn, listing)

                # A bundle/lot listing, one too generic to be a single
                # comparable product, or a digital good (subscription,
                # game key, license -- see normalize.py's
                # is_bundle_or_generic_key / is_digital_good) is skipped
                # entirely here -- not just excluded from qualifying as a
                # deal itself, but never evaluated at all, so it also
                # never becomes a false "comparable" for some other
                # listing sharing the same key. Still recorded as an
                # observation above, for historical completeness.
                if is_bundle_or_generic_key(listing.normalized_key) or is_digital_good(listing.normalized_key):
                    continue

                recent_prices = db.get_recent_prices(
                    conn, listing.normalized_key, config.reference_window_days, exclude_listing_id=listing.listing_id
                )
                deal = evaluate(listing, recent_prices, config)
                if deal is not None:
                    _handle_deal(conn, deal, source_label, notifiers, deals)

    return deals
