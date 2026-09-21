from hardverapro_arbitrage.geo import describe_location


def test_none_for_missing_location():
    assert describe_location(None) is None
    assert describe_location("") is None


def test_bare_budapest_is_zero_distance():
    result = describe_location("Budapest")
    assert result == {"distance_km": 0.0, "region": "Budapest"}


def test_kerulet_implies_budapest_regardless_of_number():
    # both forms seen in real scraped listings
    for text in ["VIII. kerület", "Budapest, XIV. kerület"]:
        result = describe_location(text)
        assert result is not None
        assert result["region"] == "Budapest"
        assert result["distance_km"] == 0.0


def test_known_pest_county_town():
    result = describe_location("Gödöllő")
    assert result is not None
    assert result["region"] == "Pest county"
    assert 0 < result["distance_km"] < 60


def test_known_other_county_city():
    result = describe_location("Miskolc")
    assert result is not None
    assert result["region"] == "Other"
    assert result["distance_km"] > 100


def test_unknown_location_returns_none():
    assert describe_location("Nowheresville") is None


def test_multi_location_string_picks_closest_match():
    # a seller listing several pickup points -- the closest one to
    # Budapest is what actually determines pickup feasibility
    result = describe_location("Miskolc, Gödöllő")
    assert result is not None
    assert result["region"] == "Pest county"


def test_accent_and_case_insensitive():
    result = describe_location("BUDAORS")
    assert result is not None
    assert result["region"] == "Pest county"
