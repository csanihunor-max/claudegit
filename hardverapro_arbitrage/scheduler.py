"""Run the pipeline forever, once per poll_interval_seconds. One cycle
raising an exception logs it and waits for the next tick instead of
killing the process — a single bad page fetch or a transient parse error
shouldn't take down an hours-long-running bot.
"""
from __future__ import annotations

import logging
import time

from .config import Config
from .notify.base import Notifier
from .pipeline import run_once
from .scraper.client import HardveraproClient
from .storage import db

logger = logging.getLogger(__name__)


def run_forever(config: Config, notifiers: list[Notifier]) -> None:
    conn = db.connect(config.db_path)
    try:
        with HardveraproClient(config) as client:
            while True:
                cycle_start = time.monotonic()
                try:
                    deals = run_once(config, conn, client, notifiers)
                    logger.info("cycle complete: %d new deal(s)", len(deals))
                except Exception:
                    logger.exception("scrape cycle failed, will retry next interval")

                elapsed = time.monotonic() - cycle_start
                sleep_for = max(0.0, config.poll_interval_seconds - elapsed)
                time.sleep(sleep_for)
    finally:
        conn.close()
