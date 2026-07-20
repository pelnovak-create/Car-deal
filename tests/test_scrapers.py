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
<li id="id-202606243587365" data-testid="id-202606243587365" data-advertid="202606243587365" class="sc-mddoqs-1 eqaHHR">
  <div class="sc-c2svtm-0 jEcZwS">
    <div data-testid="advertCard-0" class="sc-c2svtm-4 iHkBkv">
      <div class="sc-1mc7cl3-1 GevjZ">
        <a data-testid="search-listing-title" href="/car-details/202606243587365?sort=relevance&amp;searchId=e9d0201a-9c5d-4040-a449-b99aad225d3a" class="sc-1mc7cl3-3 iRbWGr">BMW 1 Series<span class="uKe8ha__visuallyhidden">1.5 118i Sport Euro 6 (s/s) 5dr, £5,000</span></a>
        <p data-testid="search-listing-subtitle" aria-hidden="true" class="sc-1mc7cl3-4 iLMXfY">1.5 118i Sport Euro 6 (s/s) 5dr</p>
      </div>
      <ul data-testid="badges-container" class="sc-1mc7cl3-6 hVhNli">
        <li data-testid="mileage" class="sc-1n64n0d-11 csblGw">63,342 miles</li>
        <li data-testid="registered_year" class="sc-1n64n0d-11 csblGw">2016 (66 reg)</li>
      </ul>
      <span class="sc-1n64n0d-8 sc-1mc7cl3-14 gmXvZp gNFmcp">£5,000</span>
      <span data-testid="search-listing-location" class="sc-1n64n0d-9 hrQIN">
        <svg xmlns="http://www.w3.org/2000/svg" data-testid="map pin"><title>Dealer location</title><path d="M0 0"></path></svg>
        <span class="sc-m0lx8i-1 iKGWFY">Glasgow (15 miles)</span>
      </span>
    </div>
  </div>
</li>
<li id="id-202606249999999" data-testid="id-202606249999999" data-advertid="202606249999999" class="sc-mddoqs-1 eqaHHR">
  <div class="sc-c2svtm-0 jEcZwS">
    <div data-testid="advertCard-1" class="sc-c2svtm-4 iHkBkv">
      <div class="sc-1mc7cl3-1 GevjZ">
        <a data-testid="search-listing-title" href="/car-details/202606249999999?sort=relevance" class="sc-1mc7cl3-3 iRbWGr">Ford Fiesta<span class="uKe8ha__visuallyhidden">1.0 Zetec Petrol Manual 5dr, £7,500</span></a>
        <p data-testid="search-listing-subtitle" aria-hidden="true" class="sc-1mc7cl3-4 iLMXfY">1.0 Zetec Petrol Manual 5dr</p>
      </div>
      <ul data-testid="badges-container" class="sc-1mc7cl3-6 hVhNli">
        <li data-testid="mileage" class="sc-1n64n0d-11 csblGw">30,000 miles</li>
        <li data-testid="registered_year" class="sc-1n64n0d-11 csblGw">2018 (18 reg)</li>
      </ul>
      <span class="sc-1n64n0d-8 sc-1mc7cl3-14 gmXvZp gNFmcp">£7,500</span>
      <span data-testid="search-listing-location" class="sc-1n64n0d-9 hrQIN">
        <svg xmlns="http://www.w3.org/2000/svg" data-testid="map pin"><title>Dealer location</title><path d="M0 0"></path></svg>
        <span class="sc-m0lx8i-1 iKGWFY">Bristol (5 miles)</span>
      </span>
    </div>
  </div>
</li>
</body></html>
"""

GUMTREE_HTML = """
<html><body>
<div data-q="search-result">
  <a data-q="search-result-anchor" href="/p/cars/volkswagen-golf/1234567890">
    <div data-q="tile-title">Volkswagen Golf 2.0 GTD</div>
  </a>
  <div data-q="tile-price">£12,250</div>
  <div data-q="tile-attributes">
    <span>2020</span>
    <span>38,000 miles</span>
    <span>Diesel</span>
    <span>Manual</span>
  </div>
  <div data-q="tile-location">Manchester</div>
</div>
</body></html>
"""

NO_MATCHING_MARKUP_HTML = "<html><body><div class='completely-redesigned-page'>No cards here</div></body></html>"


def test_autotrader_parses_known_markup():
    scraper = AutoTraderScraper(SCRAPING_CONFIG)
    soup = BeautifulSoup(AUTOTRADER_HTML, "lxml")
    listings = list(scraper.parse_results_page(soup))

    assert len(listings) == 2
    bmw = listings[0]
    assert bmw.external_id == "202606243587365"
    assert bmw.price == 5000
    assert bmw.year == 2016
    assert bmw.mileage == 63342
    assert bmw.location == "Glasgow (15 miles)"
    assert bmw.make == "BMW"
    assert bmw.model == "1 Series"
    assert bmw.title == "BMW 1 Series"
    assert bmw.source == "autotrader"
    # This card's subtitle doesn't mention fuel/transmission (real AutoTrader
    # private-seller tiles often don't) -- must not crash, and must not pick
    # up noise from the hidden a11y span or the location pin's SVG <title>.
    assert bmw.fuel_type is None
    assert bmw.transmission is None

    fiesta = listings[1]
    assert fiesta.external_id == "202606249999999"
    assert fiesta.price == 7500
    assert fiesta.mileage == 30000
    assert fiesta.year == 2018
    assert fiesta.location == "Bristol (5 miles)"
    assert fiesta.make == "Ford"
    assert fiesta.model == "Fiesta"
    assert fiesta.fuel_type == "Petrol"
    assert fiesta.transmission == "Manual"


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
