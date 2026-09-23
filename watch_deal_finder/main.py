"""Watch Deal Finder command line.

    python main.py run          scheduled loop (every poll_interval_minutes)
    python main.py once         a single pass, then exit (for cron)
    python main.py dashboard    local web dashboard
    python main.py test-notify  send a test push notification
    python main.py cloud-pass --state DUMP --out DIR   one pass for the artifact/cloud mode
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
    cloud = sub.add_parser("cloud-pass", help="one pass using state dumped from the artifact database")
    cloud.add_argument("--state", required=True, help="directory the artifact database was dumped into")
    cloud.add_argument("--out", required=True, help="directory for changed documents and batch manifests")
    cloud.add_argument("--allow-empty", action="store_true",
                       help="allow an empty dump (only for the very first run; otherwise a failed dump would "
                            "rebuild the database from scratch)")
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

    if args.command == "cloud-pass":
        state_dir = Path(args.state)
        if not args.allow_empty and not any((state_dir / "shards").glob("*.json")):
            print(f"No shard files in {state_dir / 'shards'}: the database dump failed or is empty. "
                  "Refusing to run (pass --allow-empty for a first run).", file=sys.stderr)
            return 2
        return cloud_pass(config, state_dir, Path(args.out))

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


def cloud_pass(config, state_dir: Path, out_dir: Path) -> int:
    import json

    from watchfinder.cloudsync import CollectingNotifier, export_state, import_state
    from watchfinder.storage import utcnow

    out_dir.mkdir(parents=True, exist_ok=True)
    work_db = out_dir / "work.sqlite3"
    for suffix in ("", "-wal", "-shm"):
        Path(f"{work_db}{suffix}").unlink(missing_ok=True)
    storage = Storage(work_db)
    try:
        imported = import_state(storage, state_dir)
        log.info("restored %d listing(s) from %s", len(imported), state_dir)
        http = HttpClient(config.user_agent, config.request_delay_seconds)
        notifier = CollectingNotifier()
        run_at = utcnow()
        result = Runner(config, storage, build_sources(config, http), notifier).run_once()
        summary = {"kept": result.kept, "events": len(result.events), "gone": result.gone,
                   "failures": result.failures}
        report = export_state(storage, config, imported, out_dir, run_at, summary, notifier.alerts)
    finally:
        storage.close()
    print(json.dumps(report, ensure_ascii=False, indent=1))
    return 1 if result.failures else 0


if __name__ == "__main__":
    sys.exit(main())
