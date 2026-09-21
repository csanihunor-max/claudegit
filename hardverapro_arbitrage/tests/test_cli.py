from hardverapro_arbitrage import cli


def test_all_flag_dispatches_to_run_all(monkeypatch):
    monkeypatch.setenv("HA_SEARCH_URLS", "https://example.com/search")
    calls = []
    monkeypatch.setattr(cli, "_run_all", lambda config, notifiers: calls.append((config, notifiers)))

    exit_code = cli.main(["--all"])

    assert exit_code == 0
    assert len(calls) == 1


def test_once_and_all_are_mutually_exclusive():
    try:
        cli.main(["--once", "--all"])
        assert False, "expected SystemExit"
    except SystemExit as exc:
        assert exc.code == 2


def test_missing_search_urls_reports_config_error(monkeypatch, capsys):
    monkeypatch.delenv("HA_SEARCH_URLS", raising=False)
    exit_code = cli.main(["--once"])
    assert exit_code == 2
    assert "Configuration error" in capsys.readouterr().err
