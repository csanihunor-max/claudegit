from hardverapro_arbitrage.scraper.normalize import is_bundle_or_generic_key, normalize_title


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
