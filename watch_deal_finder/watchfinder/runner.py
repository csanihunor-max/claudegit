"""One polling pass, and the scheduled loop around it."""

from __future__ import annotations

import logging
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Mapping

from .config import AppConfig
from .filters import filter_listings
from .models import Event
from .market import GroupStats, stats_from_storage
from .notify import Notifier, format_alert, should_alert
from .sources.base import Source, SourceError
from .storage import Storage, utcnow
from .tracker import detect_gone, record_results

log = logging.getLogger(__name__)


@dataclass
class PassSummary:
    fetched: int = 0
    kept: int = 0
    events: list[Event] = field(default_factory=list)
    alerts_sent: int = 0
    gone: int = 0
    failures: list[str] = field(default_factory=list)


class Runner:
    def __init__(
        self,
        config: AppConfig,
        storage: Storage,
        sources: Mapping[str, Source],
        notifier: Notifier,
        now: Callable[[], str] = utcnow,
    ):
        self.config = config
        self.storage = storage
        self.sources = sources
        self.notifier = notifier
        self._now = now
        self._unsent: list[Event] = []  # alerts whose send failed; retried next pass
        self.market: dict[str, GroupStats] = {}

    def run_once(self) -> PassSummary:
        summary = PassSummary()
        pass_started = self._now()
        # Market references from what was known before this pass, so a new listing is
        # never compared with itself.
        self.market = stats_from_storage(self.storage, self.config)
        outcomes: dict[tuple[str, str], bool] = {}

        for search in self.config.searches:
            for source_name in search.sources:
                source = self.sources.get(source_name)
                if source is None:
                    continue  # disabled (e.g. eBay without API keys)
                try:
                    result = source.search(search)
                except SourceError as exc:
                    log.error("%s / %s failed: %s", search.name, source_name, exc)
                    summary.failures.append(f"{search.name}/{source_name}: {exc}")
                    continue
                kept = filter_listings(result.listings, search, self.config)
                events = record_results(self.storage, self.config, search, source_name, kept, self._now())
                outcomes[(search.name, source_name)] = result.complete
                summary.fetched += len(result.listings)
                summary.kept += len(kept)
                summary.events.extend(events)
                log.info(
                    "%s / %s: %d fetched, %d kept, %d new/drop event(s)%s",
                    search.name, source_name, len(result.listings), len(kept), len(events),
                    "" if result.complete else " (partial: more results than one page)",
                )
                summary.alerts_sent += self._notify(events)

        if self._unsent:
            retry, self._unsent = self._unsent, []
            summary.alerts_sent += self._notify(retry)

        summary.gone = len(detect_gone(self.storage, self.config, self.sources, outcomes, pass_started, self._now()))
        log.info(
            "pass done: %d listing(s) kept, %d event(s), %d alert(s) sent, %d gone, %d failure(s)",
            summary.kept, len(summary.events), summary.alerts_sent, summary.gone, len(summary.failures),
        )
        return summary

    def _notify(self, events: list[Event]) -> int:
        sent = 0
        for event in events:
            search = self.config.search(event.search_name)
            if search is None or not should_alert(event, search, self.config, self.storage):
                continue
            if self.notifier.send(format_alert(event, search, self.config, self.market)):
                self.storage.record_alert(
                    event.listing.source, event.listing.listing_id, event.price_huf, event.kind.value, self._now()
                )
                sent += 1
            else:
                self._unsent = (self._unsent + [event])[-100:]
        return sent

    def run_forever(self, sleep: Callable[[float], None] = time.sleep) -> None:
        interval = self.config.poll_interval_minutes * 60
        log.info("starting loop: every %.0f min", self.config.poll_interval_minutes)
        while True:
            try:
                self.run_once()
            except Exception:  # keep the loop alive; the next pass may well work
                log.exception("pass crashed")
            # Up to +15% jitter so requests don't land at the same minute every time
            # (never shorter than the configured interval).
            wait = interval * random.uniform(1.0, 1.15)
            log.info("next pass in %.1f min", wait / 60)
            sleep(wait)
