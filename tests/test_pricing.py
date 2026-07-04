from car_deal_agent.models import Listing
from car_deal_agent.pricing import MarketPricer


def make_listing(external_id, price, year=2018, make="Volkswagen", model="Golf", mileage=40000):
    return Listing(
        source="autotrader",
        external_id=external_id,
        url=f"https://example.com/{external_id}",
        title=f"{make} {model}",
        price=price,
        make=make,
        model=model,
        year=year,
        mileage=mileage,
    )


def test_flags_listing_priced_well_below_group_median():
    listings = [
        make_listing("1", 10000),
        make_listing("2", 10500),
        make_listing("3", 9800),
        make_listing("4", 7000),  # well below the ~10k median -> should be flagged
    ]
    pricer = MarketPricer(deal_threshold_pct=15.0, min_group_size=3)
    scored = pricer.score(listings)

    cheap = next(s for s in scored if s.listing.external_id == "4")
    assert cheap.is_good_deal is True
    assert cheap.market_price == 9900  # median of [7000, 9800, 10000, 10500]
    assert cheap.comparable_count == 4


def test_does_not_flag_listing_near_market_price():
    listings = [
        make_listing("1", 10000),
        make_listing("2", 10500),
        make_listing("3", 9800),
        make_listing("4", 9700),
    ]
    pricer = MarketPricer(deal_threshold_pct=15.0, min_group_size=3)
    scored = pricer.score(listings)
    for s in scored:
        assert s.is_good_deal is False


def test_insufficient_comparables_yields_no_market_price():
    listings = [make_listing("1", 5000), make_listing("2", 20000)]
    pricer = MarketPricer(deal_threshold_pct=15.0, min_group_size=3)
    scored = pricer.score(listings)
    for s in scored:
        assert s.market_price is None
        assert s.is_good_deal is False


def test_falls_back_to_make_model_group_when_year_group_too_small():
    listings = [
        make_listing("1", 10000, year=2018),
        make_listing("2", 10500, year=2019),
        make_listing("3", 9800, year=2020),
        make_listing("4", 6000, year=2018),  # only comparable in its own year, but 3+ in make/model
    ]
    pricer = MarketPricer(group_by="make_model_year", deal_threshold_pct=15.0, min_group_size=3)
    scored = pricer.score(listings)
    cheap = next(s for s in scored if s.listing.external_id == "4")
    assert cheap.market_price is not None
    assert cheap.is_good_deal is True


def test_different_make_model_are_not_compared():
    listings = [
        make_listing("1", 30000, make="BMW", model="3 Series"),
        make_listing("2", 31000, make="BMW", model="3 Series"),
        make_listing("3", 29000, make="BMW", model="3 Series"),
        make_listing("4", 5000, make="Ford", model="Fiesta"),
    ]
    pricer = MarketPricer(deal_threshold_pct=15.0, min_group_size=3)
    scored = pricer.score(listings)
    fiesta = next(s for s in scored if s.listing.external_id == "4")
    assert fiesta.market_price is None
