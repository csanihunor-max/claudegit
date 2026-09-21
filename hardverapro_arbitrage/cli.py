"""Entry point: `python -m hardverapro_arbitrage [--once]`."""
from __future__ import annotations

import argparse
import logging
import sys

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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Hardverapro arbitrage scraper")
    parser.add_argument("--once", action="store_true", help="run a single scrape cycle and exit")
    parser.add_argument("--verbose", action="store_true", help="enable debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    config = Config()
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

    run_forever(config, notifiers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
