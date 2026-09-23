"""Watch Deal Finder command line.

    python main.py run          scheduled loop (every poll_interval_minutes)
    python main.py once         a single pass, then exit (for cron)
    python main.py dashboard    local web dashboard
    python main.py test-notify  send a test push notification
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from watchfinder.config import ConfigError, load_config  # noqa: E402
from watchfinder.http import HttpClient  # noqa: E402
from watchfinder.logging_setup import setup_logging  # noqa: E402
from watchfinder.notify import Alert, LogNotifier, build_notifier  # noqa: E402
from watchfinder.runner import Runner  # noqa: E402
from watchfinder.sources import build_sources  # noqa: E402
from watchfinder.storage import Storage  # noqa: E402

log = logging.getLogger("watchfinder")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Watch Deal Finder")
    parser.add_argument("--config", default=str(HERE / "config.yaml"), help="path to config.yaml")
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="poll on a schedule until stopped")
    sub.add_parser("once", help="run a single pass and exit")
    dash = sub.add_parser("dashboard", help="start the web dashboard")
    dash.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to open it from your phone on the same Wi-Fi")
    dash.add_argument("--port", type=int, default=8080)
    sub.add_parser("test-notify", help="send a test push notification via ntfy")
    args = parser.parse_args(argv)

    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    setup_logging(config.log_file, logging.DEBUG if args.verbose else logging.INFO)

    if args.command == "dashboard":
        from watchfinder.web.app import create_app

        app = create_app(config)
        log.info("dashboard on http://%s:%d/", args.host, args.port)
        app.run(host=args.host, port=args.port, debug=False)
        return 0

    notifier = build_notifier(config)
    if args.command == "test-notify":
        if isinstance(notifier, LogNotifier):
            print("NTFY_TOPIC is not set in .env", file=sys.stderr)
            return 1
        ok = notifier.send(Alert(title="✅ Watch Deal Finder", body="Connected. Deal alerts will arrive here."))
        print("sent" if ok else "failed: see the log for ntfy's error message")
        return 0 if ok else 1

    http = HttpClient(config.user_agent, config.request_delay_seconds)
    storage = Storage(config.database)
    sources = build_sources(config, http)
    if not sources:
        log.error("no sources enabled; check the 'sources' section of config.yaml")
        return 1
    runner = Runner(config, storage, sources, notifier)
    try:
        if args.command == "once":
            summary = runner.run_once()
            return 1 if summary.failures else 0
        runner.run_forever()
    except KeyboardInterrupt:
        log.info("stopped")
    finally:
        storage.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
