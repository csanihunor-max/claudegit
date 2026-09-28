"""Listing photos for the cloud dashboard.

The artifact page may not load images from other sites, so the cloud pass
downloads each listing's small thumbnail, shrinks it to a few kilobytes and
stores it in the artifact database as a data: URI:

    thumbs/t00..t47     {"items": {doc_id: {"src": thumbnail_url, "img": "data:image/webp;base64,..."}}}

Only listings still worth looking at keep a photo (active ones, and gone ones
marked interested/bought). A pass fetches at most `per_pass` new photos, newest
listings first, so the first backfill spreads over a few runs.
"""

from __future__ import annotations

import base64
import io
import json
import logging
from pathlib import Path
from typing import Any

from .http import HttpClient, HttpError
from .storage import Storage

log = logging.getLogger(__name__)

THUMBS = "thumbs"
THUMB_SHARD_COUNT = 48            # ~12-17 photos of ~8 KB per 256 KiB document
THUMB_SIZE = (220, 165)          # fits a 4:3 card photo; ~4-7 KB as WebP
THUMB_QUALITY = 55
RAW_MAX_BYTES = 9_000            # without Pillow, keep the original only if it is this small
PER_PASS = 100
GIVE_UP_AFTER_FAILURES = 4       # consecutive failures: host down or blocked, try next run
KEEP_STATUSES = ("interested", "bought")


def thumb_shard_of(did: str) -> str:
    h = 2166136261  # FNV-1a, as cloudsync.shard_of
    for byte in did.encode("utf-8"):
        h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
    return f"t{h % THUMB_SHARD_COUNT:02d}"


def load_thumbs(state_dir: Path) -> dict[str, dict[str, Any]]:
    """Photos from the dump: {doc_id: {"src", "img", "_shard"}}."""
    from .cloudsync import load_docs

    out: dict[str, dict[str, Any]] = {}
    for shard, body in load_docs(state_dir / THUMBS).items():
        for did, item in (body.get("items") or {}).items():
            if isinstance(item, dict) and isinstance(item.get("img"), str):
                out[did] = {"src": item.get("src"), "img": item["img"], "_shard": shard}
    return out


def shrink(data: bytes) -> str | None:
    """A small data: URI for an image, or None if it can't be made small enough."""
    try:
        from PIL import Image
    except ImportError:
        if len(data) <= RAW_MAX_BYTES and data[:3] == b"\xff\xd8\xff":
            return "data:image/jpeg;base64," + base64.b64encode(data).decode()
        return None
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = im.convert("RGB")
            im.thumbnail(THUMB_SIZE)
            buf = io.BytesIO()
            im.save(buf, "WEBP", quality=THUMB_QUALITY, method=6)
    except Exception as exc:  # corrupt or unsupported image
        log.debug("could not shrink image: %s", exc)
        return None
    return "data:image/webp;base64," + base64.b64encode(buf.getvalue()).decode()


def wanted_listings(storage: Storage, imported: dict[str, dict[str, Any]]) -> dict[str, str]:
    """doc_id -> thumbnail URL for every listing that should show a photo, newest first."""
    from .cloudsync import doc_id

    out: dict[str, str] = {}
    rows = storage.conn.execute(
        "SELECT source, listing_id, thumbnail_url, status FROM listings "
        "WHERE thumbnail_url IS NOT NULL ORDER BY first_seen DESC, listing_id"
    ).fetchall()
    for r in rows:
        did = doc_id(r[0], r[1])
        if r[3] == "gone" and (imported.get(did) or {}).get("user_status") not in KEEP_STATUSES:
            continue
        out[did] = r[2]
    return out


def refresh_thumbs(
    storage: Storage,
    http: HttpClient,
    existing: dict[str, dict[str, Any]],
    imported: dict[str, dict[str, Any]],
    per_pass: int = PER_PASS,
) -> tuple[dict[str, dict[str, Any]], dict[str, int]]:
    """Photos after this pass: kept, newly fetched, and dropped for listings no longer shown."""
    wanted = wanted_listings(storage, imported)
    current = {did: t for did, t in existing.items() if did in wanted and t.get("src") == wanted[did]}
    missing = [did for did in wanted if did not in current]
    stats = {"fetched": 0, "failed": 0, "missing": len(missing)}
    failures_in_row = 0
    for did in missing[:per_pass]:
        try:
            resp = http.get(wanted[did])
            img = shrink(resp.content) if resp.status_code == 200 else None
        except HttpError as exc:
            log.warning("photo %s: %s", did, exc)
            img = None
        if img is None:
            stats["failed"] += 1
            failures_in_row += 1
            if failures_in_row >= GIVE_UP_AFTER_FAILURES:
                log.warning("photos: %d failures in a row, trying again next run", failures_in_row)
                break
            continue
        failures_in_row = 0
        current[did] = {"src": wanted[did], "img": img}
        stats["fetched"] += 1
    stats["missing"] = len(wanted) - len(current)
    stats["stored"] = len(current)
    return current, stats


def thumb_writes(
    current: dict[str, dict[str, Any]],
    existing: dict[str, dict[str, Any]],
    versions: dict[str, int],
    docs_dir: Path,
) -> list[dict[str, Any]]:
    """Write entries for the photo shards that changed (see cloudsync.export_state)."""
    by_shard: dict[str, dict[str, Any]] = {}
    dirty: set[str] = set()
    for did, t in current.items():
        shard = thumb_shard_of(did)
        by_shard.setdefault(shard, {})[did] = {"src": t["src"], "img": t["img"]}
        before = existing.get(did)
        if before is None or before.get("src") != t["src"] or before.get("img") != t["img"]:
            dirty.add(shard)
    for did, t in existing.items():
        if did not in current:
            by_shard.setdefault(t["_shard"], {})[did] = {"__delete__": True}
            dirty.add(t["_shard"])
    stored_shards = {t["_shard"] for t in existing.values()}
    writes = []
    for shard in sorted(dirty):
        path = docs_dir / f"{THUMBS}__{shard}.json"
        key = f"{THUMBS}/{shard}"
        items = by_shard[shard]
        if key not in versions and shard not in stored_shards:
            items = {d: t for d, t in items.items() if "__delete__" not in t}
            op = "set"
        else:
            op = "update"
        path.write_text(json.dumps({"items": items}, ensure_ascii=False), encoding="utf-8")
        write: dict[str, Any] = {"op": op, "collection": THUMBS, "doc_id": shard, "file_path": str(path)}
        if key in versions:
            write["if_version"] = versions[key]
        writes.append(write)
    return writes
