from watchfinder.models import Event, EventKind, Listing
from watchfinder.notify import Alert, NtfyNotifier, format_alert, is_hot, should_alert
from watchfinder.tracker import record_results

T0 = "2026-09-23T10:00:00+00:00"
URL = "https://www.jofogas.hu/budapest/Raketa_42.htm"


def listing(price=20000, title="Raketa 2609 <HA>"):
    return Listing("jofogas", "42", title, price, "HUF", URL, location="Budapest",
                   thumbnail_url="https://img.jofogas.hu/bigthumbs/x.jpg")


def test_new_listing_alert(config, raketa):
    alert = format_alert(Event(EventKind.NEW, "Raketa", listing(), 20000), raketa, config)
    assert alert.title == "🆕 New · Raketa · 20 000 Ft"
    assert alert.body.splitlines() == [
        "Raketa 2609 <HA>",                                  # plain text: no escaping needed
        "💰 20 000 Ft (~50 €)",                              # rate 400 in tests
        "📈 Raketa search ref: 60 € → est. margin +10 € (+17%)",
        "📍 Budapest · Jófogás",
    ]
    assert alert.url == URL and alert.image_url.endswith("x.jpg") and alert.hot is False


def test_price_drop_alert_with_fire(config, raketa):
    # reference 60 EUR * 400 = 24 000 Ft; 50% = 12 000 Ft
    event = Event(EventKind.PRICE_DROP, "Raketa", listing(12000), 12000, old_price_huf=16000)
    alert = format_alert(event, raketa, config)
    assert alert.title == "🔥 📉 Price drop · Raketa · 12 000 Ft"
    assert "💰 12 000 Ft (~30 €)" in alert.body
    assert "↘️ was 16 000 Ft (−25%)" in alert.body
    assert alert.hot is True


def test_negative_margin(config, raketa):
    alert = format_alert(Event(EventKind.NEW, "Raketa", listing(26000), 26000), raketa, config)
    assert "est. margin −5 € (−8%)" in alert.body


def test_is_hot_threshold():
    from watchfinder.market import Reference

    ref = Reference(60, "search")                 # 60 EUR * 400 = 24 000 Ft, 50% = 12 000 Ft
    assert is_hot(12000, ref, 400, 0.5)
    assert not is_hot(12001, ref, 400, 0.5)
    assert not is_hot(1000, None, 400, 0.5)       # no reference -> never hot
    assert not is_hot(500, ref, 400, 0.5)         # placeholder prices under 1 000 Ft never count
    assert not is_hot(5000, ref, 400, 0.5, "Raketa alkatrésznek")   # parts never count


def test_should_alert_rules(storage, config, raketa):
    record_results(storage, config, raketa, "jofogas", [listing()], T0)
    ev = Event(EventKind.NEW, "Raketa", listing(), 20000)
    assert should_alert(ev, raketa, config, storage)

    over_budget = Event(EventKind.NEW, "Raketa", listing(35000), 35000)
    assert not should_alert(over_budget, raketa, config, storage)       # max_price_huf is 30 000

    storage.record_alert("jofogas", "42", 20000, "new", T0)
    assert not should_alert(ev, raketa, config, storage)                # same listing + price: no repeat
    cheaper = Event(EventKind.PRICE_DROP, "Raketa", listing(18000), 18000, 20000)
    assert should_alert(cheaper, raketa, config, storage)               # new price: alert

    storage.set_user_status("jofogas", "42", "ignore")
    assert not should_alert(cheaper, raketa, config, storage)           # ignored listings stay quiet


class FakeResp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.headers = {}

    def post(self, url, json, timeout):
        self.calls.append((url, json))
        return self.responses.pop(0)


def test_ntfy_payload_and_send():
    session = FakeSession([FakeResp(200)])
    ntfy = NtfyNotifier("watchdeals-3f9a1c", session=session, sleep=lambda s: None, min_interval=0)
    alert = Alert(title="🔥 📉 Price drop · Raketa · 12 000 Ft", body="Rakéta 2609\n💰 12 000 Ft",
                  url=URL, image_url="https://img/x.jpg", hot=True)
    assert ntfy.send(alert) is True
    url, payload = session.calls[0]
    assert url == "https://ntfy.sh/"
    assert payload == {
        "topic": "watchdeals-3f9a1c",
        "title": "🔥 📉 Price drop · Raketa · 12 000 Ft",   # sent as JSON, so accents/emoji survive
        "message": "Rakéta 2609\n💰 12 000 Ft",
        "priority": 5,
        "tags": ["fire"],
        "click": URL,
        "actions": [{"action": "view", "label": "Open listing", "url": URL}],
        "attach": "https://img/x.jpg",
    }
    assert "Authorization" not in session.headers


def test_ntfy_self_hosted_with_token_and_plain_alert():
    session = FakeSession([FakeResp(200)])
    ntfy = NtfyNotifier("deals", server="https://ntfy.example.hu/", token="tk_abc", session=session,
                        sleep=lambda s: None, min_interval=0)
    assert ntfy.send(Alert(title="t", body="b")) is True
    url, payload = session.calls[0]
    assert url == "https://ntfy.example.hu/"
    assert session.headers["Authorization"] == "Bearer tk_abc"
    assert payload["priority"] == 4 and "click" not in payload and "attach" not in payload


def test_ntfy_retries_on_rate_limit():
    session = FakeSession([FakeResp(429), FakeResp(200)])
    slept = []
    ntfy = NtfyNotifier("deals", session=session, sleep=slept.append, min_interval=0)
    assert ntfy.send(Alert(title="t", body="b")) is True
    assert 10 in slept and len(session.calls) == 2


def test_ntfy_rejection_returns_false():
    session = FakeSession([FakeResp(403, '{"error":"forbidden"}')])
    ntfy = NtfyNotifier("deals", session=session, sleep=lambda s: None, min_interval=0)
    assert ntfy.send(Alert(title="t", body="b")) is False


def test_alert_links_to_ebay_sold_items_for_the_model(config, raketa):
    alert = format_alert(Event(EventKind.NEW, "Raketa", listing(title="Rakéta Kopernikusz 2628"), 20000),
                         raketa, config)
    assert alert.comps_url == (
        "https://www.ebay.de/sch/i.html?_nkw=raketa+copernicus+2628&LH_Sold=1&LH_Complete=1&_sacat=31387")
    session = FakeSession([FakeResp(200)])
    NtfyNotifier("t", session=session, sleep=lambda s: None, min_interval=0).send(alert)
    labels = [a["label"] for a in session.calls[0][1]["actions"]]
    assert labels == ["Open listing", "eBay sold"]


def test_model_reference_beats_the_search_reference(raketa):
    from tests.conftest import make_config

    config = make_config(model_references={"Rakéta Copernicus": 100})   # normalized: "raketa copernicus"
    assert config.model_references == {"raketa copernicus": 100.0}
    copernicus = listing(price=18000, title="Raketa Kopernikusz szép állapot")
    alert = format_alert(Event(EventKind.NEW, "Raketa", copernicus, 18000), raketa, config)
    # 100 EUR * 400 = 40 000 Ft reference; 18 000 Ft is <= 50% of it -> hot
    assert alert.hot and "📈 your ref for 'raketa copernicus': 100 € → est. margin +55 € (+55%)" in alert.body
    # another Raketa model still uses the search's 60 EUR
    other = format_alert(Event(EventKind.NEW, "Raketa", listing(18000, "Raketa 2609"), 18000), raketa, config)
    assert "📈 Raketa search ref: 60 €" in other.body and not other.hot


def test_no_reference_means_no_margin_and_no_fire(config):
    seiko = config.search("Seiko")   # no reference_price_eur in the test config
    alert = format_alert(Event(EventKind.NEW, "Seiko", listing(1000, "Seiko 5"), 1000), seiko, config)
    assert "📈" not in alert.body and not alert.hot


def test_market_reference_in_alert(config):
    from watchfinder.market import GroupStats

    seiko = config.search("Seiko")   # no search reference
    stats = {"seiko 5 automatic": GroupStats(median=70000, p25=55000, p75=85000, n=12)}
    alert = format_alert(Event(EventKind.NEW, "Seiko", listing(30000, "Seiko 5 automata"), 30000), seiko, config,
                         stats)
    assert alert.hot   # 30 000 <= 50% of 70 000, spread 0.43
    assert ("📊 typical Jófogás price for 'seiko 5 automatic': 70 000 Ft (12 ads, middle half 55 000 Ft–85 000 Ft)"
            " → 57% below") in alert.body


def test_parts_are_flagged_and_never_hot(config):
    from watchfinder.market import GroupStats

    stats = {"seiko 5 automatic": GroupStats(70000, 55000, 85000, 12)}
    alert = format_alert(Event(EventKind.NEW, "Seiko", listing(9000, "Seiko 5 automata hibás, alkatrésznek"), 9000),
                         config.search("Seiko"), config, stats)
    assert not alert.hot and "🔧 looks like parts" in alert.body
