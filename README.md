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
   Gumtree's results are plain server-rendered HTML, fetched with
   `requests`. AutoTrader's results page is a JS-rendered SPA (the raw
   HTTP response is just an empty `<div id="root">`), so that scraper
   drives a real headless Chromium via Playwright to render the page
   before parsing it.
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
playwright install chromium   # downloads the browser AutoTrader's scraper drives
cp config.example.yaml config.yaml
```

Edit `config.yaml`: set your `filters` (make/model are optional — leave them
`null` to match any make/model), pick which
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

- Both sites' markup changes periodically and neither publishes a stable API
  for this. Outbound network access to autotrader.co.uk/gumtree.com is
  blocked by policy in the environment this was built in, so the scrapers'
  *navigation* (actually loading a live search results page end-to-end) could
  never be run from there. AutoTrader's *parsing* logic (`parse_results_page`
  in `scrapers/autotrader.py`) was however verified against a real listing
  card's outerHTML pasted in by hand, including two non-obvious gotchas that
  are now handled: a visually-hidden accessibility `<span>` nested inside the
  title link (would otherwise corrupt the title/make/model), and an SVG icon
  inside the location element (would otherwise leak "Dealer location" into
  the location text). Gumtree has been confirmed working against the live
  site. Run `--verbose --dry-run`; if the log says `0 listings parsed`, the
  site's markup has likely changed further:
  - For **Gumtree** (plain HTML), view-source on a live search results page
    and update the selectors in `scrapers/gumtree.py`.
  - For **AutoTrader** (JS-rendered SPA), view-source will show almost
    nothing useful — you need the *rendered* DOM. Use your browser's dev
    tools (Inspect Element) on a live search results page and update the
    `*_SELECTOR` constants at the top of `scrapers/autotrader.py`. Note the
    price element's class name is a build hash that changes on every
    AutoTrader deploy, which is why price is matched by a standalone
    "£n,nnn" text pattern instead of a class selector.
- AutoTrader's results load via infinite scroll (an
  `.infinite-scroll-component` container), not classic `?page=N` links, so
  `AutoTraderScraper.fetch_listings` navigates once and then triggers
  scrolling to load further batches, stopping once a few consecutive scrolls
  produce no new listings. `max_pages` for this source means "how many such
  batches to collect," not literal pages.
- Scraping is rate-limited (`scraping.request_delay_seconds`, default 3s
  between pages) and paginated conservatively (`max_pages` per source,
  default 3) to keep load on these sites low. Review each site's Terms of
  Service and `robots.txt` before running this regularly — some sites
  prohibit automated scraping outright. This tool is intended for personal,
  low-volume use (checking listings for yourself), not for republishing data
  or high-frequency polling.
- The AutoTrader scraper launches a real headless Chromium per run via
  Playwright (`AutoTraderScraper.fetch_page_html`/`_ensure_browser` in
  `scrapers/autotrader.py`) since its search results only exist after
  client-side JS runs. This is heavier and slower than a plain HTTP request,
  and AutoTrader may still serve a bot-detection/cookie-consent challenge to
  headless browsers — if `wait_for_selector` times out waiting for listing
  cards, that'll be logged, and you may need to add consent-dialog handling
  or a stealth/anti-detection plugin depending on what AutoTrader shows.

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
    base.py               # shared pagination/rate-limiting/parsing helpers
    autotrader.py           # AutoTrader: Playwright-rendered fetch + markup parsing
    gumtree.py                # Gumtree: requests-based fetch + markup parsing
config.example.yaml           # copy to config.yaml and fill in
tests/                          # pytest unit tests
```
