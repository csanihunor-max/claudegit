import logging

import pytest

import hardverapro_arbitrage.scheduler as scheduler_module
from hardverapro_arbitrage.config import Config
from hardverapro_arbitrage.notify.console import ConsoleNotifier


class _StopLoop(Exception):
    """Raised from the patched time.sleep to escape run_forever's `while True`
    after exactly one cycle, so the test can inspect what that cycle did."""


def test_warns_when_a_cycle_runs_longer_than_the_poll_interval(tmp_path, monkeypatch, caplog):
    # Real scenario this guards against: 53 tracked categories can take
    # several minutes per cycle now -- if HA_POLL_INTERVAL_SECONDS is set
    # shorter than that, the loop still works (no crash, no negative
    # sleep), but silently runs back-to-back with zero rest. That's worth
    # a log line, not silence.
    times = iter([0.0, 500.0])
    monkeypatch.setattr(scheduler_module.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(scheduler_module, "run_once", lambda *a, **kw: [])

    def _stop(_seconds):
        raise _StopLoop()

    monkeypatch.setattr(scheduler_module.time, "sleep", _stop)

    config = Config(
        search_urls=["https://example.com"], poll_interval_seconds=60, db_path=str(tmp_path / "t.sqlite3")
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(_StopLoop):
            scheduler_module.run_forever(config, [ConsoleNotifier()])

    assert "longer than HA_POLL_INTERVAL_SECONDS" in caplog.text


def test_no_warning_when_cycle_fits_within_the_poll_interval(tmp_path, monkeypatch, caplog):
    times = iter([0.0, 5.0])
    monkeypatch.setattr(scheduler_module.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(scheduler_module, "run_once", lambda *a, **kw: [])

    def _stop(_seconds):
        raise _StopLoop()

    monkeypatch.setattr(scheduler_module.time, "sleep", _stop)

    config = Config(
        search_urls=["https://example.com"], poll_interval_seconds=3600, db_path=str(tmp_path / "t.sqlite3")
    )
    with caplog.at_level(logging.WARNING):
        with pytest.raises(_StopLoop):
            scheduler_module.run_forever(config, [ConsoleNotifier()])

    assert "longer than HA_POLL_INTERVAL_SECONDS" not in caplog.text
