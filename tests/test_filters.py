from car_deal_agent.filters import apply_filters
from car_deal_agent.models import Listing


def make_listing(**overrides):
    defaults = dict(
        source="autotrader",
        external_id="1",
        url="https://example.com/1",
        title="Volkswagen Golf",
        price=10000,
        make="Volkswagen",
        model="Golf",
        year=2018,
        mileage=40000,
        fuel_type="Diesel",
        transmission="Manual",
    )
    defaults.update(overrides)
    return Listing(**defaults)


def test_matches_all_filters():
    listings = [make_listing()]
    filters = {"make": "Volkswagen", "model": "Golf", "max_price": 12000}
    assert apply_filters(listings, filters) == listings


def test_excludes_wrong_make():
    listings = [make_listing(make="Ford")]
    filters = {"make": "Volkswagen"}
    assert apply_filters(listings, filters) == []


def test_excludes_over_budget():
    listings = [make_listing(price=20000)]
    filters = {"max_price": 12000}
    assert apply_filters(listings, filters) == []


def test_excludes_too_high_mileage():
    listings = [make_listing(mileage=100000)]
    filters = {"max_mileage": 60000}
    assert apply_filters(listings, filters) == []


def test_excludes_year_out_of_range():
    listings = [make_listing(year=2010)]
    filters = {"min_year": 2016, "max_year": 2021}
    assert apply_filters(listings, filters) == []


def test_missing_fields_are_not_excluded():
    listings = [make_listing(mileage=None, year=None)]
    filters = {"max_mileage": 60000, "min_year": 2016}
    assert apply_filters(listings, filters) == listings
