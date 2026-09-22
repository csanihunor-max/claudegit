from hardverapro_arbitrage.categories import _LABELS, DEFAULT_SEARCH_URLS, is_liquid_category, label_for_url


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


def test_newer_categories_labeled():
    assert label_for_url("https://hardverapro.hu/aprok/hardver/monitor/index.html") == "Monitors"
    assert label_for_url("https://hardverapro.hu/aprok/notebook/pc/index.html") == "Laptops"
    assert label_for_url("https://hardverapro.hu/aprok/notebook/apple/index.html") == "MacBooks"
    assert label_for_url("https://hardverapro.hu/aprok/hazimozi_hifi/tv_projektor/index.html") == "TVs / Projectors"
    assert (
        label_for_url("https://hardverapro.hu/aprok/hazimozi_hifi/fejhallgato_fulhallgato/index.html")
        == "Headphones"
    )
    assert label_for_url("https://hardverapro.hu/aprok/mobil/okosora_okosgyuru/index.html") == "Smartwatches"


def test_liquid_pc_component_categories_are_flagged():
    for slug in ("alaplap", "videokartya", "processzor", "memoria", "merevlemez_ssd"):
        url = f"https://hardverapro.hu/aprok/hardver/{slug}/index.html"
        assert is_liquid_category(url) is True, url


def test_non_liquid_categories_are_not_flagged():
    for url in (
        "https://hardverapro.hu/aprok/hardver/monitor/index.html",
        "https://hardverapro.hu/aprok/mobil/mobil/index.html",
        "https://hardverapro.hu/aprok/notebook/pc/index.html",
    ):
        assert is_liquid_category(url) is False, url


def test_every_default_url_has_a_specific_label_not_a_fallback():
    # every URL this bot tracks by default should match one of the known
    # slugs, never fall through to the generic last-path-segment label --
    # otherwise the dashboard/notifications show a raw slug instead of a
    # readable name.
    for url in DEFAULT_SEARCH_URLS:
        assert any(slug in url for slug in _LABELS), f"{url} has no specific label"
