"""End-to-end pass with a fake Jófogás (real saved pages) and a fake Telegram."""

import copy
import itertools
import json
import re

from tests.conftest import fixture_text, make_config
from watchfinder.config import JofogasConfig
from watchfinder.models import Listing, SearchResult
from watchfinder.runner import Runner
from watchfinder.sources.base import SourceError
from watchfinder.sources.jofogas import JofogasSource, search_url


class Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


class SwitchableHttp:
    def __init__(self):
        self.pages = {}

    def get(self, url, **kw):
        return self.pages[url]


class RecordingNotifier:
    def __init__(self, ok=True):
        self.messages, self.ok = [], ok

    def send(self, text):
        self.messages.append(text)
        return self.ok


_NEXT_DATA = re.compile(r'(<script id="__NEXT_DATA__" type="application/json">)(.*?)(</script>)', re.S)


def next_data(html):
    return json.loads(_NEXT_DATA.search(html).group(2))


def with_next_data(html, data):
    return _NEXT_DATA.sub(lambda m: m.group(1) + json.dumps(data, ensure_ascii=False) + m.group(3), html)


def clock():
    ticks = itertools.count()
    return lambda: f"2026-09-23T10:{next(ticks):02d}:00+00:00"


def test_full_pass_with_real_page(storage):
    config = make_config(searches=[{"name": "Raketa", "keywords": ["raketa"], "sources": ["jofogas"],
                                    "max_price_huf": 30000, "reference_price_eur": 60}])
    http = SwitchableHttp()
    url = search_url("raketa", "karorak-")
    page = fixture_text("jofogas_raketa.html")
    http.pages[url] = Resp(200, page)
    notifier = RecordingNotifier()
    runner = Runner(config, storage, {"jofogas": JofogasSource(http, JofogasConfig())}, notifier, now=clock())

    first = runner.run_once()
    assert first.kept == 36 and first.events == [] and notifier.messages == []   # silent first pass

    # Next pass: one ad drops to 9 000 Ft and a brand-new ad appears on top.
    data = next_data(page)
    ads = data["props"]["pageProps"]["adList"]["ads"]
    target = next(a for a in ads if 20000 < a["price"]["value"] <= 30000)
    target["price"] = {"label": "9 000 Ft", "value": 9000}
    fresh = copy.deepcopy(ads[5])
    fresh.update(list_id=999000111, subject="Raketa Big Zero 2609", url="https://www.jofogas.hu/pest/x_999000111.htm",
                 price={"label": "14 000 Ft", "value": 14000})
    ads.insert(0, fresh)
    http.pages[url] = Resp(200, with_next_data(page, data))

    second = runner.run_once()
    assert sorted(e.kind.value for e in second.events) == ["new", "price_drop"]
    assert second.alerts_sent == 2
    new_msg = next(m for m in notifier.messages if "New listing" in m)
    drop_msg = next(m for m in notifier.messages if "Price drop" in m)
    assert "Raketa Big Zero 2609" in new_msg and "14 000 Ft" in new_msg
    assert drop_msg.startswith("🔥 📉 Price drop · Raketa") and "9 000 Ft" in drop_msg

    third = runner.run_once()   # same data again: no duplicate alerts
    assert third.events == [] and len(notifier.messages) == 2


def test_failed_source_is_reported_and_other_searches_continue(storage):
    class Broken:
        def search(self, s):
            raise SourceError("HTTP 429")

    class Fine:
        def search(self, s):
            return SearchResult([Listing("jofogas", "1", "Seiko 5", 1000, "HUF", "https://x")], complete=True)

    config = make_config(searches=[
        {"name": "Raketa", "keywords": ["raketa"], "sources": ["ebay"]},
        {"name": "Seiko", "keywords": ["seiko"], "sources": ["jofogas"]},
    ])
    runner = Runner(config, storage, {"ebay": Broken(), "jofogas": Fine()}, RecordingNotifier(), now=clock())
    summary = runner.run_once()
    assert summary.failures == ["Raketa/ebay: HTTP 429"]
    assert summary.kept == 1


def test_failed_telegram_send_is_retried_next_pass(storage):
    config = make_config(silent_first_pass=False,
                         searches=[{"name": "Seiko", "keywords": ["seiko"], "sources": ["jofogas"]}])

    class Fine:
        def search(self, s):
            return SearchResult([Listing("jofogas", "1", "Seiko 5", 1000, "HUF", "https://x")], complete=True)

    notifier = RecordingNotifier(ok=False)
    runner = Runner(config, storage, {"jofogas": Fine()}, notifier, now=clock())
    assert runner.run_once().alerts_sent == 0
    notifier.ok = True
    assert runner.run_once().alerts_sent == 1
    assert runner.run_once().alerts_sent == 0
