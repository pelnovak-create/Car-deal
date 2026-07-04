from car_deal_agent.scrapers.autotrader import AutoTraderScraper
from car_deal_agent.scrapers.gumtree import GumtreeScraper

SCRAPERS = {
    "autotrader": AutoTraderScraper,
    "gumtree": GumtreeScraper,
}

__all__ = ["AutoTraderScraper", "GumtreeScraper", "SCRAPERS"]
