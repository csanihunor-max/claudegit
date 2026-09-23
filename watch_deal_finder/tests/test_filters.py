from watchfinder.filters import blacklisted, category_allowed, filter_listings, normalize, title_matches
from watchfinder.models import Listing


def test_normalize_strips_accents_and_case():
    assert normalize("Rakéta ŐRÜLT Ár!") == "raketa orult ar"


def test_blacklist_case_and_accent_insensitive():
    bl = ["okosóra", "Casio", "gyerek"]
    assert blacklisted("Xiaomi OKOSORA fekete", bl) == "okosóra"
    assert blacklisted("casio g-shock", bl) == "Casio"
    assert blacklisted("Szép gyerekóra", bl) == "gyerek"   # substring inside a longer word
    assert blacklisted("Raketa 2609 mechanikus", bl) is None


def test_title_matches_keyword_accent_insensitive():
    assert title_matches("Szovjet szép Rakéta 19 köves karóra", ["raketa"])
    assert title_matches("Seiko 5 automata", ["seiko 5"])
    assert not title_matches("Seiko automata", ["seiko 5"])
    assert title_matches("Poljot chronograph", ["vostok", "poljot"])
    assert not title_matches("Homega óra", ["omega"])         # must start a word
    assert not title_matches("Rakéta kályha", ["vostok"])


def test_category_allowed():
    assert category_allowed("Divat, ruházat > Férfi ruházat > Karórák", ["karór"])
    assert not category_allowed("Otthon > Grillek", ["karór", "gyűjtemény"])
    assert category_allowed("Otthon > Grillek", [])      # no filter
    assert category_allowed(None, ["karór"])             # unknown category passes


def _l(title, category=None):
    return Listing("jofogas", title, title, 1000, "HUF", "https://x", category=category)


def test_filter_listings(config, raketa):
    listings = [
        _l("Raketa 2609 mechanikus"),
        _l("Raketa okosóra"),            # blacklisted
        _l("Rakéta porszívó"),           # title matches, fine at this stage
        _l("Vostok Amphibia"),           # keyword not in title
        _l("Replika Rakéta"),            # blacklisted
    ]
    kept = [l.title for l in filter_listings(listings, raketa, config)]
    assert kept == ["Raketa 2609 mechanikus", "Rakéta porszívó"]
