from __future__ import annotations

from typing import Iterable

from car_deal_agent.models import Listing


def matches_filters(listing: Listing, filters: dict) -> bool:
    """Source-agnostic post-filter applied after scraping, so results are
    consistent even though AutoTrader and Gumtree support different search
    query parameters natively."""
    make = filters.get("make")
    if make and listing.make and listing.make.lower() != make.lower():
        return False

    model = filters.get("model")
    if model and listing.model and listing.model.lower() != model.lower():
        return False

    min_year = filters.get("min_year")
    if min_year and listing.year and listing.year < min_year:
        return False

    max_year = filters.get("max_year")
    if max_year and listing.year and listing.year > max_year:
        return False

    max_mileage = filters.get("max_mileage")
    if max_mileage and listing.mileage and listing.mileage > max_mileage:
        return False

    min_price = filters.get("min_price")
    if min_price and listing.price and listing.price < min_price:
        return False

    max_price = filters.get("max_price")
    if max_price and listing.price and listing.price > max_price:
        return False

    fuel_type = filters.get("fuel_type")
    if fuel_type and listing.fuel_type and listing.fuel_type.lower() != fuel_type.lower():
        return False

    transmission = filters.get("transmission")
    if (
        transmission
        and listing.transmission
        and listing.transmission.lower() != transmission.lower()
    ):
        return False

    return True


def apply_filters(listings: Iterable[Listing], filters: dict) -> list[Listing]:
    return [l for l in listings if matches_filters(l, filters)]
