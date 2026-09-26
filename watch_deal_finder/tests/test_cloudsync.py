"""Cloud mode round trip: pass -> export -> (artifact database) -> dump -> import -> pass."""

import json
from pathlib import Path

from tests.conftest import make_config
from watchfinder.cloudsync import CollectingNotifier, doc_id, export_state, import_state, shard_of
from watchfinder.models import Listing, SearchResult
from watchfinder.runner import Runner
from watchfinder.storage import Storage


def merge(base, patch):
    """The artifact database's update: nested objects merge, `__delete__` removes."""
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and v.get("__delete__") is True:
            out.pop(k, None)
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = merge(out[k], v)
        else:
            out[k] = v
    return out


class FakeArtifactDb:
    """Applies batch manifests like ArtifactData does, and dumps like `list/get` with out_dir."""

    def __init__(self):
        self.docs: dict[tuple[str, str], dict] = {}

    def apply(self, report):
        for batch in report["batches"]:
            for w in json.loads(Path(batch).read_text(encoding="utf-8")):
                key = (w["collection"], w["doc_id"])
                data = json.loads(Path(w["file_path"]).read_text(encoding="utf-8")) if "file_path" in w else None
                if w["op"] == "delete":
                    self.docs.pop(key, None)
                    continue
                if w["op"] == "set":
                    self.docs[key] = data
                else:
                    assert key in self.docs, "update of a missing document"
                    self.docs[key] = merge(self.docs[key], data)

    def listing(self, did):
        return self.docs[("shards", shard_of(did))]["items"].get(did)

    def listing_ids(self):
        return {did for (col, _), body in self.docs.items() if col == "shards" for did in body["items"]}

    def set_user_status(self, did, status):
        # what the page does: db.doc("shards/sNN").update({items: {id: {user_status}}})
        key = ("shards", shard_of(did))
        self.docs[key] = merge(self.docs[key], {"items": {did: {"user_status": status}}})

    def dump(self, directory: Path) -> Path:
        for (collection, did), data in self.docs.items():
            path = directory / collection / f"{did}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            # envelope form, to prove import_state unwraps it
            path.write_text(json.dumps({"id": did, "version": 1, "data": data}), encoding="utf-8")
        return directory


class Source:
    def __init__(self):
        self.listings = []

    def search(self, search):
        return SearchResult(list(self.listings), complete=True)


def L(i, price, title="Raketa 2609"):
    return Listing("jofogas", i, title, price, "HUF", f"https://www.jofogas.hu/x_{i}.htm", location="Pest")


CONFIG = make_config(searches=[{"name": "Raketa", "keywords": ["raketa"], "sources": ["jofogas"],
                                "max_price_huf": 30000, "reference_price_eur": 60}])


def cloud_pass(db: FakeArtifactDb, source: Source, tmp: Path, n: int, day: str | None = None):
    day = day or f"2026-09-2{n}"
    state = db.dump(tmp / f"state{n}")
    storage = Storage(tmp / f"work{n}.sqlite3")
    imported = import_state(storage, state)
    notifier = CollectingNotifier()
    result = Runner(CONFIG, storage, {"jofogas": source}, notifier,
                    now=lambda: f"{day}T10:00:00+00:00").run_once()
    report = export_state(storage, CONFIG, imported, tmp / f"out{n}", f"{day}T10:00:00+00:00",
                          {"kept": result.kept, "failures": result.failures}, notifier.alerts)
    storage.close()
    db.apply(report)
    return report, notifier.alerts


def test_round_trip(tmp_path):
    db, source = FakeArtifactDb(), Source()
    source.listings = [L("1", 20000), L("2", 25000)]

    r1, alerts = cloud_pass(db, source, tmp_path, 1)
    assert alerts == [] and r1["new_listings"] == 2                    # silent first pass, docs created
    doc = db.listing("jofogas-1")
    assert doc["price_huf"] == 20000 and doc["searches"] == ["Raketa"] and doc["history"][0]["huf"] == 20000
    assert db.docs[("state", "seen")]["seeded"] == ["Raketa|jofogas"]
    status = db.docs[("meta", "status")]
    assert status["searches"][0]["reference_price_eur"] == 60 and status["searches"][0]["keywords"] == ["raketa"]
    assert status["ebay_sold_domain"] == "ebay.de"
    assert doc["comps_query"] == "raketa 2609"                      # model words for the "eBay sold" link

    # Nothing changed: only the two bookkeeping docs are written, no shards.
    r2, alerts = cloud_pass(db, source, tmp_path, 2)
    assert alerts == [] and r2["new_listings"] == 0 and r2["changed_listings"] == 0
    assert len(json.loads(Path(r2["batches"][0]).read_text())) == 2

    # The user marks listing 2 as ignored in the dashboard; then a new ad appears,
    # listing 1 drops in price and listing 2 drops too.
    db.set_user_status("jofogas-2", "ignore")
    source.listings = [L("1", 15000), L("2", 20000), L("3", 9000, "Raketa Big Zero")]
    r3, alerts = cloud_pass(db, source, tmp_path, 3)
    titles = {a.title for a in alerts}                                  # not the ignored one:
    assert titles == {"🔥 🆕 New · Raketa · 9 000 Ft", "📉 Price drop · Raketa · 15 000 Ft"}
    assert r3["new_listings"] == 1 and r3["changed_listings"] == 2
    assert db.listing("jofogas-2")["user_status"] == "ignore"                    # update merged, kept
    assert db.listing("jofogas-2")["price_huf"] == 20000
    assert [h["huf"] for h in db.listing("jofogas-1")["history"]] == [20000, 15000]
    alerts_text = Path(r3["alerts_file"]).read_text(encoding="utf-8")
    assert "Raketa Big Zero" in alerts_text
    assert "Sold comps: https://www.ebay.de/sch/i.html?_nkw=raketa+big+zero&LH_Sold=1" in alerts_text

    # Same data again: alerts are remembered across runs, so nothing repeats.
    r4, alerts = cloud_pass(db, source, tmp_path, 4)
    assert alerts == [] and r4["changed_listings"] == 0

    # Listing 3 disappears (complete result set) -> marked gone, kept.
    source.listings = [L("1", 15000), L("2", 20000)]
    cloud_pass(db, source, tmp_path, 5)
    assert db.listing("jofogas-3")["status"] == "gone"


def test_listings_spread_over_16_shard_documents(tmp_path):
    db, source = FakeArtifactDb(), Source()
    # distinct watches (a reference number each), so they aren't each other's comparables
    source.listings = [L(str(i), 1000 + i, f"Raketa {1000 + i}") for i in range(400)]
    report, _ = cloud_pass(db, source, tmp_path, 1)
    writes = [w for b in report["batches"] for w in json.loads(Path(b).read_text())]
    assert len(writes) == 18                                       # 16 shards + seen + status
    assert len(db.listing_ids()) == 400
    biggest = max(Path(w["file_path"]).stat().st_size for w in writes)
    assert biggest < 100_000                                       # far under the 256 KiB document cap
    # one price change -> only that listing's shard is rewritten
    source.listings[7] = L("7", 500, "Raketa 1007")
    report, _ = cloud_pass(db, source, tmp_path, 2)
    writes = [w for b in report["batches"] for w in json.loads(Path(b).read_text())]
    assert [(w["collection"], w["doc_id"], w["op"]) for w in writes if w["collection"] == "shards"] == [
        ("shards", shard_of("jofogas-7"), "update")]


def test_shard_of_is_stable():
    assert shard_of("jofogas-162189005") == shard_of("jofogas-162189005")
    assert len({shard_of(f"jofogas-{i}") for i in range(500)}) == 16


def test_doc_id_is_safe_for_artifact_database():
    assert doc_id("jofogas", "162189005") == "jofogas-162189005"
    assert doc_id("ebay", "v1|226512345678|0") == "ebay-v1_226512345678_0"


def test_old_gone_listings_are_pruned_unless_marked(tmp_path):
    db, source = FakeArtifactDb(), Source()
    source.listings = [L("1", 1000), L("2", 1000), L("3", 1000)]
    cloud_pass(db, source, tmp_path, 1, day="2026-09-01")
    db.set_user_status("jofogas-2", "bought")
    source.listings = []
    cloud_pass(db, source, tmp_path, 2, day="2026-09-02")          # all three gone
    assert db.listing_ids() == {"jofogas-1", "jofogas-2", "jofogas-3"}
    report, _ = cloud_pass(db, source, tmp_path, 3, day="2026-10-15")
    assert report["pruned"] == 2
    assert db.listing_ids() == {"jofogas-2"}                        # bought one kept
    assert "jofogas-1" not in db.docs[("state", "seen")]["last_seen"]


def test_writes_are_pinned_to_the_versions_read(tmp_path):
    from watchfinder.cloudsync import load_versions

    db, source = FakeArtifactDb(), Source()
    source.listings = [L("1", 1000)]
    cloud_pass(db, source, tmp_path, 1)
    state = db.dump(tmp_path / "pinned")
    shard = shard_of("jofogas-1")
    (state / "versions.json").write_text(json.dumps({f"shards/{shard}": 3, "state/seen": 5, "meta/status": 5}))
    assert load_versions(state) == {f"shards/{shard}": 3, "state/seen": 5, "meta/status": 5}
    storage = Storage(tmp_path / "pinned.sqlite3")
    imported = import_state(storage, state)
    source.listings = [L("1", 900)]
    Runner(CONFIG, storage, {"jofogas": source}, CollectingNotifier(),
           now=lambda: "2026-09-25T10:00:00+00:00").run_once()
    report = export_state(storage, CONFIG, imported, tmp_path / "pinned_out", "2026-09-25T10:00:00+00:00", {}, [],
                          load_versions(state))
    writes = {(w["collection"], w["doc_id"]): w for b in report["batches"] for w in json.loads(Path(b).read_text())}
    assert writes[("shards", shard)]["if_version"] == 3 and writes[("shards", shard)]["op"] == "update"
    assert writes[("state", "seen")]["if_version"] == 5 and writes[("meta", "status")]["if_version"] == 5


def test_model_references_are_read_from_the_dump(tmp_path):
    from watchfinder.cloudsync import load_model_references

    refs = tmp_path / "state" / "refs"
    refs.mkdir(parents=True)
    (refs / "raketa_copernicus.json").write_text(json.dumps({"model": "raketa copernicus", "eur": 95}))
    (refs / "broken.json").write_text(json.dumps({"model": "", "eur": 10}))
    (refs / "zero.json").write_text(json.dumps({"model": "seiko 5", "eur": 0}))
    assert load_model_references(tmp_path / "state") == {"raketa copernicus": 95.0}


def test_listings_matching_a_new_blacklist_word_are_removed(tmp_path):
    from dataclasses import replace as dc_replace

    import tests.test_cloudsync as mod

    db, source = FakeArtifactDb(), Source()
    source.listings = [L("1", 1000, "Raketa Snoopy"), L("2", 1000, "Raketa 2609")]
    cloud_pass(db, source, tmp_path, 1)
    db.set_user_status("jofogas-2", "interested")
    old = mod.CONFIG
    mod.CONFIG = dc_replace(old, blacklist=old.blacklist + ("snoopy",))
    try:
        report, _ = cloud_pass(db, source, tmp_path, 2)
    finally:
        mod.CONFIG = old
    assert report["pruned"] == 1 and db.listing_ids() == {"jofogas-2"}


def test_unchanged_data_rewrites_no_listing_documents(tmp_path):
    # many near-identical listings: the comparables chosen must be the same every run
    db, source = FakeArtifactDb(), Source()
    source.listings = [L(str(i), 10000 + (i % 7) * 1000, "Szovjet Raketa karóra") for i in range(60)]
    cloud_pass(db, source, tmp_path, 1)
    report, _ = cloud_pass(db, source, tmp_path, 2)
    assert report["changed_listings"] == 0
    doc = db.listing("jofogas-5")
    assert doc["market"]["generic"] and doc["market"]["n"] >= 4 and len(doc["market"]["comps"]) <= 8


def test_a_full_shard_sheds_its_oldest_gone_listings(tmp_path, monkeypatch):
    import watchfinder.cloudsync as cs

    db, source = FakeArtifactDb(), Source()
    source.listings = [L(str(i), 1000 + i, f"Raketa {1000 + i}") for i in range(200)]
    cloud_pass(db, source, tmp_path, 1, day="2026-09-01")
    source.listings = source.listings[:100]          # the other 100 disappear
    cloud_pass(db, source, tmp_path, 2, day="2026-09-02")
    assert len(db.listing_ids()) == 200
    monkeypatch.setattr(cs, "SHARD_BUDGET_BYTES", 8_000)   # pretend the shards are nearly full
    report, _ = cloud_pass(db, source, tmp_path, 3, day="2026-09-03")
    ids = db.listing_ids()
    assert all(f"jofogas-{i}" in ids for i in range(100))   # active listings are kept
    assert len(ids) < 200 and report["pruned"] > 0
