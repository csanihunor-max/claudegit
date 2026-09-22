from hardverapro_arbitrage.scraper.normalize import is_bundle_or_generic_key, is_digital_good, normalize_title


def test_strips_sale_filler_words():
    assert normalize_title("Eladó iPhone 12 128GB, garanciával!") == "iphone 12 128gb"


def test_case_and_accent_insensitive():
    a = normalize_title("Eladó Videókártya RTX 3070")
    b = normalize_title("ELADÓ videokartya rtx 3070")
    assert a == b == "videokartya rtx 3070"


def test_whitespace_and_punctuation_insensitive():
    a = normalize_title("iPhone 12   128 GB")
    b = normalize_title("iPhone, 12 - 128 GB!!")
    assert a == b


# Real false negative this guards against: checked against real scraped
# data, only 112 of 4,565 distinct normalized keys ever reached the
# 2-listing minimum needed to compute a reference price -- a title's unit
# being written with or without a separating space ("128GB" vs "128 GB")
# was the single most common reason two listings of the literal same item
# split into different keys and never got compared at all.
def test_unit_spacing_insensitive():
    assert normalize_title("iPhone 12 128GB") == normalize_title("iPhone 12 128 GB")
    assert normalize_title("RTX 3070 8GB") == normalize_title("RTX 3070 8 GB")
    assert normalize_title("SSD 1TB") == normalize_title("SSD 1 TB")


def test_unit_merge_does_not_swallow_unrelated_numbers():
    # "2 ev garancia" (2 year warranty) shouldn't accidentally merge into
    # a unit token just because a number precedes some other word.
    assert normalize_title("iPhone 12 128GB, 2 ev garanciaval") == "iphone 12 128gb 2 ev"


def test_different_items_get_different_keys():
    a = normalize_title("iPhone 12 128GB")
    b = normalize_title("iPhone 13 128GB")
    assert a != b


# Real false positives this whole function exists to catch -- a seller's
# own generically-titled lot of however many games they bundled, matched
# against a completely different seller's differently-sized lot.
def test_generic_platform_games_titles_are_flagged():
    for title in [
        "PS4 játékok",
        "PS5 játékok",
        "PC játékok",
        "Xbox one játékok",
        "Xbox játékok",
        "Nintendo Switch Játékok",
        "PlayStation 4 játékok",
    ]:
        assert is_bundle_or_generic_key(normalize_title(title)) is True, title


def test_explicit_bundle_words_are_flagged():
    assert is_bundle_or_generic_key(normalize_title("PS4 játék csomag")) is True
    assert is_bundle_or_generic_key(normalize_title("Xbox játék gyűjtemény")) is True


def test_specific_game_titles_are_not_flagged():
    assert is_bundle_or_generic_key(normalize_title("God of War Ragnarök PS4")) is False
    assert is_bundle_or_generic_key(normalize_title("Eladó iPhone 12 128GB")) is False


def test_a_console_plus_a_few_named_games_is_not_flagged():
    # specific enough (has "konzol" and a count) to not collapse into the
    # bare "<platform> games" pattern
    assert is_bundle_or_generic_key(normalize_title("Xbox One konzol + 3 játékkal")) is False


# Real problem this catches: widening category coverage pulled digital
# goods (subscription codes, game keys, software licenses) into
# otherwise-physical categories like "Xbox" -- a "Game Pass Ultimate
# előfizetés" listing sitting right next to actual physical consoles.
def test_digital_goods_are_flagged():
    for title in [
        "Game Pass Ultimate előfizetések 3 - 36 hónapig azonnali kézbesítéssel!",
        "Xbox Live Gold előfizetés 12 hónap",
        "PS Plus Essential előfizetés 3 hónap",
        "Steam kulcs - Cyberpunk 2077",
        "Digitális kód - Forza Horizon 5",
        "CD Key Windows 11 Pro",
    ]:
        assert is_digital_good(normalize_title(title)) is True, title


def test_physical_listings_are_not_flagged_as_digital():
    for title in [
        "Xbox One S All Digital 1TB",
        "ASUS ROG Xbox Ally X",
        "PlayStation 4 Pro 1TB",
        "Ryzen 5 7600X",
    ]:
        assert is_digital_good(normalize_title(title)) is False, title
