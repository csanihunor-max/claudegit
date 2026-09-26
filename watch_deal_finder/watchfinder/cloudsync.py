"""Cloud mode: the watcher's state lives in a claude.ai artifact's database.

A scheduled cloud session starts from an empty container every run, so it:
1. dumps the artifact database to local JSON files (ArtifactData list/get with out_dir),
2. runs `python main.py cloud-pass --state <dump> --out <dir>`, which rebuilds a
   throwaway SQLite database from the dump (`import_state`), does one normal pass,
   and writes only what changed back out as JSON files plus ready-made batch
   manifests (`export_state`),
3. applies those batches with ArtifactData and reports the alerts.

The database refuses an unpinned write to a document that was read, so the
dump directory also holds `versions.json` ({"shards/s00": 3, "state/seen": 7,
...}, the versions the reads reported) and every write to an existing document
carries that `if_version`. A write that loses a race with the page (a status
click in between) then fails cleanly instead of overwriting it; the next run
redoes the work.

Artifact database layout:
    shards/s00..s15     {"items": {doc_id: listing}}: every listing, spread over
                        16 documents by a stable hash (a database holds at most
                        5,000 documents of 256 KiB; ~700 bytes per listing). The
                        page writes only `items.<id>.user_status` (nested update
                        merges); this module never writes that field.
    state/seen          {"last_seen": {doc_id: iso}, "last_checked": {...}, "seeded": [...]}
                        kept apart so listing documents only change on real changes.
    meta/status         last run time and summary, plus the search settings the
                        dashboard needs for margins.
    refs/<id>           {"model": "raketa copernicus", "eur": 90}: per-model resale
                        references the owner sets on the dashboard after checking
                        eBay sold prices. Read-only here (see `load_model_references`).
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import AppConfig
from .filters import blacklisted
from .market import (MAX_COMPS, MAX_SPREAD, MIN_COMPS, MIN_COMPS_HOT, WINDOW_DAYS, MarketIndex, is_parts,
                     listing_records)
from .notify import Alert
from .storage import USER_STATUSES, Storage

SHARDS = "shards"
SHARD_COUNT = 16
STATE, SEEN = "state", "seen"
META, STATUS = "meta", "status"
BATCH_SIZE = 50
# An artifact database holds at most 5,000 documents, so gone listings are
# deleted after this many days unless marked interested/bought.
PRUNE_GONE_AFTER_DAYS = 30

# Fields this module owns in a listing document (everything except user_status).
ENGINE_FIELDS = (
    "source", "listing_id", "title", "price", "currency", "price_huf", "url", "location",
    "thumbnail_url", "category", "first_seen", "status", "gone_at", "searches", "history", "alerted",
    "comps_query", "ident", "market", "parts",
)

_BAD_ID_CHARS = re.compile(r"[^A-Za-z0-9_\-.~:@+]")


def doc_id(source: str, listing_id: str) -> str:
    return _BAD_ID_CHARS.sub("_", f"{source}-{listing_id}")[:200]


def shard_of(did: str) -> str:
    # FNV-1a: stable across runs and Python versions (unlike hash()).
    h = 2166136261
    for byte in did.encode("utf-8"):
        h = ((h ^ byte) * 16777619) & 0xFFFFFFFF
    return f"s{h % SHARD_COUNT:02d}"


class CollectingNotifier:
    """Keeps alerts in memory; the cloud session reports them as its push notification."""

    def __init__(self) -> None:
        self.alerts: list[Alert] = []

    def send(self, alert: Alert) -> bool:
        self.alerts.append(alert)
        return True


# -- reading the dump ------------------------------------------------------


def _unwrap(raw: Any) -> dict[str, Any]:
    """ArtifactData files may hold the bare document or an envelope around it."""
    if isinstance(raw, dict):
        for key in ("data", "fields", "doc"):
            if isinstance(raw.get(key), dict) and ("version" in raw or "id" in raw or "doc_id" in raw):
                return raw[key]
    return raw if isinstance(raw, dict) else {}


def load_versions(state_dir: Path) -> dict[str, int]:
    """versions.json written next to the dump: {"collection/doc_id": version}."""
    path = state_dir / "versions.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): int(v) for k, v in raw.items() if str(v).isdigit()}


def load_model_references(state_dir: Path) -> dict[str, float]:
    """Per-model references set on the dashboard (refs/<id> documents in the dump)."""
    refs: dict[str, float] = {}
    for doc in load_docs(state_dir / "refs").values():
        model, eur = doc.get("model"), doc.get("eur")
        if isinstance(model, str) and model.strip() and isinstance(eur, (int, float)) and eur > 0:
            refs[model.strip()] = float(eur)
    return refs


def load_docs(directory: Path) -> dict[str, dict[str, Any]]:
    docs: dict[str, dict[str, Any]] = {}
    if directory.is_dir():
        for path in sorted(directory.glob("*.json")):
            docs[path.stem] = _unwrap(json.loads(path.read_text(encoding="utf-8")))
    return docs


def import_state(storage: Storage, state_dir: Path) -> dict[str, dict[str, Any]]:
    """Rebuild the SQLite tables from a dump. Returns the listings by doc id, each
    with a `_shard` key naming the shard document it came from."""
    listings: dict[str, dict[str, Any]] = {}
    for shard, body in load_docs(state_dir / SHARDS).items():
        for did, item in (body.get("items") or {}).items():
            if isinstance(item, dict) and item.get("source") and item.get("listing_id"):
                listings[did] = {**item, "_shard": shard}
    seen = load_docs(state_dir / STATE).get(SEEN, {})
    last_seen = seen.get("last_seen") or {}
    last_checked = seen.get("last_checked") or {}

    with storage.transaction() as conn:
        for did, d in listings.items():
            history = d.get("history") or []
            first_seen = d.get("first_seen") or (history[0]["t"] if history else "1970-01-01T00:00:00+00:00")
            user_status = d.get("user_status") if d.get("user_status") in USER_STATUSES else None
            conn.execute(
                """INSERT OR REPLACE INTO listings (source, listing_id, title, price, currency, price_huf, url,
                       location, thumbnail_url, category, first_seen, last_seen, last_checked, status, gone_at,
                       user_status, ident)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (d["source"], d["listing_id"], d.get("title", ""), d.get("price"), d.get("currency", "HUF"),
                 d.get("price_huf"), d.get("url", ""), d.get("location"), d.get("thumbnail_url"),
                 d.get("category"), first_seen, last_seen.get(did) or first_seen, last_checked.get(did),
                 d.get("status") or "active", d.get("gone_at"), user_status,
                 json.dumps(d["ident"], ensure_ascii=False) if isinstance(d.get("ident"), dict) else None),
            )
            for point in history:
                conn.execute(
                    "INSERT INTO price_history (source, listing_id, price, currency, price_huf, seen_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (d["source"], d["listing_id"], point.get("price"), d.get("currency", "HUF"), point.get("huf"),
                     point["t"]),
                )
            for name in d.get("searches") or []:
                storage.link_search(d["source"], d["listing_id"], name)
            for huf in d.get("alerted") or []:
                conn.execute(
                    "INSERT OR IGNORE INTO alerts_sent (source, listing_id, price_huf, kind, sent_at) VALUES (?, ?, ?, 'restored', ?)",
                    (d["source"], d["listing_id"], huf, first_seen),
                )
        for key in seen.get("seeded") or []:
            search_name, _, source = key.rpartition("|")
            storage.mark_seeded(search_name, source, "1970-01-01T00:00:00+00:00")
    return listings


# -- writing the changes ---------------------------------------------------


def listing_docs(storage: Storage, config: AppConfig) -> dict[str, dict[str, Any]]:
    conn = storage.conn
    records = listing_records(storage, config)
    idents = {(r["source"], r["listing_id"]): r["ident"] for r in records}
    index = MarketIndex(records)
    searches: dict[tuple[str, str], list[str]] = {}
    for r in conn.execute("SELECT source, listing_id, search_name FROM listing_searches ORDER BY search_name"):
        searches.setdefault((r[0], r[1]), []).append(r[2])
    history: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in conn.execute("SELECT source, listing_id, price, price_huf, seen_at FROM price_history ORDER BY seen_at, id"):
        history.setdefault((r[0], r[1]), []).append({"t": r[4], "huf": r[3], "price": r[2]})
    alerted: dict[tuple[str, str], list[int]] = {}
    for r in conn.execute("SELECT source, listing_id, price_huf FROM alerts_sent ORDER BY price_huf"):
        alerted.setdefault((r[0], r[1]), []).append(r[2])

    docs = {}
    for r in conn.execute("SELECT * FROM listings"):
        key = (r["source"], r["listing_id"])
        docs[doc_id(*key)] = {
            "source": r["source"], "listing_id": r["listing_id"], "title": r["title"], "price": r["price"],
            "currency": r["currency"], "price_huf": r["price_huf"], "url": r["url"], "location": r["location"],
            "thumbnail_url": r["thumbnail_url"], "category": r["category"], "first_seen": r["first_seen"],
            "status": r["status"], "gone_at": r["gone_at"], "searches": searches.get(key, []),
            "history": history.get(key, []), "alerted": alerted.get(key, []),
            # model words for the "eBay sold" link, and the groups used for market references
            "comps_query": idents[key].query,
            "ident": json.loads(idents[key].to_json()),
            # the median of this listing's comparable ads, and which ads those are (see market.py)
            "market": _market_doc(index, idents[key], config, doc_id(*key)),
            "parts": is_parts(r["title"]),
        }
    return docs


def _market_doc(index: MarketIndex, ident, config: AppConfig, did: str) -> dict[str, Any] | None:
    ref = index.reference(ident, config.eur_huf_rate, exclude_id=did)
    return ref.to_doc() if ref else None


def _engine_view(doc: dict[str, Any]) -> dict[str, Any]:
    return {k: doc.get(k) for k in ENGINE_FIELDS}


def export_state(
    storage: Storage,
    config: AppConfig,
    imported: dict[str, dict[str, Any]],
    out_dir: Path,
    run_at: str,
    summary: dict[str, Any],
    alerts: list[Alert],
    versions: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Write changed documents and batch manifests under out_dir. Returns a small report.

    `versions` maps "collection/doc_id" to the version read in the dump; writes to
    those documents are pinned with it."""
    out_dir = out_dir.resolve()
    versions = versions or {}
    docs_dir = out_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    writes: list[dict[str, Any]] = []

    def add(op: str, collection: str, did: str, data: dict[str, Any]) -> None:
        path = docs_dir / f"{collection}__{did}.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        write = {"op": op, "collection": collection, "doc_id": did, "file_path": str(path)}
        if f"{collection}/{did}" in versions:
            write["if_version"] = versions[f"{collection}/{did}"]
            if op == "set" and collection == SHARDS:
                write["op"] = "update"  # an existing shard is merged, never replaced
        writes.append(write)

    cutoff = (datetime.fromisoformat(run_at) - timedelta(days=PRUNE_GONE_AFTER_DAYS)).isoformat()
    keep_statuses = {"interested", "bought"}
    pruned: list[str] = []
    # Gone for a month, or matching a blacklist word added since the listing was stored.
    candidates = storage.conn.execute(
        "SELECT source, listing_id, user_status, title, status, gone_at FROM listings"
    ).fetchall()
    for r in candidates:
        old_gone = r[4] == "gone" and (r[5] or "") < cutoff
        if not old_gone and not blacklisted(r[3], config.blacklist):
            continue
        did = doc_id(r[0], r[1])
        # user_status lives in the artifact (the page writes it); trust the dump over SQLite.
        if (imported.get(did) or {}).get("user_status", r[2]) in keep_statuses:
            continue
        for table in ("price_history", "listing_searches", "alerts_sent", "listings"):  # listings last (FK)
            storage.conn.execute(f"DELETE FROM {table} WHERE source = ? AND listing_id = ?", (r[0], r[1]))
        if did in imported:
            pruned.append(did)
    storage.conn.commit()

    # Group current listings by shard; write a shard only if something in it changed.
    by_shard: dict[str, dict[str, Any]] = {}
    new_count = changed_count = 0
    dirty: set[str] = set()
    for did, doc in listing_docs(storage, config).items():
        shard = shard_of(did)
        by_shard.setdefault(shard, {})[did] = doc
        before = imported.get(did)
        if before is None:
            new_count += 1
            dirty.add(shard)
        elif _engine_view(before) != _engine_view(doc):
            changed_count += 1
            dirty.add(shard)
    for did in pruned:
        dirty.add(imported[did]["_shard"])
    existing_shards = {d["_shard"] for d in imported.values()}
    for shard in sorted(dirty):
        items: dict[str, Any] = dict(by_shard.get(shard, {}))
        for did in pruned:
            if imported[did]["_shard"] == shard:
                items[did] = {"__delete__": True}
        # "update" merges recursively, so the page's user_status fields survive.
        add("update" if shard in existing_shards else "set", SHARDS, shard, {"items": items})

    rows = storage.conn.execute("SELECT source, listing_id, last_seen, last_checked FROM listings").fetchall()
    seeded = [f"{r[0]}|{r[1]}" for r in storage.conn.execute("SELECT search_name, source FROM search_state")]
    add("set", STATE, SEEN, {
        "last_seen": {doc_id(r[0], r[1]): r[2] for r in rows},
        "last_checked": {doc_id(r[0], r[1]): r[3] for r in rows if r[3]},
        "seeded": sorted(seeded),
    })
    add("set", META, STATUS, {
        "last_run": run_at,
        "summary": summary,
        "alerts": [{"title": a.title, "body": a.body, "url": a.url, "comps_url": a.comps_url} for a in alerts],
        "eur_huf_rate": config.eur_huf_rate,
        "hot_deal_ratio": config.hot_deal_ratio,
        "ebay_sold_domain": config.ebay.sold_domain,
        "market_rules": {"min_comps": MIN_COMPS, "min_comps_hot": MIN_COMPS_HOT, "max_comps": MAX_COMPS,
                         "max_spread": MAX_SPREAD, "window_days": WINDOW_DAYS},
        "ebay_category": config.ebay.category_ids,
        "searches": [
            {"name": s.name, "keywords": list(s.keywords), "max_price_huf": s.max_price_huf,
             "reference_price_eur": s.reference_price_eur}
            for s in config.searches
        ],
    })

    batches = []
    for i in range(0, len(writes), BATCH_SIZE):
        path = out_dir / f"batch_{i // BATCH_SIZE + 1:02d}.json"
        path.write_text(json.dumps(writes[i:i + BATCH_SIZE], ensure_ascii=False, indent=1), encoding="utf-8")
        batches.append(str(path))

    alerts_md = out_dir / "alerts.md"
    alerts_md.write_text(
        "\n\n".join(
            f"{a.title}\n{a.body}\n{a.url or ''}" + (f"\nSold comps: {a.comps_url}" if a.comps_url else "")
            for a in alerts
        ) or "No new deals.",
        encoding="utf-8",
    )
    report = {
        "run_at": run_at, "new_listings": new_count, "changed_listings": changed_count, "pruned": len(pruned),
        "alerts": len(alerts),
        "batches": batches, "alerts_file": str(alerts_md), **summary,
    }
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report
