from pathlib import Path

from hardverapro_arbitrage.tools.inspect_html import main

FIXTURE = Path(__file__).parent / "fixtures" / "sample_search_page.html"


def test_prints_parsed_listings(capsys):
    exit_code = main([str(FIXTURE)])
    assert exit_code == 0
    output = capsys.readouterr().out
    assert "2 listing(s) parsed" in output
    assert "Eladó iPhone 12 128GB" in output
    assert "180,000 HUF" in output


def test_no_args_prints_usage(capsys):
    exit_code = main([])
    assert exit_code == 2
    assert "hardverapro_arbitrage.tools.inspect_html" in capsys.readouterr().out
