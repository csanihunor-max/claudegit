# Hardverapro Arbitrage Scraper

Polls one or more hardverapro.hu search-result pages every hour, tracks
prices per item over time, and flags listings priced well below that
item's own recent second-hand market price.

## ⚠️ Selectors are unverified

This was built in an environment with **no network access to
hardverapro.hu**, so the HTML parsing selectors in
`hardverapro_arbitrage/scraper/parser.py` (`_SELECTORS`) are best-effort
guesses, not something run against the real site. Before trusting any of
this:

1. Save a real search-results page's HTML (browser → View Source, or
   `curl` it locally).
2. Run it through `parse_search_results()` (see `tests/test_parser.py` for
   the pattern) and compare the output to what the page actually shows.
3. Fix `_SELECTORS` in `parser.py` to match. Everything downstream
   (normalization, pricing, arbitrage detection, storage, notification) is
   independent of the site markup and is already tested.

## How "market price" is computed

There's no external second-hand price API wired in. Instead, the bot
computes its own reference price per item: the **median of all other
recent listings for the same normalized item title**, computed from its
own price-history database. A listing is flagged as a deal once it's
priced `HA_DEAL_THRESHOLD` (default 20%) or more below that median, and
only once at least `HA_MIN_SAMPLES` (default 3) other listings of that
item have been seen — otherwise there's nothing to compare against.

Titles are normalized (`scraper/normalize.py`) by lowercasing, stripping
accents/punctuation, and removing common Hungarian marketplace filler
words ("eladó", "garanciával", "használt", ...) so e.g. "Eladó iPhone 12
128GB garanciával" and "iPhone 12 128 GB" are recognized as the same item.
This is intentionally conservative — it only merges listings whose titles
reduce to an *identical* key, so it never guesses that two differently
named products are the same thing.

If you actually have a specific external price reference in mind (a price
list, another marketplace, etc.) instead of this self-referential
approach, swap out `pricing/market.py` — nothing else needs to change.

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
# edit .env: at minimum set HA_SEARCH_URLS to your saved search URL(s)
```

## Running

```bash
# one scrape cycle, then exit (good for testing/cron)
python -m hardverapro_arbitrage --once

# run forever, once per HA_POLL_INTERVAL_SECONDS (default: hourly)
python -m hardverapro_arbitrage
```

Deals are always logged to the console. Set `HA_TELEGRAM_BOT_TOKEN` and
`HA_TELEGRAM_CHAT_ID` in `.env` to also get a Telegram message per deal
(see comments in `.env.example` for how to obtain them). Each
(listing, price) pair is only ever notified once — a re-scrape at the
same price won't spam you again, but a further price drop will.

## Configuration

All of it lives in environment variables, read by
`hardverapro_arbitrage/config.py`; see `.env.example` for the full list
and defaults.

## Data

Prices are stored in a local SQLite file (`HA_DB_PATH`, default
`hardverapro_arbitrage.sqlite3`). Every scrape of every listing is kept as
one row in `observations`, so the price history simply builds up over
time — nothing is ever deleted automatically.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Covers normalization, market-reference math, deal detection, storage, and
parsing against a synthetic fixture (see the warning above — the fixture
matches the guessed selectors, it isn't real site HTML).
