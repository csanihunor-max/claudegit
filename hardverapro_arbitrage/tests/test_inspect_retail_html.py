from pathlib import Path

from hardverapro_arbitrage.tools.inspect_retail_html import main

FIXTURE = Path(__file__).parent / "fixtures" / "sample_retail_search.html"


def test_prints_parsed_candidates(capsys):
    exit_code = main([str(FIXTURE)])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "2 product candidate(s) parsed" in output
    assert "Steam Deck OLED 512" in output
    assert "280,000 HUF" in output


def test_no_args_prints_usage(capsys):
    exit_code = main([])
    assert exit_code == 2
    assert "inspect_retail_html" in capsys.readouterr().out
