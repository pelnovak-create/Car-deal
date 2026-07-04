from bs4 import BeautifulSoup

from car_deal_agent.scrapers.autotrader import AutoTraderScraper
from car_deal_agent.scrapers.gumtree import GumtreeScraper

SCRAPING_CONFIG = {
    "request_delay_seconds": 0,
    "timeout_seconds": 5,
    "user_agent": "test-agent",
}

AUTOTRADER_HTML = """
<html><body>
<article data-testid="advertCard">
  <a data-testid="search-listing-title" href="/car-details/202401011234567">
    Volkswagen Golf 1.6 TDI Match 5dr
  </a>
  <div data-testid="search-listing-price">£11,000</div>
  <ul data-testid="search-listing-specs">
    <li>2019</li>
    <li>45,000 miles</li>
    <li>Diesel</li>
    <li>Manual</li>
  </ul>
  <span data-testid="search-listing-location">London</span>
</article>
<article data-testid="advertCard">
  <a data-testid="search-listing-title" href="/car-details/202401019999999">
    Ford Fiesta 1.0 Zetec 5dr
  </a>
  <div data-testid="search-listing-price">£7,500</div>
  <ul data-testid="search-listing-specs">
    <li>2018</li>
    <li>30,000 miles</li>
    <li>Petrol</li>
    <li>Manual</li>
  </ul>
  <span data-testid="search-listing-location">Bristol</span>
</article>
</body></html>
"""

GUMTREE_HTML = """
<html><body>
<article class="listing-tile">
  <a class="listing-link" href="/p/cars/volkswagen-golf/1234567890">
    <h2 class="listing-title">Volkswagen Golf 2.0 GTD</h2>
  </a>
  <strong class="listing-price">£12,250</strong>
  <div class="listing-attributes">
    <span>2020</span>
    <span>38,000 miles</span>
    <span>Diesel</span>
    <span>Manual</span>
  </div>
  <span class="listing-location">Manchester</span>
</article>
</body></html>
"""

NO_MATCHING_MARKUP_HTML = "<html><body><div class='completely-redesigned-page'>No cards here</div></body></html>"


def test_autotrader_parses_known_markup():
    scraper = AutoTraderScraper(SCRAPING_CONFIG)
    soup = BeautifulSoup(AUTOTRADER_HTML, "lxml")
    listings = list(scraper.parse_results_page(soup))

    assert len(listings) == 2
    golf = listings[0]
    assert golf.external_id == "202401011234567"
    assert golf.price == 11000
    assert golf.year == 2019
    assert golf.mileage == 45000
    assert golf.fuel_type == "Diesel"
    assert golf.transmission == "Manual"
    assert golf.location == "London"
    assert golf.make == "Volkswagen"
    assert golf.model == "Golf"
    assert golf.source == "autotrader"


def test_autotrader_returns_empty_on_unrecognized_markup():
    scraper = AutoTraderScraper(SCRAPING_CONFIG)
    soup = BeautifulSoup(NO_MATCHING_MARKUP_HTML, "lxml")
    listings = list(scraper.parse_results_page(soup))
    assert listings == []


def test_gumtree_parses_known_markup():
    scraper = GumtreeScraper(SCRAPING_CONFIG)
    soup = BeautifulSoup(GUMTREE_HTML, "lxml")
    listings = list(scraper.parse_results_page(soup))

    assert len(listings) == 1
    golf = listings[0]
    assert golf.external_id == "1234567890"
    assert golf.price == 12250
    assert golf.year == 2020
    assert golf.mileage == 38000
    assert golf.fuel_type == "Diesel"
    assert golf.transmission == "Manual"
    assert golf.location == "Manchester"
    assert golf.source == "gumtree"


def test_gumtree_returns_empty_on_unrecognized_markup():
    scraper = GumtreeScraper(SCRAPING_CONFIG)
    soup = BeautifulSoup(NO_MATCHING_MARKUP_HTML, "lxml")
    listings = list(scraper.parse_results_page(soup))
    assert listings == []


def test_autotrader_build_search_url_includes_filters():
    scraper = AutoTraderScraper(SCRAPING_CONFIG)
    url = scraper.build_search_url(
        {"make": "Volkswagen", "model": "Golf", "max_price": 15000, "postcode": "SW1A 1AA"}, page=2
    )
    assert "make=Volkswagen" in url
    assert "model=Golf" in url
    assert "price-to=15000" in url
    assert "page=2" in url


def test_gumtree_build_search_url_includes_filters():
    scraper = GumtreeScraper(SCRAPING_CONFIG)
    url = scraper.build_search_url({"make": "Volkswagen", "model": "Golf"}, page=1)
    assert "search_category=cars" in url
    assert "Volkswagen" in url
