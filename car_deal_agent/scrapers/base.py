from __future__ import annotations

import logging
import re
import time
from abc import ABC, abstractmethod
from typing import Iterator, Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_MILEAGE_RE = re.compile(r"([\d,]+)\s*miles", re.IGNORECASE)
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_PRICE_RE = re.compile(r"[\d,]+")
# Ordered longest-first so e.g. "plug-in hybrid" matches before the shorter
# "hybrid" when both would otherwise match the same text.
FUEL_TYPES = ("plug-in hybrid", "mild hybrid", "petrol", "diesel", "electric", "hybrid")
TRANSMISSIONS = ("semi-automatic", "manual", "automatic")


class ScraperError(RuntimeError):
    pass


class Scraper(ABC):
    """Base class for a single-source car listing scraper.

    Subclasses are responsible for building the search URL(s) for a page of
    results and for parsing a results page into Listing objects. Rate limiting,
    pagination, and HTTP error handling are handled here so subclasses only
    need to deal with source-specific URL/markup concerns.
    """

    source_name = "base"

    def __init__(self, scraping_config: dict) -> None:
        self.request_delay = scraping_config.get("request_delay_seconds", 3.0)
        self.timeout = scraping_config.get("timeout_seconds", 15)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": scraping_config.get("user_agent", "Mozilla/5.0"),
                "Accept-Language": "en-GB,en;q=0.9",
            }
        )

    def fetch_listings(self, filters: dict, max_pages: int) -> Iterator["Listing"]:  # noqa: F821
        for page in range(1, max_pages + 1):
            url = self.build_search_url(filters, page)
            html = self.fetch_page_html(url)
            if html is None:
                return
            soup = BeautifulSoup(html, "lxml")
            page_listings = list(self.parse_results_page(soup))
            if not page_listings:
                if page == 1:
                    logger.warning(
                        "%s: 0 listings parsed from %s. The site's markup may have "
                        "changed; check the selectors in %s.py.",
                        self.source_name, url, self.source_name,
                    )
                break
            yield from page_listings
            if page < max_pages:
                time.sleep(self.request_delay)

    def fetch_page_html(self, url: str) -> Optional[str]:
        """Return the fully-loaded HTML for a search results page, or None on
        failure. Default implementation is a plain HTTP GET; override this for
        JS-rendered sites that need a real browser to produce their markup."""
        return self._get(url)

    def _get(self, url: str) -> Optional[str]:
        for attempt in range(1, 3):
            try:
                resp = self.session.get(url, timeout=self.timeout)
                if resp.status_code != 200:
                    logger.warning(
                        "%s: got status %s for %s (attempt %d/2). Body snippet: %r",
                        self.source_name, resp.status_code, url, attempt, resp.text[:300],
                    )
                    if attempt < 2:
                        time.sleep(self.request_delay * 3)
                        continue
                    return None
                resp.raise_for_status()
                return resp.text
            except requests.RequestException as e:
                logger.error("%s: request failed for %s: %s", self.source_name, url, e)
                if attempt < 2:
                    time.sleep(self.request_delay * 3)
                    continue
                return None
        return None

    def close(self) -> None:
        """Release any resources (browser processes, etc). No-op by default."""
        self.session.close()

    @abstractmethod
    def build_search_url(self, filters: dict, page: int) -> str: ...

    @abstractmethod
    def parse_results_page(self, soup: BeautifulSoup) -> Iterator["Listing"]:  # noqa: F821
        ...


def parse_price(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    match = _PRICE_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(0).replace(",", ""))
    except ValueError:
        return None


def parse_mileage(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    match = _MILEAGE_RE.search(text)
    if not match:
        return None
    try:
        return int(match.group(1).replace(",", ""))
    except ValueError:
        return None


def parse_year(text: Optional[str]) -> Optional[int]:
    if not text:
        return None
    match = _YEAR_RE.search(text)
    return int(match.group(1)) if match else None


def _find_keyword(texts: list[str], keywords: tuple[str, ...]) -> Optional[str]:
    """Find a keyword as a whole word/phrase within any of the given texts,
    whether the text is a standalone badge (e.g. "Diesel") or a longer
    sentence it's embedded in (e.g. "1.6 TDI Match 5dr Diesel Manual")."""
    for text in texts:
        for keyword in keywords:
            match = re.search(rf"\b{re.escape(keyword)}\b", text, re.IGNORECASE)
            if match:
                return match.group(0)
    return None


def parse_fuel_type(texts: list[str]) -> Optional[str]:
    return _find_keyword(texts, FUEL_TYPES)


def parse_transmission(texts: list[str]) -> Optional[str]:
    return _find_keyword(texts, TRANSMISSIONS)


def extract_id_from_url(url: str) -> Optional[str]:
    """Pull the trailing numeric ad ID out of a listing URL."""
    match = re.search(r"(\d{5,})(?:[/?#]|$)", url)
    return match.group(1) if match else None
