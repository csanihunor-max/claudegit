"""Change detection: new listings, price drops, gone listings, duplicate-alert suppression."""

from watchfinder.models import EventKind, Listing
from watchfinder.tracker import detect_gone, record_results
from tests.conftest import make_config

T0, T1, T2 = "2026-09-23T10:00:00+00:00", "2026-09-23T10:15:00+00:00", "2026-09-23T10:30:00+00:00"
LATER = "2026-09-24T10:00:00+00:00"


def L(listing_id: str, price: float | None = 20000, title: str = "Raketa 2609") -> Listing:
    return Listing("jofogas", listing_id, title, price, "HUF", f"https://www.jofogas.hu/x_{listing_id}.htm")


def test_first_pass_is_silent_then_new_listings_alert(storage, config, raketa):
    assert record_results(storage, config, raketa, "jofogas", [L("1"), L("2")], T0) == []
    events = record_results(storage, config, raketa, "jofogas", [L("1"), L("2"), L("3")], T1)
    assert [(e.kind, e.listing.listing_id) for e in events] == [(EventKind.NEW, "3")]
    row = storage.get("jofogas", "3")
    assert row["first_seen"] == T1 and row["status"] == "active"


def test_first_pass_alerts_when_silent_first_pass_off(storage, raketa):
    config = make_config(silent_first_pass=False)
    events = record_results(storage, config, raketa, "jofogas", [L("1")], T0)
    assert [e.kind for e in events] == [EventKind.NEW]


def test_price_drop_detected_and_history_kept(storage, config, raketa):
    record_results(storage, config, raketa, "jofogas", [L("1", 20000)], T0)
    assert record_results(storage, config, raketa, "jofogas", [L("1", 20000)], T1) == []  # unchanged
    events = record_results(storage, config, raketa, "jofogas", [L("1", 15000)], T2)
    assert len(events) == 1
    drop = events[0]
    assert drop.kind is EventKind.PRICE_DROP and drop.price_huf == 15000 and drop.old_price_huf == 20000
    assert [h["price_huf"] for h in storage.price_history("jofogas", "1")] == [20000, 15000]
    assert storage.get("jofogas", "1")["last_seen"] == T2


def test_price_increase_is_recorded_but_not_an_event(storage, config, raketa):
    record_results(storage, config, raketa, "jofogas", [L("1", 20000)], T0)
    assert record_results(storage, config, raketa, "jofogas", [L("1", 25000)], T1) == []
    assert [h["price_huf"] for h in storage.price_history("jofogas", "1")] == [20000, 25000]


def test_complete_result_marks_missing_listings_gone(storage, config, raketa):
    record_results(storage, config, raketa, "jofogas", [L("1"), L("2")], T0)
    record_results(storage, config, raketa, "jofogas", [L("1")], T1)
    gone = detect_gone(storage, config, {}, {("Raketa", "jofogas"): True}, pass_started=T1, now=T1)
    assert gone == [("jofogas", "2")]
    row = storage.get("jofogas", "2")
    assert row["status"] == "gone" and row["gone_at"] == T1   # kept, not deleted
    assert storage.get("jofogas", "1")["status"] == "active"


def test_failed_search_never_marks_anything_gone(storage, config, raketa):
    record_results(storage, config, raketa, "jofogas", [L("1")], T0)
    assert detect_gone(storage, config, {}, {}, pass_started=T1, now=T1) == []
    assert storage.get("jofogas", "1")["status"] == "active"


def test_listing_seen_by_another_search_this_pass_is_not_gone(storage, config, raketa):
    seiko = config.search("Seiko")
    item = L("1", title="Raketa Seiko")
    record_results(storage, config, raketa, "jofogas", [item], T0)
    record_results(storage, config, seiko, "jofogas", [item], T1)   # seen this pass via Seiko
    record_results(storage, config, raketa, "jofogas", [], T1)
    gone = detect_gone(storage, config, {}, {("Raketa", "jofogas"): True, ("Seiko", "jofogas"): True},
                       pass_started=T1, now=T1)
    assert gone == []


class CheckingSource:
    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.checked = []

    def is_gone(self, listing):
        self.checked.append(listing.listing_id)
        return self.verdicts[listing.listing_id]


def test_partial_results_verify_old_unseen_listings_directly(storage, config, raketa):
    record_results(storage, config, raketa, "jofogas", [L("1"), L("2"), L("3")], T0)
    source = CheckingSource({"1": True, "2": False, "3": None})
    outcomes = {("Raketa", "jofogas"): False}
    # Unseen for only 15 minutes: could just have dropped off page 1, so nothing is checked yet.
    assert detect_gone(storage, config, {"jofogas": source}, outcomes, pass_started=T1, now=T1) == []
    assert source.checked == []
    # A day later the site is asked directly.
    gone = detect_gone(storage, config, {"jofogas": source}, outcomes, pass_started=LATER, now=LATER)
    assert gone == [("jofogas", "1")]
    assert sorted(source.checked) == ["1", "2", "3"]
    assert storage.get("jofogas", "2")["last_checked"] == LATER   # alive: not re-checked for a while
    assert storage.get("jofogas", "3")["status"] == "active"


def test_gone_checks_are_capped_per_pass(storage, raketa):
    config = make_config(max_gone_checks_per_pass=2)
    record_results(storage, config, raketa, "jofogas", [L(str(i)) for i in range(5)], T0)
    source = CheckingSource({str(i): False for i in range(5)})
    detect_gone(storage, config, {"jofogas": source}, {("Raketa", "jofogas"): False}, LATER, LATER)
    assert len(source.checked) == 2


def test_gone_listing_that_reappears_is_active_again(storage, config, raketa):
    record_results(storage, config, raketa, "jofogas", [L("1")], T0)
    detect_gone(storage, config, {}, {("Raketa", "jofogas"): True}, pass_started=T1, now=T1)
    assert storage.get("jofogas", "1")["status"] == "gone"
    events = record_results(storage, config, raketa, "jofogas", [L("1")], T2)
    assert events == []   # not "new" again
    assert storage.get("jofogas", "1")["status"] == "active"
