import io
import json

from PIL import Image

from watchfinder.http import HttpError
from watchfinder.models import Listing
from watchfinder.storage import Storage
from watchfinder.thumbs import (THUMB_SIZE, load_thumbs, refresh_thumbs, shrink, thumb_shard_of, thumb_writes)


def jpeg(w=640, h=480, color=(120, 90, 60)):
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, "JPEG", quality=90)
    return buf.getvalue()


class Resp:
    def __init__(self, content, status=200):
        self.content, self.status_code = content, status


class FakeHttp:
    def __init__(self, fail=()):
        self.calls, self.fail = [], set(fail)

    def get(self, url):
        self.calls.append(url)
        if url in self.fail or "*" in self.fail:
            raise HttpError("blocked")
        return Resp(jpeg())


def store(tmp_path, n, gone=()):
    s = Storage(tmp_path / "db.sqlite3")
    for i in range(n):
        s.insert(Listing("jofogas", str(i), f"Raketa {i}", 1000, "HUF", f"https://x/{i}",
                         thumbnail_url=f"https://img.jofogas.hu/thumbs/{i}.jpg"), 1000, f"2026-09-2{i % 9}T10:00:00+00:00")
    for i in gone:
        s.mark_gone("jofogas", str(i), "2026-09-28T10:00:00+00:00")
    s.conn.commit()
    return s


def test_shrink_makes_a_small_webp():
    uri = shrink(jpeg(1200, 900))
    assert uri.startswith("data:image/webp;base64,") and len(uri) < 12_000
    import base64
    with Image.open(io.BytesIO(base64.b64decode(uri.split(",", 1)[1]))) as im:
        assert im.size[0] <= THUMB_SIZE[0] and im.size[1] <= THUMB_SIZE[1]
    assert shrink(b"not an image") is None


def test_refresh_fetches_missing_keeps_existing_and_drops_gone(tmp_path):
    s = store(tmp_path, 4, gone=[3])
    existing = {"jofogas-0": {"src": "https://img.jofogas.hu/thumbs/0.jpg", "img": "data:old", "_shard": "t01"},
                "jofogas-3": {"src": "https://img.jofogas.hu/thumbs/3.jpg", "img": "data:x", "_shard": "t02"}}
    http = FakeHttp()
    current, stats = refresh_thumbs(s, http, existing, {"jofogas-3": {"user_status": None}})
    assert set(current) == {"jofogas-0", "jofogas-1", "jofogas-2"}       # gone one dropped
    assert current["jofogas-0"]["img"] == "data:old"                         # not fetched again
    assert len(http.calls) == 2 and stats["fetched"] == 2 and stats["missing"] == 0
    # ...unless the owner marked it
    current, _ = refresh_thumbs(s, FakeHttp(), existing, {"jofogas-3": {"user_status": "interested"}})
    assert "jofogas-3" in current


def test_refresh_is_capped_and_gives_up_when_the_host_is_blocked(tmp_path):
    s = store(tmp_path, 9)
    current, stats = refresh_thumbs(s, FakeHttp(), {}, {}, per_pass=3)
    assert len(current) == 3 and stats["missing"] == 6
    http = FakeHttp(fail=["*"])
    current, stats = refresh_thumbs(s, http, {}, {})
    assert current == {} and len(http.calls) == 4 and stats["failed"] == 4


def test_writes_set_new_shards_update_known_ones_and_delete_dropped(tmp_path):
    a, b = "jofogas-1", "jofogas-2"
    existing = {b: {"src": "u2", "img": "i2", "_shard": thumb_shard_of(b)}}
    current = {a: {"src": "u1", "img": "i1"}}
    versions = {f"thumbs/{thumb_shard_of(b)}": 7}
    writes = thumb_writes(current, existing, versions, tmp_path)
    by_doc = {w["doc_id"]: w for w in writes}
    wa, wb = by_doc[thumb_shard_of(a)], by_doc[thumb_shard_of(b)]
    if thumb_shard_of(a) != thumb_shard_of(b):
        assert wa["op"] == "set" and "if_version" not in wa
        assert json.loads(open(wa["file_path"]).read()) == {"items": {a: {"src": "u1", "img": "i1"}}}
    assert wb["op"] == "update" and wb["if_version"] == 7
    assert json.loads(open(wb["file_path"]).read())["items"][b] == {"__delete__": True}
    # nothing changed -> nothing written
    assert thumb_writes({b: {"src": "u2", "img": "i2"}}, existing, versions, tmp_path) == []


def test_load_thumbs_reads_the_dump(tmp_path):
    (tmp_path / "thumbs").mkdir()
    (tmp_path / "thumbs" / "t05.json").write_text(json.dumps(
        {"id": "t05", "version": 2, "data": {"items": {"jofogas-9": {"src": "u", "img": "data:y"}}}}))
    assert load_thumbs(tmp_path) == {"jofogas-9": {"src": "u", "img": "data:y", "_shard": "t05"}}
