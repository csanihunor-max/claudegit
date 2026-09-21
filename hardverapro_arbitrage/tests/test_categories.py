from hardverapro_arbitrage.categories import label_for_url


def test_known_category_labeled():
    url = "https://hardverapro.hu/aprok/szoftver_jatek/steam_deck/index.html"
    assert label_for_url(url) == "Steam Deck"


def test_vr_matches_regardless_of_parent_department():
    assert label_for_url("https://hardverapro.hu/aprok/hardver/vr/index.html") == "VR headsets"
    assert label_for_url("https://hardverapro.hu/aprok/szoftver_jatek/vr/index.html") == "VR headsets"


def test_unknown_category_falls_back_to_last_segment():
    url = "https://hardverapro.hu/aprok/hardver/valami_uj_kategoria/index.html"
    assert label_for_url(url) == "Valami Uj Kategoria"


def test_never_raises_on_a_bare_domain():
    # no meaningful path segment to fall back to — just mustn't raise
    result = label_for_url("https://hardverapro.hu/")
    assert isinstance(result, str) and result


def test_pc_parts_categories_labeled():
    assert label_for_url("https://hardverapro.hu/aprok/hardver/alaplap/index.html") == "Motherboards"
    assert label_for_url("https://hardverapro.hu/aprok/hardver/videokartya/index.html") == "Graphics Cards"
    assert label_for_url("https://hardverapro.hu/aprok/hardver/processzor/index.html") == "CPUs"
