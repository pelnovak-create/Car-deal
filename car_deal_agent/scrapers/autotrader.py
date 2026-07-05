from __future__ import annotations

import logging
import re
from typing import Iterator, Optional
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from car_deal_agent.models import Listing
from car_deal_agent.scrapers.base import (
    Scraper,
    extract_id_from_url,
    parse_fuel_type,
    parse_mileage,
    parse_price,
    parse_transmission,
    parse_year,
)

logger = logging.getLogger(__name__)

BASE_URL = "https://www.autotrader.co.uk/car-search"

# NOTE ON SELECTORS: AutoTrader's search results page is a JS-rendered SPA (the
# raw HTML response is just an empty <div id="root"> with script tags), which
# is why this scraper renders the page with a real headless browser (Playwright)
# before parsing rather than parsing the raw HTTP response body. These reflect
# the rendered DOM structure as of last review (confirmed against a real
# listing card's outerHTML); if `fetch_listings` logs "0 listings parsed",
# inspect a live, *rendered* search results page (browser dev tools, not
# view-source) and update the selectors below.
#
# Each result is a <li id="id-{advertid}" data-advertid="{advertid}"> — the
# data-advertid attribute gives a reliable external_id directly, no need to
# parse it out of the URL.
CARD_SELECTOR = "li[data-advertid]"
TITLE_SELECTOR = "[data-testid='search-listing-title']"
SUBTITLE_SELECTOR = "[data-testid='search-listing-subtitle']"
BADGES_CONTAINER_SELECTOR = "[data-testid='badges-container']"
LOCATION_SELECTOR = "[data-testid='search-listing-location']"

# The price element's CSS class is a build-hashed name (e.g. "gNFmcp") that
# changes on every AutoTrader deploy, so it can't be matched reliably. Instead
# match any standalone text node that's *just* a price ("£11,000") — this
# naturally skips longer strings like a monthly finance figure with "p/m"
# attached. If a card ever has more than one bare "£n,nnn" text node (e.g. a
# separate finance headline price), this takes the first one in DOM order,
# which is normally the main cash price.
_PRICE_TEXT_RE = re.compile(r"^£[\d,]+$")

# How long to wait for the first batch of listing cards to appear after
# navigation (the SPA needs a moment to fetch and render results client-side).
RENDER_TIMEOUT_MS = 15_000

# Results load via infinite scroll (a `.infinite-scroll-component` container),
# not classic ?page=N pagination, so `fetch_listings` triggers scrolling to
# load further batches instead of navigating to a new URL per page. Each
# "page" in `max_pages` corresponds to one such batch (initial load + one
# scroll-triggered load each).
_SCROLL_JS = """
() => {
    window.scrollTo(0, document.body.scrollHeight);
    const el = document.querySelector('.infinite-scroll-component');
    if (el) { el.scrollTop = el.scrollHeight; }
}
"""
# Stop scrolling for more results after this many consecutive scrolls produce
# no new cards (i.e. we've reached the end of the list).
_MAX_STALE_SCROLLS = 3


class AutoTraderScraper(Scraper):
    source_name = "autotrader"

    def __init__(self, scraping_config: dict) -> None:
        super().__init__(scraping_config)
        self._playwright = None
        self._browser = None
        self._context = None

    def fetch_listings(self, filters: dict, max_pages: int) -> Iterator[Listing]:
        self._ensure_browser()
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

        url = self.build_search_url(filters, page=1)
        page = self._context.new_page()
        seen_ids: set[str] = set()
        try:
            try:
                page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
                page.wait_for_selector(CARD_SELECTOR, timeout=RENDER_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                logger.warning(
                    "autotrader: no listing cards appeared within %dms for %s "
                    "(page may show a cookie-consent/bot-check wall, or "
                    "CARD_SELECTOR in autotrader.py needs updating)",
                    RENDER_TIMEOUT_MS, url,
                )
                return
            except PlaywrightError as e:
                logger.error("autotrader: failed to load %s: %s", url, e)
                return

            stale_scrolls = 0
            for batch_num in range(1, max_pages + 1):
                soup = BeautifulSoup(page.content(), "lxml")
                batch = list(self.parse_results_page(soup))
                new_listings = [l for l in batch if l.external_id not in seen_ids]

                if not batch and batch_num == 1:
                    logger.warning(
                        "autotrader: 0 listings parsed from %s. The site's markup "
                        "may have changed; check the selectors in autotrader.py.",
                        url,
                    )

                seen_ids.update(l.external_id for l in new_listings)
                yield from new_listings

                if not new_listings:
                    stale_scrolls += 1
                    if stale_scrolls >= _MAX_STALE_SCROLLS:
                        break
                else:
                    stale_scrolls = 0

                if batch_num < max_pages:
                    try:
                        page.evaluate(_SCROLL_JS)
                        page.wait_for_timeout(self.request_delay * 1000)
                    except PlaywrightError as e:
                        logger.warning("autotrader: scroll attempt failed: %s", e)
                        break
        finally:
            page.close()

    def _ensure_browser(self) -> None:
        if self._browser is not None:
            return
        from playwright.sync_api import sync_playwright

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent=self.session.headers.get("User-Agent"),
        )

    def close(self) -> None:
        super().close()
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._browser is not None:
            self._browser.close()
            self._browser = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None

    def build_search_url(self, filters: dict, page: int) -> str:
        params = {"sort": "relevance", "page": page}
        if filters.get("make"):
            params["make"] = filters["make"]
        if filters.get("model"):
            params["model"] = filters["model"]
        if filters.get("postcode"):
            params["postcode"] = filters["postcode"]
        if filters.get("radius_miles"):
            params["radius"] = filters["radius_miles"]
        if filters.get("min_price"):
            params["price-from"] = filters["min_price"]
        if filters.get("max_price"):
            params["price-to"] = filters["max_price"]
        if filters.get("min_year"):
            params["year-from"] = filters["min_year"]
        if filters.get("max_year"):
            params["year-to"] = filters["max_year"]
        if filters.get("max_mileage"):
            params["maximum-mileage"] = filters["max_mileage"]
        if filters.get("fuel_type"):
            params["fuel-type"] = filters["fuel_type"]
        if filters.get("transmission"):
            params["transmission"] = filters["transmission"]
        return f"{BASE_URL}?{urlencode(params)}"

    def parse_results_page(self, soup: BeautifulSoup) -> Iterator[Listing]:
        for card in soup.select(CARD_SELECTOR):
            title_el = card.select_one(TITLE_SELECTOR)
            if not title_el or not title_el.get("href"):
                continue

            href = title_el["href"]
            url = href if href.startswith("http") else f"https://www.autotrader.co.uk{href}"
            external_id = card.get("data-advertid") or extract_id_from_url(url)
            if not external_id:
                continue

            # AutoTrader nests a visually-hidden a11y <span> inside the title
            # link containing the trim + price as extra text (e.g. "1.5 118i
            # Sport Euro 6 (s/s) 5dr, £5,000") -- get_text() would append that
            # straight onto the title with no separator. Only take the link's
            # own direct text, not its descendants' text.
            title = "".join(title_el.find_all(string=True, recursive=False)).strip()
            subtitle_el = card.select_one(SUBTITLE_SELECTOR)
            subtitle = subtitle_el.get_text(strip=True) if subtitle_el else ""

            badge_texts: list[str] = []
            badge_map: dict[str, str] = {}
            badges_container = card.select_one(BADGES_CONTAINER_SELECTOR)
            if badges_container:
                for li in badges_container.select("li"):
                    text = li.get_text(strip=True)
                    badge_texts.append(text)
                    testid = li.get("data-testid")
                    if testid:
                        badge_map[testid] = text

            price = _find_price(card)

            year = (
                parse_year(badge_map.get("registered_year"))
                or parse_year(title)
                or next((parse_year(t) for t in badge_texts if parse_year(t)), None)
            )
            mileage = parse_mileage(badge_map.get("mileage")) or next(
                (parse_mileage(t) for t in badge_texts if parse_mileage(t)), None
            )
            fuel_type = parse_fuel_type(badge_texts) or parse_fuel_type([subtitle])
            transmission = parse_transmission(badge_texts) or parse_transmission([subtitle])

            location_el = card.select_one(LOCATION_SELECTOR)
            location = None
            if location_el:
                # The location span wraps an SVG pin icon with its own
                # <title>text</title> (e.g. "Dealer location"); strip it so it
                # doesn't get prepended to the actual place name.
                for svg in location_el.find_all("svg"):
                    svg.decompose()
                location = location_el.get_text(strip=True)

            make, model = _split_make_model(title)

            yield Listing(
                source=self.source_name,
                external_id=external_id,
                url=url,
                title=title,
                price=price,
                make=make,
                model=model,
                year=year,
                mileage=mileage,
                location=location,
                fuel_type=fuel_type,
                transmission=transmission,
            )


def _find_price(card) -> Optional[int]:
    for text_node in card.find_all(string=_PRICE_TEXT_RE):
        return parse_price(str(text_node))
    return None


def _split_make_model(title: str) -> tuple[str | None, str | None]:
    """AutoTrader titles are typically '<Make> <Model> <trim/spec...>'."""
    parts = title.split()
    if len(parts) < 2:
        return None, None
    make, model = parts[0], parts[1]
    # Handle multi-word model families like "1 Series" (BMW) or "C Class"
    # (Mercedes) so e.g. "BMW 1 Series 118i Sport" doesn't get truncated to
    # model="1".
    if len(parts) > 2 and parts[2].lower() in ("series", "class"):
        model = f"{model} {parts[2]}"
    return make, model
