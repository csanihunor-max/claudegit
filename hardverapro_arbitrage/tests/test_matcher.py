from hardverapro_arbitrage.retail.matcher import best_match, score_match


def test_high_score_for_same_product_different_vocabulary():
    listing = "Steam Deck OLED 512GB BONTATLAN"
    candidate = "Valve Steam Deck OLED 512 GB kézikonzol"
    assert score_match(listing, candidate) > 0.8


def test_spec_mismatch_heavily_penalized_despite_word_overlap():
    # same product line, different capacity -- must not score high just
    # because "steam", "deck", "oled" all match
    listing = "Steam Deck OLED 512GB"
    candidate = "Valve Steam Deck OLED 256 GB kézikonzol"
    assert score_match(listing, candidate) < 0.4


def test_unrelated_product_scores_zero():
    listing = "Steam Deck OLED 512GB"
    candidate = "Samsung Galaxy S23 256GB"
    assert score_match(listing, candidate) == 0.0


def test_score_is_bounded_at_one():
    listing = "iPhone 12 128GB"
    candidate = "Apple iPhone 12 128GB kártyafüggetlen okostelefon Apple iPhone 12 128GB"
    assert score_match(listing, candidate) <= 1.0


def test_best_match_picks_highest_scoring_candidate():
    listing = "Steam Deck OLED 512GB"
    candidates = [
        ("Valve Steam Deck OLED 256 GB kézikonzol", 200_000.0, "HUF", "https://x/256"),
        ("Valve Steam Deck OLED 512 GB kézikonzol", 280_000.0, "HUF", "https://x/512"),
        ("Nintendo Switch OLED", 120_000.0, "HUF", "https://x/switch"),
    ]
    result = best_match(listing, candidates)
    assert result is not None
    assert result.price == 280_000.0
    assert result.match_confidence > 0.8


def test_best_match_returns_none_for_no_candidates():
    assert best_match("Steam Deck OLED 512GB", []) is None
