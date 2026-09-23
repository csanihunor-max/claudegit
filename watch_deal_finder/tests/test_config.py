import pytest

from watchfinder.config import ConfigError, load_config, parse_config

MINIMAL = {"searches": [{"name": "Raketa", "keywords": "raketa"}]}


def test_defaults():
    cfg = parse_config(MINIMAL)
    assert cfg.poll_interval_minutes == 15
    assert cfg.searches[0].keywords == ("raketa",)
    assert cfg.searches[0].sources == ("jofogas",)
    assert cfg.jofogas.categories == ("karorak-",)
    assert cfg.ebay.enabled is False


def test_poll_interval_minimum():
    with pytest.raises(ConfigError, match="at least 10"):
        parse_config({**MINIMAL, "poll_interval_minutes": 5})
    assert parse_config({**MINIMAL, "poll_interval_minutes": 10}).poll_interval_minutes == 10


@pytest.mark.parametrize("bad", [
    {"searches": []},
    {"searches": [{"name": "x"}]},
    {"searches": [{"name": "x", "keywords": ["a"], "sources": ["vatera"]}]},
    {"searches": [{"name": "x", "keywords": ["a"]}, {"name": "x", "keywords": ["b"]}]},
    {**MINIMAL, "request_delay_seconds": [0, 2]},
])
def test_invalid_configs(bad):
    with pytest.raises(ConfigError):
        parse_config(bad)


def test_secrets_come_from_env_file(tmp_path, monkeypatch):
    for var in ("NTFY_TOPIC", "NTFY_SERVER", "NTFY_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    (tmp_path / "config.yaml").write_text("searches:\n  - name: R\n    keywords: [raketa]\n", encoding="utf-8")
    (tmp_path / ".env").write_text("NTFY_TOPIC=watchdeals-3f9a1c\n", encoding="utf-8")
    cfg = load_config(tmp_path / "config.yaml")
    assert cfg.secrets.ntfy_topic == "watchdeals-3f9a1c"
    assert cfg.secrets.ntfy_server == "https://ntfy.sh"
    assert cfg.secrets.ntfy_token is None
    assert cfg.database == tmp_path / "data/watchfinder.sqlite3"


def test_shipped_config_is_valid():
    from pathlib import Path

    cfg = load_config(Path(__file__).parent.parent / "config.yaml", env_file=None)
    assert len(cfg.searches) >= 5


def test_model_references_validation():
    assert parse_config({**MINIMAL, "model_references": {"Seiko 5 6309": "85"}}).model_references == {"seiko 5 6309": 85.0}
    with pytest.raises(ConfigError):
        parse_config({**MINIMAL, "model_references": {"seiko": "cheap"}})
