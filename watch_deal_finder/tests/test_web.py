import pytest

from tests.conftest import make_config
from watchfinder.models import Listing
from watchfinder.storage import Storage
from watchfinder.tracker import detect_gone, record_results
from watchfinder.web.app import create_app

T0, T1, T2 = "2026-09-20T10:00:00+00:00", "2026-09-21T10:00:00+00:00", "2026-09-22T10:00:00+00:00"


def L(i, price, title, source="jofogas", currency="HUF"):
    return Listing(source, i, title, price, currency, f"https://example/{i}", location="Budapest",
                   thumbnail_url=f"https://img/{i}.jpg")


@pytest.fixture
def client(tmp_path):
    config = make_config(database=str(tmp_path / "db.sqlite3"), searches=[
        {"name": "Raketa", "keywords": ["raketa"], "sources": ["jofogas", "ebay"], "reference_price_eur": 60},
        {"name": "Seiko", "keywords": ["seiko"], "sources": ["jofogas"]},
    ])
    s = Storage(config.database)
    raketa, seiko = config.search("Raketa"), config.search("Seiko")
    record_results(s, config, raketa, "jofogas", [L("1", 20000, "Raketa A"), L("2", 10000, "Raketa B")], T0)
    record_results(s, config, seiko, "jofogas", [L("3", 50000, "Seiko 5")], T1)
    record_results(s, config, raketa, "jofogas", [L("1", 16000, "Raketa A"), L("2", 10000, "Raketa B"),
                                                  L("4", 30000, "Raketa C")], T2)
    record_results(s, config, raketa, "ebay", [L("e1", 70.0, "Raketa X", "ebay", "EUR"),
                                               L("e2", 90.0, "Raketa Y", "ebay", "EUR")], T2)
    s.close()
    app = create_app(config)
    app.testing = True
    return app.test_client()


def ids(resp):
    assert resp.status_code == 200
    return [i["listing_id"] for i in resp.get_json()["items"]]


def test_index_page_renders(client):
    html = client.get("/").get_data(as_text=True)
    assert "<option>Raketa</option>" in html and "viewport" in html


def test_sorting(client):
    assert ids(client.get("/api/listings?sort=newest&source=jofogas"))[0] == "4"
    assert ids(client.get("/api/listings?sort=cheapest&source=jofogas")) == ["2", "1", "4", "3"]
    # margin: ref 60 EUR * 400 = 24 000 Ft; Seiko (no reference) last
    assert ids(client.get("/api/listings?sort=margin&source=jofogas")) == ["2", "1", "4", "3"]


def test_filters(client):
    assert sorted(ids(client.get("/api/listings?search=Seiko"))) == ["3"]
    assert sorted(ids(client.get("/api/listings?source=ebay"))) == ["e1", "e2"]
    assert sorted(ids(client.get("/api/listings?max_price=20 000&source=jofogas"))) == ["1", "2"]


def test_listing_fields(client):
    items = {i["listing_id"]: i for i in client.get("/api/listings").get_json()["items"]}
    a = items["1"]
    assert a["price_history"] == [20000, 16000]
    assert a["price_eur"] == 40.0 and a["margin_eur"] == 20.0 and a["margin_pct"] == 33
    assert items["2"]["hot"] is True           # 10 000 <= 12 000 (50% of 24 000)
    assert items["3"]["margin_eur"] is None
    assert items["e1"]["price_huf"] == 28000   # 70 EUR * 400


def test_status_buttons_and_views(client):
    post = lambda i, s: client.post(f"/api/listings/jofogas/{i}/status", json={"status": s})
    assert post("1", "interested").status_code == 200
    assert post("2", "ignore").status_code == 200
    assert "2" not in ids(client.get("/api/listings"))          # ignored hidden from candidates
    assert ids(client.get("/api/listings?view=ignore")) == ["2"]
    assert ids(client.get("/api/listings?view=interested")) == ["1"]
    assert post("2", None).status_code == 200                    # clear
    assert "2" in ids(client.get("/api/listings"))
    assert post("nope", "bought").status_code == 404
    assert post("1", "sold").status_code == 400
    assert client.post("/api/listings/jofogas/1/status", data={"status": "bought"}).status_code == 415


def test_bad_params(client):
    assert client.get("/api/listings?sort=weird").status_code == 400
    assert client.get("/api/listings?max_price=abc").status_code == 400


def test_searches_endpoint_has_ebay_median_and_sold_links(client):
    data = {s["name"]: s for s in client.get("/api/searches").get_json()}
    assert data["Raketa"]["ebay_median_eur"] == 80 and data["Raketa"]["ebay_count"] == 2
    assert data["Seiko"]["ebay_median_eur"] is None
    assert data["Seiko"]["comps_url"].startswith("https://www.ebay.de/sch/i.html?_nkw=seiko&LH_Sold=1")
    assert data["Raketa"]["jofogas_gone_count"] == 0


def test_listing_has_sold_comps_link(client):
    items = {i["listing_id"]: i for i in client.get("/api/listings").get_json()["items"]}
    assert items["3"]["comps_url"].startswith("https://www.ebay.de/sch/i.html?_nkw=seiko+5&LH_Sold=1")


def test_recently_gone_listings_give_a_local_sold_signal(tmp_path):
    from datetime import datetime, timedelta, timezone

    config = make_config(database=str(tmp_path / "db.sqlite3"),
                         searches=[{"name": "Raketa", "keywords": ["raketa"], "sources": ["jofogas"]}])
    s = Storage(config.database)
    now = datetime.now(timezone.utc)
    t = lambda days: (now - timedelta(days=days)).isoformat()
    raketa = config.search("Raketa")
    record_results(s, config, raketa, "jofogas", [L("1", 10000, "Raketa A"), L("2", 20000, "Raketa B"),
                                                  L("3", 30000, "Raketa C"), L("4", 99000, "Raketa D")], t(60))
    record_results(s, config, raketa, "jofogas", [L("4", 99000, "Raketa D")], t(50))
    detect_gone(s, config, {}, {("Raketa", "jofogas"): True}, pass_started=t(50), now=t(40))  # 1-3 gone, 40 days ago
    s.conn.execute("UPDATE listings SET gone_at = ? WHERE listing_id IN ('1', '2')", (t(5),))  # two recent
    s.conn.commit()
    s.close()
    app = create_app(config)
    data = app.test_client().get("/api/searches").get_json()[0]
    assert data["jofogas_gone_count"] == 2 and data["jofogas_gone_median_huf"] == 15000
