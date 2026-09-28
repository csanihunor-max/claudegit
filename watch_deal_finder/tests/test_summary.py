from watchfinder.summary import short_description


def test_bullets_become_a_list_and_the_repeated_title_is_skipped():
    body = ("Szovjet szép Rakéta Mechanikus karóra *Az óra szépen müködik *Eredeti Rakéta szerkezet "
            "*Krómozott tok *Uj szij")
    assert short_description(body, "Szovjet Szép Rakéta Baltika Mechanikus karóra") == \
        "Az óra szépen müködik · Eredeti Rakéta szerkezet · Krómozott tok · Uj szij"


def test_contact_details_and_sign_offs_are_removed():
    body = ("Seiko 5 automata, 1978-as, szépen jár. Hívjon: 06 30 123 4567. Írjon e-mailt: kiss.peter@example.com "
            "vagy nézze meg: https://example.com/ora. Üdv, Péter")
    out = short_description(body, "Seiko 5")
    assert out == "automata, 1978-as, szépen jár."
    for leaked in ("06 30", "123", "@", "example", "Péter"):
        assert leaked not in out


def test_bare_phone_number_sentence_is_dropped():
    assert short_description("Szép állapotú Poljot. +36301234567", "Poljot óra") == "Szép állapotú Poljot."


def test_long_text_is_cut_at_a_word():
    out = short_description("Eredeti számlap és tok, szépen működő szerkezet. " * 20, "x", limit=60)
    assert out.endswith("…") and len(out) <= 61 and " " in out


def test_nothing_useful_gives_none():
    assert short_description(None) is None
    assert short_description("Raketa 2609 karóra", "Raketa 2609 karóra") is None
    assert short_description("Érdeklődni telefonon.", "Raketa") is None
