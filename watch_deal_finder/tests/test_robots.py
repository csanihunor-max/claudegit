from tests.conftest import fixture_text
from watchfinder.config import DEFAULT_USER_AGENT
from watchfinder.robots import RobotsRules
from watchfinder.sources.jofogas import search_url

RULES = RobotsRules(fixture_text("jofogas_robots.txt"))
UA = DEFAULT_USER_AGENT


def test_our_search_urls_are_allowed():
    assert RULES.allowed(search_url("raketa", "karorak-"), UA)
    assert RULES.allowed(search_url("karóra"), UA)
    assert RULES.allowed("https://www.jofogas.hu/budapest/Raketa_karora_162189005.htm", UA)


def test_forbidden_parameters_are_disallowed():
    base = "https://www.jofogas.hu/magyarorszag/karorak-"
    assert not RULES.allowed(base + "?max_price=30000&q=raketa", UA)
    assert not RULES.allowed(base + "?q=raketa&o=2", UA)          # `&o=` pagination
    assert not RULES.allowed(base + "?o=12", UA)                   # deep pagination
    assert RULES.allowed(base + "?o=2", UA)                        # Allow: /*?o=2$ wins (longer match)
    assert not RULES.allowed("https://www.jofogas.hu/aw/something", UA)


def test_ai_training_crawlers_are_blocked_but_we_are_not():
    url = search_url("raketa", "karorak-")
    assert not RULES.allowed(url, "Mozilla/5.0 (compatible; GPTBot/1.0)")
    assert not RULES.allowed(url, "CCBot/2.0")
    assert RULES.allowed(url, UA)


def test_empty_robots_allows_everything():
    assert RobotsRules("").allowed("https://example.com/anything?x=1", UA)
