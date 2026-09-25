import pytest

from watchfinder.comps import comps_query, ebay_sold_url


@pytest.mark.parametrize("title, keywords, expected", [
    ("Szovjet Szép Rakéta Baltika Mechanikus karóra", ["raketa"], "raketa baltica"),
    ("Raketa Kopernikusz új beépítés", ["raketa"], "raketa copernicus"),
    ("Szovjet Szép Rakéta TV Tokos Mechanikus karóra", ["raketa"], "raketa tv"),
    ("Raketa Retro Férfi Karóra Orosz Szovjet Kézi Húzós 16 Köves", ["raketa"], "raketa vintage"),  # no model: vintage cue
    ("Seiko 5 7009-3040", ["seiko"], "seiko 5 7009 3040"),
    ("Seiko Kinetic SKA791P1", ["seiko"], "seiko kinetic ska791p1"),
    ("Seiko Prospex Solar Limited Edition Black Series 200m", ["seiko"], "seiko prospex"),  # 200m is not a reference
    ("Vostok Komandirskie 1975 39mm", ["vostok", "komandirskie"], "vostok komandirskie"),  # year, size dropped
    ("Omega Seamaster De Ville automata", ["omega"], "omega seamaster de ville automatic"),
    ("Longines nagyon ritka aranyóra", ["longines"], "longines gold"),
    ("Omega Seamaster Lady 28mm Pink", ["omega"], "omega seamaster lady"),
    ("Aranyozott Doxa karóra", ["doxa"], "doxa"),                               # gold-PLATED is not gold
    ("Poljot és Rakéta karórák", ["poljot"], "poljot"),
])
def test_comps_query(title, keywords, expected):
    assert comps_query(title, keywords) == expected


def test_at_most_two_reference_numbers():
    assert comps_query("Seiko 5 6309 7040 SKX007 SRPD55 turtle", ["seiko"]) == "seiko 5 turtle 6309 7040"


def test_group_keys_never_widen_past_the_model():
    from watchfinder.comps import model_signature

    sig = model_signature("Raketa Kopernikusz 2628 automata", ["raketa"])
    assert sig.group_keys == ["raketa copernicus 2628 automatic", "raketa copernicus 2628",
                              "raketa copernicus automatic", "raketa copernicus"]
    assert sig.market_ok
    # identified only by a reference number: stays on it
    assert model_signature("Seiko 7009-3040 automata", ["seiko"]).group_keys == [
        "seiko 7009 3040 automatic", "seiko 7009 3040"]
    # vague vintage title: its own vintage group, usable
    vint = model_signature("Szép szovjet Pobeda mechanikus karóra", ["pobeda"])
    assert vint.group_keys == ["pobeda vintage"] and vint.market_ok
    # vague modern title: no automatic market reference at all
    assert not model_signature("Vostok Anchar", ["vostok"]).market_ok


def test_ebay_sold_url():
    assert ebay_sold_url("raketa copernicus") == (
        "https://www.ebay.de/sch/i.html?_nkw=raketa+copernicus&LH_Sold=1&LH_Complete=1&_sacat=31387")
    assert ebay_sold_url("seiko 5", "ebay.com", None) == (
        "https://www.ebay.com/sch/i.html?_nkw=seiko+5&LH_Sold=1&LH_Complete=1")


def test_vintage_and_modern_pieces_of_a_model_are_separate_groups():
    from watchfinder.comps import model_signature

    vintage = model_signature("Vintage Omega Seamaster Cosmic Automatic (1970-es évek)", ["omega"])
    modern = model_signature("Omega Seamaster Diver 300M", ["omega"])
    assert vintage.group_keys[-1] == "omega seamaster cosmic vintage"
    assert modern.group_keys[-1] == "omega seamaster"
    assert "vintage" not in vintage.query            # the eBay search stays on the model
