"""Read-only web dashboard over the same SQLite DB the scraper writes to.

Runs as its own process (`python -m hardverapro_arbitrage serve`), so it
stays reachable even if the scrape loop is mid-cycle, and vice versa.
Deals are listed with the biggest relative bargain first (discount % below
the item's own market reference price), ties broken by absolute savings —
see README for why % is the primary ranking, not raw savings.

Reachability: bound to HA_WEB_HOST (default 0.0.0.0, i.e. every network
interface on the machine it runs on) and HA_WEB_PORT. That makes it
reachable on your LAN; to reach it from your phone while away from home
you still need a tunnel back to that machine (Tailscale, an SSH -L port
forward, a reverse proxy with auth) — this process has no built-in
authentication, so don't expose it to the open internet as-is.
"""
from __future__ import annotations

import sqlite3

from flask import Flask, jsonify, render_template_string

from .config import Config
from .storage import db

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
  </style>
</head>
<body>
  <h1>Best Hardverapro deals right now</h1>
  <p class="meta">Ranked by % below each item's recent market price. Last {{ window_days }} days, top {{ limit }}. Auto-refreshes every 5 min.</p>
  {% if deals %}
  <table>
    <thead>
      <tr>
        <th>Discount</th>
        <th>Item</th>
        <th>Price</th>
        <th>Market ref.</th>
        <th>Savings</th>
        <th>Location</th>
        <th>Detected</th>
      </tr>
    </thead>
    <tbody>
      {% for d in deals %}
      <tr>
        <td class="discount">{{ "%.0f"|format(d.discount_fraction * 100) }}%</td>
        <td><a href="{{ d.url }}" target="_blank" rel="noopener">{{ d.title }}</a></td>
        <td class="price">{{ "{:,.0f}".format(d.price) }} {{ d.currency }}</td>
        <td class="price">{{ "{:,.0f}".format(d.market_reference_price) }} {{ d.currency }}</td>
        <td class="price">{{ "{:,.0f}".format(d.market_reference_price - d.price) }} {{ d.currency }}</td>
        <td>{{ d.location or "" }}</td>
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


def _deal_to_dict(row: sqlite3.Row) -> dict:
    return {
        "listing_id": row["listing_id"],
        "title": row["title"],
        "url": row["url"],
        "price": row["price"],
        "currency": row["currency"],
        "location": row["location"],
        "market_reference_price": row["market_reference_price"],
        "discount_fraction": row["discount_fraction"],
        "sample_size": row["sample_size"],
        "detected_at": row["detected_at"],
    }


def create_app(config: Config) -> Flask:
    app = Flask(__name__)

    def _get_conn() -> sqlite3.Connection:
        # A fresh connection per request: simplest way to be safe if the
        # scraper process (a separate process) is writing to the same
        # SQLite file concurrently.
        return db.connect(config.db_path)

    @app.get("/")
    def dashboard():
        conn = _get_conn()
        try:
            rows = db.get_recent_deals(conn, config.deals_list_window_days, config.deals_list_limit)
        finally:
            conn.close()
        return render_template_string(
            _TEMPLATE,
            deals=[_deal_to_dict(r) for r in rows],
            window_days=config.deals_list_window_days,
            limit=config.deals_list_limit,
        )

    @app.get("/api/deals")
    def api_deals():
        conn = _get_conn()
        try:
            rows = db.get_recent_deals(conn, config.deals_list_window_days, config.deals_list_limit)
        finally:
            conn.close()
        return jsonify([_deal_to_dict(r) for r in rows])

    @app.get("/healthz")
    def healthz():
        return {"status": "ok"}

    return app


def run(config: Config) -> None:
    app = create_app(config)
    app.run(host=config.web_host, port=config.web_port)
