"""Entry point: `python -m hardverapro_arbitrage [--once | --serve | --all]`."""
from __future__ import annotations

import argparse
import logging
import sys
import threading

from .config import Config
from .notify.base import Notifier
from .notify.console import ConsoleNotifier
from .notify.telegram import TelegramNotifier
from .pipeline import run_once
from .scheduler import run_forever
from .scraper.client import HardveraproClient
from .storage import db


def _build_notifiers(config: Config) -> list[Notifier]:
    notifiers: list[Notifier] = [ConsoleNotifier()]
    if config.telegram_bot_token and config.telegram_chat_id:
        notifiers.append(TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id))
    return notifiers


def _run_all(config: Config, notifiers: list[Notifier]) -> None:
    """Run the scrape loop and the web dashboard together in a single
    process/command — the scrape loop in a background thread, the
    dashboard's dev server blocking in the main thread. Simplest way to
    run this as one persistent "server": one process to start, one to
    keep alive under whatever supervises it (a terminal, a service
    manager, Task Scheduler, etc).
    """
    from .web import run as run_web

    loop_thread = threading.Thread(
        target=run_forever, args=(config, notifiers), name="scrape-loop", daemon=True
    )
    loop_thread.start()
    run_web(config)  # blocks until interrupted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hardverapro arbitrage scraper")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="run a single scrape cycle and exit")
    mode.add_argument(
        "--serve",
        action="store_true",
        help="run only the read-only web dashboard (see README for exposing it remotely)",
    )
    mode.add_argument(
        "--all",
        action="store_true",
        help="run the scrape loop and the web dashboard together in one process (recommended for normal use)",
    )
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = Config()

    if args.serve:
        # The dashboard only reads existing data — it doesn't need a
        # configured search URL to start, only to have anything to show.
        from .web import run as run_web

        run_web(config)
        return 0

    try:
        config.validate()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    notifiers = _build_notifiers(config)

    if args.once:
        conn = db.connect(config.db_path)
        try:
            with HardveraproClient(config) as client:
                run_once(config, conn, client, notifiers)
        finally:
            conn.close()
        return 0

    if args.all:
        _run_all(config, notifiers)
        return 0

    run_forever(config, notifiers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
