from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
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
# navigation (the SPA needs a moment to fetch and render results client-side;
# this can take noticeably longer from a datacenter/VPS network path than
# from a home connection). Overridable via scraping.render_timeout_seconds.
DEFAULT_RENDER_TIMEOUT_MS = 30_000

# Cookie-consent CMPs can withhold page content (including listing data)
# until consent is recorded -- more likely to trigger for a fresh/datacenter
# IP with no pre-existing consent cookie than for a residential one. These
# are a few common consent-management-platform "accept" button selectors;
# the text-based fallback below catches most others.
_COOKIE_ACCEPT_SELECTORS = [
    "#onetrust-accept-btn-handler",        # OneTrust CMP
    "button[title='Accept All']",           # Quantcast/Sourcepoint CMP
    "button[data-testid='accept-all-cookies']",
    "#truste-consent-button",               # TrustArc
]
_COOKIE_ACCEPT_TEXT_RE = re.compile(
    r"^\s*(accept(\s+all)?(\s+cookies)?|allow\s+all(\s+cookies)?|i\s+accept|agree)\s*$",
    re.IGNORECASE,
)

# Phrases/markers that indicate a genuine bot-detection/CAPTCHA interstitial
# rather than an ordinary cookie banner or a plain markup change -- if we see
# one of these, no amount of selector-fiddling will fix it.
_BOT_CHALLENGE_TEXT_PATTERNS = [
    (re.compile(r"checking your browser", re.I), "Cloudflare 'checking your browser' interstitial"),
    (re.compile(r"just a moment", re.I), "Cloudflare challenge page"),
    (re.compile(r"attention required", re.I), "Cloudflare block page"),
    (re.compile(r"pardon our interruption", re.I), "bot-check interstitial ('Pardon Our Interruption')"),
    (re.compile(r"unusual traffic", re.I), "'unusual traffic' block page"),
    (re.compile(r"verify you are (a )?human", re.I), "human-verification challenge"),
    (re.compile(r"are you a robot", re.I), "robot-verification challenge"),
    (re.compile(r"access denied", re.I), "access-denied block page"),
    (re.compile(r"\bcaptcha\b", re.I), "CAPTCHA challenge"),
]
_BOT_CHALLENGE_IFRAME_HINTS = (
    "recaptcha", "hcaptcha", "captcha-delivery", "px-cdn", "geo.captcha-delivery",
)

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
        self.render_timeout_ms = int(
            scraping_config.get("render_timeout_seconds", DEFAULT_RENDER_TIMEOUT_MS / 1000) * 1000
        )
        # When set, a screenshot + full page HTML are saved here whenever 0
        # listing cards are found, so you can see exactly what the browser
        # rendered (useful for silent bot-detection that serves a stripped
        # page with no visible challenge/banner). Set to null/None to disable.
        debug_dir = scraping_config.get("debug_dir", "debug")
        self.debug_dir = Path(debug_dir) if debug_dir else None

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
            except PlaywrightError as e:
                logger.error("autotrader: failed to load %s: %s", url, e)
                return

            self._dismiss_cookie_banner(page)
            try:
                page.wait_for_selector(CARD_SELECTOR, timeout=self.render_timeout_ms)
            except PlaywrightTimeoutError:
                # Consent banners sometimes render after the initial paint;
                # try once more, then give the page a final chance to catch up.
                if self._dismiss_cookie_banner(page):
                    try:
                        page.wait_for_selector(CARD_SELECTOR, timeout=self.render_timeout_ms)
                    except PlaywrightTimeoutError:
                        pass

            if page.locator(CARD_SELECTOR).count() == 0:
                challenge = self._detect_bot_challenge(page)
                if challenge:
                    logger.error(
                        "autotrader: this looks like a bot-detection/CAPTCHA challenge (%s) "
                        "being served to this IP address for %s -- this is NOT a selector or "
                        "markup issue, and updating autotrader.py will not fix it. You likely "
                        "need a different network path (residential proxy, different egress "
                        "IP) to scrape AutoTrader from here.",
                        challenge, url,
                    )
                else:
                    logger.warning(
                        "autotrader: no listing cards appeared within %dms for %s, even after "
                        "attempting to dismiss a cookie-consent banner and no bot-challenge "
                        "signature was detected. The site's markup may have changed, or this "
                        "network may be getting a silently different page (e.g. bot detection "
                        "with no visible challenge) -- check the selectors against a live "
                        "rendered page, or inspect the debug capture below.",
                        self.render_timeout_ms, url,
                    )
                self._save_debug_artifacts(page, url)
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

    def _save_debug_artifacts(self, page, url: str) -> None:
        """Save a screenshot + the full rendered HTML when 0 listing cards
        are found, so the actual page a headless browser sees from this
        network can be inspected after the fact (e.g. to catch silent bot
        detection that serves a stripped page with no visible challenge)."""
        if self.debug_dir is None:
            return
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            base = self.debug_dir / f"autotrader_{stamp}"
            png_path = base.with_suffix(".png")
            html_path = base.with_suffix(".html")
            page.screenshot(path=str(png_path), full_page=True)
            html_path.write_text(page.content(), encoding="utf-8")
            logger.warning(
                "autotrader: saved debug screenshot to %s and HTML to %s (url: %s)",
                png_path, html_path, url,
            )
        except Exception:
            logger.exception("autotrader: failed to save debug artifacts")

    def _dismiss_cookie_banner(self, page) -> bool:
        """Best-effort dismissal of a cookie-consent banner. Tries the main
        page plus any iframes (some CMPs render the banner in one). Returns
        True if something was clicked."""
        from playwright.sync_api import Error as PlaywrightError

        for frame in page.frames:
            for selector in _COOKIE_ACCEPT_SELECTORS:
                try:
                    frame.locator(selector).first.click(timeout=1000)
                    logger.info("autotrader: dismissed cookie banner via selector %r", selector)
                    page.wait_for_timeout(500)
                    return True
                except PlaywrightError:
                    continue
            for role in ("button", "link"):
                try:
                    frame.get_by_role(role, name=_COOKIE_ACCEPT_TEXT_RE).first.click(timeout=1000)
                    logger.info(
                        "autotrader: dismissed cookie banner via accessible text (role=%s)", role
                    )
                    page.wait_for_timeout(500)
                    return True
                except PlaywrightError:
                    continue
        return False

    def _detect_bot_challenge(self, page) -> Optional[str]:
        """Best-effort detection of a bot-detection/CAPTCHA interstitial, as
        distinct from an ordinary cookie banner or a genuine markup change."""
        try:
            body_text = page.locator("body").inner_text(timeout=2000)
        except Exception:
            body_text = ""
        for pattern, description in _BOT_CHALLENGE_TEXT_PATTERNS:
            if pattern.search(body_text):
                return description
        try:
            for frame in page.frames:
                src = (frame.url or "").lower()
                if any(hint in src for hint in _BOT_CHALLENGE_IFRAME_HINTS):
                    return f"CAPTCHA iframe detected ({frame.url.split('?')[0]})"
        except Exception:
            pass
        return None

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
