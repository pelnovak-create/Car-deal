from __future__ import annotations

import logging
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
# before parsing rather than parsing the raw HTTP response body. These
# `data-testid` attributes reflect the rendered DOM structure as of last
# review; if `fetch_listings` logs "0 listings parsed", inspect a live,
# *rendered* search results page (browser dev tools, not view-source) and
# update the selectors below (search this file for CARD_SELECTOR etc).
CARD_SELECTOR = "[data-testid='advertCard'], article"
TITLE_SELECTOR = "[data-testid='search-listing-title'], h2 a, h3 a"
PRICE_SELECTOR = "[data-testid='search-listing-price']"
SPECS_SELECTOR = "[data-testid='search-listing-specs'] li, ul li"
LOCATION_SELECTOR = "[data-testid='search-listing-location']"

# How long to wait for listing cards to appear after navigation before giving
# up on a page (the SPA needs a moment to fetch and render results client-side).
RENDER_TIMEOUT_MS = 15_000


class AutoTraderScraper(Scraper):
    source_name = "autotrader"

    def __init__(self, scraping_config: dict) -> None:
        super().__init__(scraping_config)
        self._playwright = None
        self._browser = None
        self._context = None

    def fetch_page_html(self, url: str) -> Optional[str]:
        self._ensure_browser()
        page = self._context.new_page()
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

            page.goto(url, timeout=self.timeout * 1000, wait_until="domcontentloaded")
            try:
                page.wait_for_selector(CARD_SELECTOR, timeout=RENDER_TIMEOUT_MS)
            except PlaywrightTimeoutError:
                logger.warning(
                    "autotrader: no listing cards appeared within %dms for %s "
                    "(page may show a cookie-consent/bot-check wall, or "
                    "CARD_SELECTOR in autotrader.py needs updating)",
                    RENDER_TIMEOUT_MS, url,
                )
            return page.content()
        except PlaywrightError as e:
            logger.error("autotrader: failed to render %s: %s", url, e)
            return None
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
            external_id = extract_id_from_url(url)
            if not external_id:
                continue

            title = title_el.get_text(strip=True)
            price_el = card.select_one(PRICE_SELECTOR)
            price = parse_price(price_el.get_text(strip=True) if price_el else None)

            spec_texts = [el.get_text(strip=True) for el in card.select(SPECS_SELECTOR)]
            year = parse_year(title) or next(
                (parse_year(t) for t in spec_texts if parse_year(t)), None
            )
            mileage = next((parse_mileage(t) for t in spec_texts if parse_mileage(t)), None)
            fuel_type = parse_fuel_type(spec_texts)
            transmission = parse_transmission(spec_texts)

            location_el = card.select_one(LOCATION_SELECTOR)
            location = location_el.get_text(strip=True) if location_el else None

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


def _split_make_model(title: str) -> tuple[str | None, str | None]:
    """AutoTrader titles are typically '<Make> <Model> <trim/spec...>'."""
    parts = title.split()
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]
