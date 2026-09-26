"""Comparables engine: which ads a listing is compared with, and the resulting reference."""

from datetime import datetime, timezone

import pytest

from watchfinder.comps import identify
from watchfinder.market import (MIN_COMPS, GroupStats, MarketIndex, Reference, is_hot, is_parts,
                                resolve_reference, stats_of)

NOW = datetime(2026, 9, 26, tzinfo=timezone.utc)
_n = iter(range(10_000))


def rec(title, price, brand="raketa", details=None, status="active", gone_at=None, source="jofogas"):
    i = next(_n)
    return {"id": f"jofogas-{i}", "source": source, "title": title, "price_huf": price, "status": status,
            "gone_at": gone_at, "first_seen": f"2026-09-{10 + i % 15:02d}T10:00:00+00:00",
            "ident": identify(title, details, [brand])}


def index(records):
    return MarketIndex(records, NOW)


def test_stats():
    s = stats_of([10000, 12000, 15000, 18000, 30000])
    assert (s.median, s.p25, s.p75, s.n) == (15000, 12000, 18000, 5)


def test_same_reference_code_beats_shared_words():
    ix = index([rec("Omega Seamaster 2541.80", p, "omega") for p in (800_000, 850_000, 900_000, 950_000)]
               + [rec("Omega Seamaster Planet Ocean", p, "omega") for p in (1_700_000, 1_800_000, 1_900_000)])
    ref = ix.reference(identify("Omega Seamaster Bond", "ref: 2541.80, quartz", ["omega"]), 400)
    assert ref.stats.median == 875_000 and ref.key == "ref 2541.80"
    assert len(ref.comp_ids) == 4   # Planet Oceans only share "seamaster": not similar enough to count


def test_model_words_found_without_any_vocabulary():
    ix = index([rec("Vostok Anchar karóra", p, "vostok") for p in (150_000, 160_000, 170_000, 180_000)]
               + [rec("Szovjet Vostok mechanikus karóra", p, "vostok") for p in (7_000, 9_000, 11_000, 13_000)])
    ref = ix.reference(identify("Vostok Anchar", None, ["vostok"]), 400)
    assert ref.stats.median == 165_000 and ref.key == "vostok anchar" and not ref.generic


def test_price_classes_never_mix():
    base = [rec("Omega Constellation", p, "omega") for p in (500_000, 520_000, 540_000, 560_000)]
    lady = [rec("Omega Constellation Lady", p, "omega") for p in (300_000, 310_000, 320_000, 330_000)]
    gold = [rec("Omega Constellation 18k", p, "omega") for p in (900_000, 950_000, 1_000_000, 1_050_000)]
    ix = index(base + lady + gold)
    assert ix.reference(identify("Omega Constellation", None, ["omega"]), 400).stats.median == 530_000
    assert ix.reference(identify("Omega Constellation Lady", None, ["omega"]), 400).stats.median == 315_000
    assert ix.reference(identify("Omega Constellation 18k arany", None, ["omega"]), 400).stats.median == 975_000


def test_quartz_and_automatic_are_not_compared_when_both_are_known():
    ix = index([rec("Tissot Seastar automata", p, "tissot") for p in (190_000, 200_000, 210_000, 220_000)]
               + [rec("Tissot Seastar quartz", p, "tissot") for p in (85_000, 88_000, 92_000, 95_000)])
    assert ix.reference(identify("Tissot Seastar kvarc", None, ["tissot"]), 400).stats.median == 90_000


def test_vague_titles_are_only_compared_with_vague_titles():
    ix = index([rec("Szovjet Raketa mechanikus karóra", p) for p in (12_000, 14_000, 15_000, 16_000, 18_000)]
               + [rec("Raketa Copernicus", p) for p in (60_000, 65_000, 70_000, 75_000)])
    vague = ix.reference(identify("Szép szovjet Raketa karóra", None, ["raketa"]), 400)
    assert vague.generic and vague.stats.median == 15_000
    specific = ix.reference(identify("Raketa Kopernikusz szovjet", None, ["raketa"]), 400)
    assert specific is None or specific.stats.median >= 60_000   # never the 15 000 generic median


def test_too_few_comparables_gives_no_reference():
    ix = index([rec("Doxa Sub 300", p, "doxa") for p in range(MIN_COMPS - 1)])
    assert ix.reference(identify("Doxa Sub 300", None, ["doxa"]), 400) is None


def test_the_listing_itself_is_excluded():
    records = [rec("Raketa Big Zero", p) for p in (40_000, 42_000, 44_000, 46_000, 5_000)]
    ix = index(records)
    ref = ix.reference(records[-1]["ident"], 400, exclude_id=records[-1]["id"])
    assert ref.stats.n == 4 and ref.stats.median == 43_000


def test_left_out_of_comparables():
    ix = index([rec("Raketa Big Zero", 40_000) for _ in range(3)] + [
        rec("Raketa Big Zero", 500),                                        # placeholder price
        rec("Raketa Big Zero alkatrésznek", 3_000),                         # parts
        rec("Raketa Big Zero", 30_000, status="gone", gone_at="2026-06-01T00:00:00+00:00"),  # gone long ago
        rec("Raketa Big Zero", 40_000, source="ebay"),                      # only Jófogás prices
    ])
    assert ix.reference(identify("Raketa Big Zero", None, ["raketa"]), 400) is None   # only 3 left


def test_resolution_order():
    ix = index([rec("Raketa Big Zero", p) for p in (40_000, 42_000, 44_000, 46_000)])
    ident = identify("Raketa Big Zero", None, ["raketa"])
    assert resolve_reference(ident, {}, ix, 400).source == "market"
    own = resolve_reference(ident, {"raketa big zero": 90}, ix, 400)
    assert (own.source, own.eur) == ("you", 90)
    assert resolve_reference(identify("Raketa Albatros", None, ["raketa"]), {}, ix, 400, 50).source == "search"
    assert resolve_reference(identify("Raketa Albatros", None, ["raketa"]), {}, ix, 400) is None


def test_hot_rules():
    tight = Reference(100, "market", "k", GroupStats(40000, 35000, 45000, 6))
    loose = Reference(100, "market", "k", GroupStats(40000, 5000, 90000, 6))
    few = Reference(100, "market", "k", GroupStats(40000, 35000, 45000, 4))
    assert is_hot(20000, tight, 400, 0.5)
    assert not is_hot(20001, tight, 400, 0.5)
    assert not is_hot(20000, loose, 400, 0.5)          # comparables all over the place
    assert not is_hot(20000, few, 400, 0.5)            # shown, but too few for 🔥
    assert not is_hot(500, tight, 400, 0.5)            # placeholder price
    assert not is_hot(9000, tight, 400, 0.5, "Raketa alkatrésznek")
    assert not is_hot(1000, None, 400, 0.5)


@pytest.mark.parametrize("title, parts", [
    ("Raketa óra alkatrésznek", True),
    ("Pobeda óra felhúzó tengely 8 db - NOS", True),
    ("Longines Doboz", True),
    ("Longines VHP 22 mm gumiszíj", True),
    ("Seiko 5 hibás, nem jár", True),
    ("Certina DS 1888 - Dobozában, Papírjaival", False),
    ("Vostok Partner orosz automata óra börszíjjal", False),
    ("Raketa TV tokos mechanikus", False),
])
def test_is_parts(title, parts):
    assert is_parts(title) is parts


def test_the_same_ad_posted_twice_counts_once():
    dupes = [rec("Longines Flagship", 325_000, "longines") for _ in range(5)]
    others = [rec("Longines Flagship", p, "longines") for p in (265_000, 345_000, 300_000)]
    ref = index(dupes + others).reference(identify("Longines Flagship", None, ["longines"]), 400)
    assert ref.stats.n == 4


def test_mini_is_a_ladies_size_and_diamonds_matter():
    assert identify("Omega De Ville Mini", None, ["omega"]).lady
    assert "diamond" in identify("Longines Dolce Vita Gyémántos", None, ["longines"]).words
