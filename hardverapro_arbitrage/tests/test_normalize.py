from hardverapro_arbitrage.scraper.normalize import normalize_title


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
