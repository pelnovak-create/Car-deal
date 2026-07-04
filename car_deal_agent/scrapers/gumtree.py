from __future__ import annotations

import logging
from typing import Iterator
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

BASE_URL = "https://www.gumtree.com/search"

# NOTE ON SELECTORS: like most classifieds sites, Gumtree changes its CSS class
# names periodically. These selectors reflect the site's structure as of last
# review; if `fetch_listings` logs "0 listings parsed", inspect a live search
# results page and update the selectors below.
CARD_SELECTOR = "article, .listing-tile, [data-q='search-result-tile']"
TITLE_LINK_SELECTOR = "a.listing-link, a[href*='/p/']"
PRICE_SELECTOR = ".listing-price, strong.listing-price"
LOCATION_SELECTOR = ".listing-location, [data-q='listing-location']"
ATTRIBUTES_SELECTOR = ".listing-attributes span, .listing-attributes li"


class GumtreeScraper(Scraper):
    source_name = "gumtree"

    def build_search_url(self, filters: dict, page: int) -> str:
        query_parts = [p for p in (filters.get("make"), filters.get("model")) if p]
        params = {
            "search_category": "cars",
            "q": " ".join(query_parts),
            "page": page,
        }
        if filters.get("postcode"):
            params["search_location"] = filters["postcode"]
        if filters.get("radius_miles"):
            params["distance"] = filters["radius_miles"]
        if filters.get("min_price"):
            params["min_price"] = filters["min_price"]
        if filters.get("max_price"):
            params["max_price"] = filters["max_price"]
        return f"{BASE_URL}?{urlencode(params)}"

    def parse_results_page(self, soup: BeautifulSoup) -> Iterator[Listing]:
        for card in soup.select(CARD_SELECTOR):
            title_el = card.select_one(TITLE_LINK_SELECTOR)
            if not title_el or not title_el.get("href"):
                continue

            href = title_el["href"]
            url = href if href.startswith("http") else f"https://www.gumtree.com{href}"
            external_id = extract_id_from_url(url)
            if not external_id:
                continue

            title = title_el.get_text(strip=True)
            if not title:
                continue

            price_el = card.select_one(PRICE_SELECTOR)
            price = parse_price(price_el.get_text(strip=True) if price_el else None)

            attr_texts = [el.get_text(strip=True) for el in card.select(ATTRIBUTES_SELECTOR)]
            card_text = card.get_text(" ", strip=True)
            year = parse_year(title) or next(
                (parse_year(t) for t in attr_texts if parse_year(t)), None
            ) or parse_year(card_text)
            mileage = (
                next((parse_mileage(t) for t in attr_texts if parse_mileage(t)), None)
                or parse_mileage(card_text)
            )
            fuel_type = parse_fuel_type(attr_texts)
            transmission = parse_transmission(attr_texts)

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
    """Gumtree titles are free-text; best-effort assume '<Make> <Model> ...' like AutoTrader."""
    parts = title.split()
    if len(parts) < 2:
        return None, None
    return parts[0], parts[1]
