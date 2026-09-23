from watchfinder.models import Event, EventKind, Listing
from watchfinder.notify import TelegramNotifier, format_alert, is_hot, should_alert
from watchfinder.tracker import record_results

T0 = "2026-09-23T10:00:00+00:00"


def listing(price=20000, title="Raketa <2609> & co"):
    return Listing("jofogas", "42", title, price, "HUF", "https://www.jofogas.hu/budapest/Raketa_42.htm",
                   location="Budapest")


def test_new_listing_message(config, raketa):
    text = format_alert(Event(EventKind.NEW, "Raketa", listing(), 20000), raketa, config)
    assert text.splitlines()[0] == "🆕 New listing · Raketa"
    assert "<b>Raketa &lt;2609&gt; &amp; co</b>" in text          # HTML-escaped for Telegram
    assert "20 000 Ft (~50 €)" in text                            # rate 400 in tests
    assert "resale ref 60 € → est. margin +10 € (+17%)" in text
    assert "📍 Budapest · Jófogás" in text
    assert '<a href="https://www.jofogas.hu/budapest/Raketa_42.htm">Open listing</a>' in text
    assert "🔥" not in text


def test_price_drop_message_with_fire(config, raketa):
    # reference 60 EUR * 400 = 24 000 Ft; 50% = 12 000 Ft
    event = Event(EventKind.PRICE_DROP, "Raketa", listing(12000), 12000, old_price_huf=16000)
    text = format_alert(event, raketa, config)
    assert text.startswith("🔥 📉 Price drop · Raketa")
    assert "12 000 Ft (~30 €)" in text
    assert "was 16 000 Ft (−25%)" in text


def test_is_hot_threshold(config, raketa):
    assert is_hot(12000, raketa, config)
    assert not is_hot(12001, raketa, config)
    assert not is_hot(1000, config.search("Seiko"), config)   # no reference price -> never hot


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
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body or {}
        self.text = str(self._body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json, timeout):
        self.calls.append((url, json))
        return self.responses.pop(0)


def test_telegram_send_and_retry_after_429():
    session = FakeSession([FakeResp(429, {"parameters": {"retry_after": 3}}), FakeResp(200, {"ok": True})])
    slept = []
    tg = TelegramNotifier("123:ABC", "999", session=session, sleep=slept.append, min_interval=0)
    assert tg.send("hello") is True
    assert 3 in slept
    url, payload = session.calls[-1]
    assert url == "https://api.telegram.org/bot123:ABC/sendMessage"
    assert payload == {"chat_id": "999", "text": "hello", "parse_mode": "HTML", "disable_web_page_preview": False}


def test_telegram_rejection_returns_false():
    session = FakeSession([FakeResp(400, {"ok": False, "description": "Bad Request: chat not found"})])
    tg = TelegramNotifier("t", "c", session=session, sleep=lambda s: None, min_interval=0)
    assert tg.send("x") is False


def test_negative_margin(config, raketa):
    text = format_alert(Event(EventKind.NEW, "Raketa", listing(26000), 26000), raketa, config)
    assert "est. margin −5 € (−8%)" in text
