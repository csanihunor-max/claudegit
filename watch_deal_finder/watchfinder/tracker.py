"""Change detection: turn a fresh batch of listings into new / price-drop events,
and decide which previously seen listings have disappeared."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Mapping

from .comps import identify
from .config import AppConfig, SearchConfig
from .models import Event, EventKind, Listing
from .pricing import to_huf
from .sources.base import Source
from .storage import Storage

log = logging.getLogger(__name__)


def record_results(
    storage: Storage,
    config: AppConfig,
    search: SearchConfig,
    source: str,
    listings: list[Listing],
    now: str,
) -> list[Event]:
    """Store one search's results and return what changed.

    The first time a (search, source) pair runs, everything already listed is
    stored silently (when `silent_first_pass` is on) so you don't get dozens of
    alerts for old ads on day one.
    """
    announce_new = storage.is_seeded(search.name, source) or not config.silent_first_pass
    events: list[Event] = []
    with storage.transaction():
        for listing in listings:
            price_huf = to_huf(listing.price, listing.currency, config.eur_huf_rate)
            row = storage.get(listing.source, listing.listing_id)
            if row is None:
                storage.insert(listing, price_huf, now)
                if announce_new:
                    events.append(Event(EventKind.NEW, search.name, listing, price_huf))
            else:
                old_huf = row["price_huf"]
                storage.update_seen(listing, price_huf, now)
                if price_huf != old_huf:
                    storage.add_price_point(listing, price_huf, now)
                    if old_huf is not None and price_huf is not None and price_huf < old_huf:
                        events.append(Event(EventKind.PRICE_DROP, search.name, listing, price_huf, old_huf))
            storage.link_search(listing.source, listing.listing_id, search.name)
            if listing.details is not None or row is None or not row["ident"]:
                # identify the watch while the ad text is at hand (the text itself isn't stored)
                storage.set_ident(listing.source, listing.listing_id,
                                  identify(listing.title, listing.details, search.keywords).to_json())
        storage.mark_seeded(search.name, source, now)
    return events


def detect_gone(
    storage: Storage,
    config: AppConfig,
    sources: Mapping[str, Source],
    outcomes: Mapping[tuple[str, str], bool],
    pass_started: str,
    now: str,
) -> list[tuple[str, str]]:
    """Mark listings as gone. Returns the (source, listing_id) keys marked.

    `outcomes` maps each (search name, source) that ran *successfully* this pass
    to whether its results were complete. A listing not seen by any search this
    pass is:
    - marked gone straight away if one of its searches returned a complete result
      set (so it would have been in there);
    - otherwise (it may simply have dropped off page 1) checked directly on the
      site once it has been unseen for `gone_check_after_hours`, a few per pass.
    Failed searches are absent from `outcomes`, so a network error never marks
    anything gone.
    """
    candidates: dict[tuple[str, str], tuple[Listing, bool, str | None, str]] = {}
    for (search_name, source), complete in outcomes.items():
        for row in storage.active_for_search(search_name, source):
            if row["last_seen"] >= pass_started:
                continue
            key = (row["source"], row["listing_id"])
            prev_complete = candidates[key][1] if key in candidates else False
            candidates[key] = (_row_to_listing(row), prev_complete or complete, row["last_checked"], row["last_seen"])

    gone: list[tuple[str, str]] = []
    threshold = (datetime.fromisoformat(now) - timedelta(hours=config.gone_check_after_hours)).isoformat()
    to_check: list[tuple[str, Listing]] = []
    with storage.transaction():
        for key, (listing, complete, last_checked, last_seen) in candidates.items():
            if complete:
                storage.mark_gone(*key, now)
                gone.append(key)
            elif last_seen < threshold and (last_checked is None or last_checked < threshold):
                to_check.append((last_checked or "", listing))

    # Least recently checked first, capped so a big backlog doesn't flood the site.
    to_check.sort(key=lambda item: item[0])
    for _, listing in to_check[: config.max_gone_checks_per_pass]:
        source = sources.get(listing.source)
        if source is None:
            continue
        verdict = source.is_gone(listing)
        with storage.transaction():
            if verdict is True:
                storage.mark_gone(listing.source, listing.listing_id, now)
                gone.append(listing.key)
            elif verdict is False:
                storage.mark_checked(listing.source, listing.listing_id, now)
    if gone:
        log.info("marked %d listing(s) as gone", len(gone))
    return gone


def _row_to_listing(row) -> Listing:
    return Listing(
        source=row["source"],
        listing_id=row["listing_id"],
        title=row["title"],
        price=row["price"],
        currency=row["currency"],
        url=row["url"],
        location=row["location"],
        thumbnail_url=row["thumbnail_url"],
        category=row["category"],
    )
