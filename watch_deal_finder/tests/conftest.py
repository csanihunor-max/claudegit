from __future__ import annotations

from pathlib import Path

import pytest

from watchfinder.config import AppConfig, SearchConfig, parse_config
from watchfinder.storage import Storage

FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_config(**overrides) -> AppConfig:
    raw = {
        "eur_huf_rate": 400,
        "blacklist": ["okosóra", "smartwatch", "replika", "gyerek", "casio", "fitness"],
        "searches": [
            {"name": "Raketa", "keywords": ["raketa"], "sources": ["jofogas"], "max_price_huf": 30000,
             "reference_price_eur": 60},
            {"name": "Seiko", "keywords": ["seiko"], "sources": ["jofogas"]},
        ],
    }
    raw.update(overrides)
    return parse_config(raw)


@pytest.fixture
def config() -> AppConfig:
    return make_config()


@pytest.fixture
def raketa(config) -> SearchConfig:
    return config.search("Raketa")


@pytest.fixture
def storage():
    s = Storage(":memory:")
    yield s
    s.close()
