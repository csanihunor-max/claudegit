from datetime import datetime, timezone

import pytest

from watchfinder.market import (GroupStats, MIN_SAMPLES, Reference, is_hot, is_parts, market_stats,
                                resolve_reference)

NOW = datetime(2026, 9, 25, tzinfo=timezone.utc)


def rec(price, keys=("raketa vintage",), title="Szovjet Raketa", status="active", gone_at=None, market_ok=True,
        source="jofogas"):
    return {"source": source, "title": title, "price_huf": price, "status": status, "gone_at": gone_at,
            "group_keys": list(keys), "market_ok": market_ok}


def test_median_and_quartiles():
    stats = market_stats([rec(p) for p in (10000, 12000, 15000, 18000, 30000)], NOW)
    s = stats["raketa vintage"]
    assert (s.median, s.p25, s.p75, s.n) == (15000, 12000, 18000, 5)
    assert round(s.spread, 2) == 0.4


def test_what_is_left_out():
    stats = market_stats([
        rec(15000), rec(15000),
        rec(500),                                          # placeholder price
        rec(3000, title="Raketa alkatrésznek"),            # parts
        rec(4000, title="Raketa felhúzó tengely 8 db"),    # parts / lot
        rec(20000, status="gone", gone_at="2026-06-01T00:00:00+00:00"),   # gone too long ago
        rec(16000, status="gone", gone_at="2026-09-20T00:00:00+00:00"),   # gone recently: counts
        rec(99000, market_ok=False),                       # vague modern title
        rec(15000, source="ebay"),                         # only Jófogás prices
    ], NOW)
    assert stats["raketa vintage"].n == 3


def test_listing_contributes_to_every_group_key():
    stats = market_stats([rec(10000, keys=("raketa copernicus 2628", "raketa copernicus"))], NOW)
    assert set(stats) == {"raketa copernicus 2628", "raketa copernicus"}


def test_resolution_order():
    stats = {"raketa copernicus": GroupStats(30000, 25000, 40000, 8),
             "raketa copernicus 2628": GroupStats(35000, 30000, 38000, 2)}   # too few
    keys = ["raketa copernicus 2628", "raketa copernicus"]
    market = resolve_reference(keys, {}, stats, 400)
    assert market.source == "market" and market.key == "raketa copernicus" and market.eur == 75
    own = resolve_reference(keys, {"raketa copernicus": 90}, stats, 400)
    assert (own.source, own.eur) == ("you", 90)
    assert resolve_reference(["x"], {}, stats, 400, search_ref_eur=50).source == "search"
    assert resolve_reference(["x"], {}, stats, 400) is None
    # a vague modern title never gets a market reference, even if its group has data
    assert resolve_reference(keys, {}, stats, 400, market_ok=False) is None


def test_no_fire_when_the_group_is_all_over_the_place():
    tight = Reference(75, "market", "k", GroupStats(30000, 25000, 40000, 8))     # spread 0.5
    loose = Reference(75, "market", "k", GroupStats(30000, 5000, 90000, 8))      # spread 2.8
    few = Reference(75, "market", "k", GroupStats(30000, 25000, 40000, 6))       # shown, but too few for 🔥
    assert is_hot(14000, tight, 400, 0.5)
    assert not is_hot(14000, loose, 400, 0.5)
    assert not is_hot(14000, few, 400, 0.5)


@pytest.mark.parametrize("title, parts", [
    ("Raketa óra alkatrésznek", True),
    ("Pobeda óra felhúzó tengely 8 db - NOS", True),
    ("Longines Doboz", True),
    ("Longines VHP 22 mm gumiszíj", True),
    ("Seiko 5 hibás, nem jár", True),
    ("Certina DS 1888 - Dobozában, Papírjaival", False),     # "in its box" is a plus, not a box
    ("Vostok Partner orosz automata óra börszíjjal", False),  # "with leather strap"
    ("Raketa TV tokos mechanikus", False),
])
def test_is_parts(title, parts):
    assert is_parts(title) is parts


def test_min_samples_is_sane():
    assert MIN_SAMPLES >= 5
