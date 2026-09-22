"""Read-only web dashboard over the same SQLite DB the scraper writes to.

Runs as its own process (`python -m hardverapro_arbitrage serve`), so it
stays reachable even if the scrape loop is mid-cycle, and vice versa.
Deals are listed with the biggest relative bargain first (discount % below
the item's own market reference price), ties broken by absolute savings.

Reachability: bound to HA_WEB_HOST (default 0.0.0.0, i.e. every network
interface on the machine it runs on) and HA_WEB_PORT. That makes it
reachable on your LAN; to reach it from your phone while away from home
you still need a tunnel back to that machine (Tailscale, an SSH -L port
forward, a reverse proxy with auth) — this process has no built-in
authentication, so don't expose it to the open internet as-is.
"""
from __future__ import annotations

import logging
import sqlite3

from flask import Flask, jsonify, redirect, render_template_string, request, url_for

from .config import Config
from .geo import describe_location
from .notify.base import Notifier
from .notify.console import ConsoleNotifier
from .notify.telegram import TelegramNotifier
from .pipeline import run_once
from .scraper.client import HardveraproClient
from .storage import db

logger = logging.getLogger(__name__)

_TEMPLATE = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="refresh" content="300">
  <title>Hardverapro deals</title>
  <style>
    body { font-family: -apple-system, system-ui, sans-serif; margin: 0; padding: 1rem;
           background: #111; color: #eee; }
    h1 { font-size: 1.1rem; font-weight: 600; margin: 0 0 0.75rem; }
    .meta { color: #888; font-size: 0.8rem; margin-bottom: 1rem; }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th, td { text-align: left; padding: 0.5rem 0.4rem; border-bottom: 1px solid #333; }
    th { color: #999; font-weight: 500; font-size: 0.75rem; text-transform: uppercase; }
    a { color: #6cf; text-decoration: none; }
    a:hover { text-decoration: underline; }
    .discount { font-weight: 700; color: #4d9; }
    .price { white-space: nowrap; }
    .empty { color: #888; padding: 2rem 0; text-align: center; }
    .toolbar { display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: 0.5rem; flex-wrap: wrap; }
    button.refresh { background: #234; color: #eee; border: 1px solid #456; border-radius: 6px; padding: 0.4rem 0.9rem;
                      font-size: 0.85rem; cursor: pointer; }
    button.refresh:hover { background: #345; }
  </style>
</head>
<body>
  <div class="toolbar">
    <h1>Best Hardverapro deals right now</h1>
    <form method="post" action="{{ url_for('refresh') }}">
      <button class="refresh" type="submit">↻ Refresh now</button>
    </form>
  </div>
  {% if refresh_error %}<p class="meta" style="color:#e77">{{ refresh_error }}</p>{% endif %}
  <p class="meta">
    <b>Discount</b> — % below other resale listings of the same item on hardverapro.hu
    itself. <b>Distance</b> — straight-line km from Budapest, best-effort from the
    listing's location text (a fixed lookup table of known towns, not a geocoding
    service — "—" means the location wasn't recognized). Last {{ window_days }} days,
    top {{ limit }}. Auto-refreshes every 5 min, or click Refresh for an immediate
    rescan (can take several minutes with the default 52-category list — this
    blocks until it's done, it hasn't hung). Click a column header to sort by it
    (click again to flip direction).
  </p>
  <form method="get" class="toolbar" style="margin-bottom: 0.75rem;">
    <input type="hidden" name="sort" value="{{ sort }}">
    <input type="hidden" name="dir" value="{{ dir }}">
    <label class="meta" for="category-filter">Category:
      <select name="category" id="category-filter" onchange="this.form.submit()">
        <option value="" {{ "selected" if not category else "" }}>All ({{ all_deals_count }})</option>
        {% for c in categories %}
        <option value="{{ c }}" {{ "selected" if c == category else "" }}>{{ c }}</option>
        {% endfor %}
      </select>
    </label>
  </form>
  {% if deals %}
  <table>
    <thead>
      <tr>
        <th><a href="{{ sort_links.discount }}">Discount{{ sort_arrows.discount }}</a></th>
        <th>Item</th>
        <th><a href="{{ sort_links.category }}">Category{{ sort_arrows.category }}</a></th>
        <th><a href="{{ sort_links.price }}">Price{{ sort_arrows.price }}</a></th>
        <th>Reference</th>
        <th><a href="{{ sort_links.savings }}">Savings{{ sort_arrows.savings }}</a></th>
        <th>Location</th>
        <th><a href="{{ sort_links.distance }}">Distance{{ sort_arrows.distance }}</a></th>
        <th><a href="{{ sort_links.detected }}">Detected{{ sort_arrows.detected }}</a></th>
      </tr>
    </thead>
    <tbody>
      {% for d in deals %}
      <tr>
        <td class="discount">{{ "%.0f"|format(d.discount_fraction * 100) }}%</td>
        <td><a href="{{ d.url }}" target="_blank" rel="noopener">{{ d.title }}</a></td>
        <td>{{ d.source_label or "" }}</td>
        <td class="price">{{ "{:,.0f}".format(d.price) }} {{ d.currency }}</td>
        <td class="price">{{ "{:,.0f}".format(d.market_reference_price) }} {{ d.currency }}</td>
        <td class="price">{{ "{:,.0f}".format(d.market_reference_price - d.price) }} {{ d.currency }}</td>
        <td>{{ d.location or "" }}</td>
        <td class="price">{% if d.distance_km is not none %}{{ "%.0f"|format(d.distance_km) }} km ({{ d.region }}){% else %}—{% endif %}</td>
        <td>{{ d.detected_at.split("T")[0] }}</td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
  {% else %}
  <p class="empty">No deals detected yet. Either the scraper hasn't found any, or it hasn't run yet — see README for how to start it.</p>
  {% endif %}
</body>
</html>
"""


# Each column's key function and its default direction when first sorted
# by (a column always defaults to whichever direction is more useful --
# biggest discount/savings/newest first, cheapest price and A-Z category
# first). Clicking an already-active column flips it instead.
_SORT_KEYS: dict[str, tuple] = {
    "discount": (lambda d: d["discount_fraction"], "desc"),
    "price": (lambda d: d["price"], "asc"),
    "category": (lambda d: (d["source_label"] or "").lower(), "asc"),
    "savings": (lambda d: d["savings"], "desc"),
    "detected": (lambda d: d["detected_at"], "desc"),
    "distance": (None, "asc"),  # special-cased in _sort_deals -- see below
}
_DEFAULT_SORT = "discount"


def _sort_deals(deals: list[dict], sort: str, direction: str) -> list[dict]:
    if sort == "distance":
        # Unmatched locations (distance_km is None) always sort last,
        # regardless of direction -- "unknown" is never "closest" or
        # "farthest", it's just missing, so a plain reverse=True/False on
        # a single key (e.g. treating None as infinity) would wrongly put
        # them first when sorting "farthest first".
        known = [d for d in deals if d["distance_km"] is not None]
        unknown = [d for d in deals if d["distance_km"] is None]
        known.sort(key=lambda d: d["distance_km"], reverse=(direction == "desc"))
        return known + unknown
    key_fn, _ = _SORT_KEYS.get(sort, _SORT_KEYS[_DEFAULT_SORT])
    return sorted(deals, key=key_fn, reverse=(direction == "desc"))


def _resolve_sort(sort: str | None, direction: str | None) -> tuple[str, str]:
    sort = sort if sort in _SORT_KEYS else _DEFAULT_SORT
    direction = direction if direction in ("asc", "desc") else _SORT_KEYS[sort][1]
    return sort, direction


def _deal_to_dict(row: sqlite3.Row) -> dict:
    location = row["location"]
    geo = describe_location(location)
    return {
        "listing_id": row["listing_id"],
        "title": row["title"],
        "url": row["url"],
        "price": row["price"],
        "currency": row["currency"],
        "location": location,
        "distance_km": geo["distance_km"] if geo else None,
        "region": geo["region"] if geo else None,
        "market_reference_price": row["market_reference_price"],
        "discount_fraction": row["discount_fraction"],
        "sample_size": row["sample_size"],
        "savings": row["market_reference_price"] - row["price"],
        "detected_at": row["detected_at"],
        "source_label": row["source_label"],
    }


def _build_notifiers(config: Config) -> list[Notifier]:
    notifiers: list[Notifier] = [ConsoleNotifier()]
    if config.telegram_bot_token and config.telegram_chat_id:
        notifiers.append(TelegramNotifier(config.telegram_bot_token, config.telegram_chat_id))
    return notifiers


def create_app(config: Config) -> Flask:
    app = Flask(__name__)

    def _get_conn() -> sqlite3.Connection:
        # A fresh connection per request: simplest way to be safe if the
        # scraper process (a separate process) is writing to the same
        # SQLite file concurrently.
        return db.connect(config.db_path)

    @app.get("/")
    def dashboard(refresh_error: str | None = None):
        conn = _get_conn()
        try:
            rows = db.get_recent_deals(
                conn,
                config.deals_list_window_days,
                config.deals_list_limit,
                max_listing_age_seconds=config.poll_interval_seconds * 2,
            )
        finally:
            conn.close()
        all_deals = [_deal_to_dict(r) for r in rows]
        categories = sorted({d["source_label"] for d in all_deals if d["source_label"]})

        sort, direction = _resolve_sort(request.args.get("sort"), request.args.get("dir"))
        category = request.args.get("category") or None
        deals = [d for d in all_deals if not category or d["source_label"] == category]
        deals = _sort_deals(deals, sort, direction)

        def _toggle_dir(col: str) -> str:
            if sort == col:
                return "asc" if direction == "desc" else "desc"
            return _SORT_KEYS[col][1]

        sort_links = {
            col: url_for("dashboard", sort=col, dir=_toggle_dir(col), category=category)
            for col in _SORT_KEYS
        }
        sort_arrows = {col: (" ▲" if direction == "asc" else " ▼") if sort == col else "" for col in _SORT_KEYS}

        return render_template_string(
            _TEMPLATE,
            deals=deals,
            window_days=config.deals_list_window_days,
            limit=config.deals_list_limit,
            refresh_error=refresh_error,
            sort=sort,
            dir=direction,
            category=category or "",
            categories=categories,
            all_deals_count=len(all_deals),
            sort_links=sort_links,
            sort_arrows=sort_arrows,
        )

    @app.post("/refresh")
    def refresh():
        # Synchronous and blocking on purpose: a manual refresh button on a
        # personal dashboard, not a production endpoint. Takes as long as
        # one full scrape cycle -- with the default 52-category list and
        # HA_MAX_PAGES_PER_CATEGORY=6, that's several minutes, not the
        # "under a minute" this used to promise back when there were far
        # fewer categories; a narrower HA_SEARCH_URLS is proportionally
        # faster.
        if not config.search_urls:
            return dashboard(refresh_error="Can't refresh: HA_SEARCH_URLS isn't set.")
        conn = _get_conn()
        try:
            with HardveraproClient(config) as client:
                run_once(config, conn, client, _build_notifiers(config))
        except Exception:
            logger.exception("manual refresh failed")
            return dashboard(refresh_error="Refresh failed — see the server log for details.")
        finally:
            conn.close()
        return redirect(url_for("dashboard"))

    @app.get("/api/deals")
    def api_deals():
        conn = _get_conn()
        try:
            rows = db.get_recent_deals(
                conn,
                config.deals_list_window_days,
                config.deals_list_limit,
                max_listing_age_seconds=config.poll_interval_seconds * 2,
            )
        finally:
            conn.close()
        deals = [_deal_to_dict(r) for r in rows]

        category = request.args.get("category") or None
        if category:
            deals = [d for d in deals if d["source_label"] == category]
        sort, direction = _resolve_sort(request.args.get("sort"), request.args.get("dir"))
        deals = _sort_deals(deals, sort, direction)

        return jsonify(deals)

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


def run(config: Config) -> None:
    app = create_app(config)
    app.run(host=config.web_host, port=config.web_port)
