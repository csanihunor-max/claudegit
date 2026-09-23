import pytest

from watchfinder.comps import comps_query, ebay_sold_url


@pytest.mark.parametrize("title, keywords, expected", [
    ("Szovjet Szép Rakéta Baltika Mechanikus karóra", ["raketa"], "raketa baltica"),
    ("Raketa Kopernikusz új beépítés", ["raketa"], "raketa copernicus"),
    ("Szovjet Szép Rakéta TV Tokos Mechanikus karóra", ["raketa"], "raketa tv"),
    ("Raketa Retro Férfi Karóra Orosz Szovjet Kézi Húzós 16 Köves", ["raketa"], "raketa"),  # "16" jewels dropped
    ("Seiko 5 7009-3040", ["seiko"], "seiko 5 7009 3040"),
    ("Seiko Kinetic SKA791P1", ["seiko"], "seiko kinetic ska791p1"),
    ("Seiko Prospex Solar Limited Edition Black Series 200m", ["seiko"], "seiko"),      # 200m is not a model
    ("Vostok Komandirskie 1975 39mm", ["vostok", "komandirskie"], "vostok komandirskie"),  # year, size dropped
    ("Omega Seamaster De Ville automata", ["omega"], "omega seamaster de ville"),
    ("Poljot és Rakéta karórák", ["poljot"], "poljot"),
])
def test_comps_query(title, keywords, expected):
    assert comps_query(title, keywords) == expected


def test_query_is_capped_at_four_terms():
    assert len(comps_query("Seiko 5 6309 7040 SKX007 SRPD55 turtle", ["seiko"]).split()) == 4


def test_ebay_sold_url():
    assert ebay_sold_url("raketa copernicus") == (
        "https://www.ebay.de/sch/i.html?_nkw=raketa+copernicus&LH_Sold=1&LH_Complete=1&_sacat=31387")
    assert ebay_sold_url("seiko 5", "ebay.com", None) == (
        "https://www.ebay.com/sch/i.html?_nkw=seiko+5&LH_Sold=1&LH_Complete=1")
