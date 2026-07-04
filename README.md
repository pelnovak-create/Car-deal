# Car Deal Agent

A Python agent that scrapes AutoTrader UK and Gumtree for used car listings
matching your filters, estimates a fair market price for each one by
comparing it against similar listings it has seen, flags listings priced
well below that estimate as "good deals", and sends you a notification.
Seen listings are stored in SQLite so you're only notified about genuinely
new listings.

## How it works

1. **Scrape** — `car_deal_agent/scrapers/{autotrader,gumtree}.py` fetch search
   result pages for your filters (make, model, year/price/mileage range,
   location) and parse each listing card into a normalized `Listing`.
2. **Filter** — `filters.py` re-applies your filters in Python so results are
   consistent across both sites regardless of what each site's search
   supports natively.
3. **Score** — `pricing.py` groups comparable listings (same make/model/year,
   falling back to make/model if there aren't enough) and computes the
   median price of the group as a market-price estimate. A listing priced
   `deal_threshold_pct` or more below that estimate is flagged as a good
   deal, provided the group has at least `min_group_size` comparables (below
   that, there's no reliable estimate and nothing is flagged).
4. **Store & dedupe** — `db.py` upserts every listing into SQLite keyed by
   `source:external_id`. Only listings that are brand new *and* flagged as
   good deals trigger a notification.
5. **Notify** — `notifier.py` supports console output, local desktop
   notifications (`notify-send` on Linux), email (SMTP), and Telegram. Enable
   any combination in your config.

## Setup

```bash
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

Edit `config.yaml`: set your `filters` (make/model are required), pick which
`sources` to scrape, tune the `pricing` thresholds, and configure
`notifications`. Secrets (email password, Telegram bot token) can be inlined
or pulled from environment variables using `${VAR_NAME}` syntax.

- **Telegram**: message [@BotFather](https://t.me/BotFather) to create a bot
  and get a token; message your bot once, then fetch
  `https://api.telegram.org/bot<token>/getUpdates` to find your `chat_id`.
- **Email**: for Gmail, use an
  [app password](https://support.google.com/accounts/answer/185833) rather
  than your real password.

## Usage

```bash
# Single run
python -m car_deal_agent --config config.yaml

# Run continuously, checking every 60 minutes
python -m car_deal_agent --config config.yaml --interval-minutes 60

# Scrape and score but don't send notifications (logs what it would send)
python -m car_deal_agent --config config.yaml --dry-run
```

For scheduled runs on a server, a cron entry calling a single pass (without
`--interval-minutes`) is simpler to reason about than the built-in loop:

```
0 * * * * cd /path/to/Car-deal && /usr/bin/python3 -m car_deal_agent --config config.yaml >> agent.log 2>&1
```

## Important: scraper maintenance & legal considerations

- Both sites' HTML structure changes periodically and neither publishes a
  stable API for this. The CSS/`data-testid` selectors in
  `scrapers/autotrader.py` and `scrapers/gumtree.py` reflect each site's
  structure as best known at time of writing, but **this code could not be
  tested against the live sites** from the environment it was built in
  (outbound network access to those domains was blocked by network policy).
  Run it once with `--verbose --dry-run`; if the log says
  `0 listings parsed`, the site's markup has likely changed — inspect a live
  search results page in your browser's dev tools and update the
  `*_SELECTOR` constants at the top of the relevant scraper file.
- Scraping is rate-limited (`scraping.request_delay_seconds`, default 3s
  between pages) and paginated conservatively (`max_pages` per source,
  default 3) to keep load on these sites low. Review each site's Terms of
  Service and `robots.txt` before running this regularly — some sites
  prohibit automated scraping outright. This tool is intended for personal,
  low-volume use (checking listings for yourself), not for republishing data
  or high-frequency polling.
- AutoTrader in particular renders results via JavaScript and may serve
  bot-detection challenges to non-browser clients; if `requests`-based
  scraping is consistently blocked, you'd need a headless-browser-based
  fetch (e.g. Playwright) instead of `requests` — the parsing logic in
  `parse_results_page` would work unchanged against the same HTML either way.

## Running tests

```bash
pip install -r requirements.txt pytest
pytest
```

Scraper tests exercise `parse_results_page` against hand-written HTML
fixtures matching the documented selectors — they confirm the parsing logic
itself is correct, not that today's live site markup matches those fixtures.

## Project layout

```
car_deal_agent/
  config.py        # YAML config loading, defaults, validation
  models.py         # Listing / ScoredListing dataclasses
  db.py              # SQLite storage + dedup
  filters.py          # post-scrape filter matching
  pricing.py           # market-price grouping & deal scoring
  notifier.py           # console/desktop/email/telegram backends
  main.py                # CLI orchestration (scrape -> filter -> score -> notify)
  scrapers/
    base.py               # shared HTTP/rate-limiting/parsing helpers
    autotrader.py           # AutoTrader-specific URL + markup parsing
    gumtree.py                # Gumtree-specific URL + markup parsing
config.example.yaml           # copy to config.yaml and fill in
tests/                          # pytest unit tests
```
