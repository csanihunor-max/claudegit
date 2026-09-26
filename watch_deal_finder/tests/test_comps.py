import pytest

from watchfinder.comps import Ident, comps_query, ebay_sold_url, identify


@pytest.mark.parametrize("title, details, brand, query", [
    # reference / model codes: the most precise identity, from title or description
    ("Omega Broad Arrow 3551.20.00", None, "omega", "omega 3551.20.00"),
    ("Omega Seamaster Bond Gold", "tömör 18k arany részek quartz ref:2342.20.00", "omega", "omega 2342.20.00 gold"),
    ("Seiko 5 automata karóra orient citizen", "Saját dobozában, Snk355K1 modell. Cal.: 7S26", "seiko",
     "seiko snk355k1"),
    ("Seiko V701-6K00 vintage típusú óra", None, "seiko", "seiko v701-6k00"),
    ("Seiko 5 7009-3040", None, "seiko", "seiko 7009-3040"),
    ("Longines Conquest L3.777.4.58.6", None, "longines", "longines l3.777.4.58.6"),
    # model words, including names that are in no list
    ("Vostok Anchar", None, "vostok", "vostok anchar"),
    ("Longines Golden Classic", None, "longines", "longines golden classic"),
    ("Szovjet Szép Rakéta Baltika Mechanikus karóra", None, "raketa", "raketa baltica"),
    ("Szép Rakéta karóra", "Rakéta Kopernikusz 2628.H szerkezettel", "raketa", "raketa copernicus"),
    ("Omega Seamaster Lady 28mm Pink", None, "omega", "omega seamaster lady"),
    # vague titles
    ("Raketa Retro Férfi Karóra Orosz Szovjet Kézi Húzós 16 Köves", None, "raketa", "raketa vintage"),
    ("Szép állapotban Rakéta karóra", None, "raketa", "raketa"),
])
def test_query(title, details, brand, query):
    assert comps_query(title, [brand], details) == query


def test_phone_numbers_are_never_taken_for_reference_numbers():
    ident = identify("Raketa Big Zero", "Hívjon: 06 30 123 4567 vagy +36301234567", ["raketa"])
    assert ident.refs == () and ident.numbers == ()


def test_gold_colour_in_a_description_is_not_solid_gold():
    assert not identify("Doxa karóra", "arany színű számlap, aranyozott tok", ["doxa"]).gold
    assert identify("Doxa karóra", "18k tömör arany tok", ["doxa"]).gold


def test_keyword_stuffed_brands_are_ignored():
    assert "citizen" not in identify("Seiko 5 automata orient citizen", None, ["seiko"]).words


def test_attributes():
    i = identify("Vintage Omega Seamaster Cosmic Automatic (1970-es évek)", None, ["omega"])
    assert i.vintage and i.movement == "automatic" and "cosmic" in i.words
    assert not identify("Omega Speedmaster Moonwatch 1995", None, ["omega"]).vintage   # 1990s isn't vintage


def test_ident_json_round_trip():
    i = identify("Omega Seamaster Lady 2583.80", "quartz", ["omega"])
    assert Ident.from_json(i.to_json()) == i


def test_ebay_sold_url():
    assert ebay_sold_url("raketa copernicus") == (
        "https://www.ebay.de/sch/i.html?_nkw=raketa+copernicus&LH_Sold=1&LH_Complete=1&_sacat=31387")
    assert ebay_sold_url("seiko 5", "ebay.com", None) == (
        "https://www.ebay.com/sch/i.html?_nkw=seiko+5&LH_Sold=1&LH_Complete=1")
