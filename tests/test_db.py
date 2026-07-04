import os

from car_deal_agent import db
from car_deal_agent.models import Listing, ScoredListing


def make_scored(external_id="123", price=10000, is_good_deal=False):
    listing = Listing(
        source="autotrader",
        external_id=external_id,
        url=f"https://www.autotrader.co.uk/car-details/{external_id}",
        title="Volkswagen Golf 1.6 TDI",
        price=price,
        make="Volkswagen",
        model="Golf",
        year=2018,
        mileage=40000,
    )
    return ScoredListing(
        listing=listing, market_price=12000, deal_score_pct=16.7, comparable_count=5,
        is_good_deal=is_good_deal,
    )


def test_init_db_creates_file(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    assert os.path.exists(db_path)


def test_upsert_new_listing_is_new(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    scored = make_scored()
    with db.connect(db_path) as conn:
        is_new = db.upsert_scored_listing(conn, scored)
    assert is_new is True


def test_upsert_existing_listing_is_not_new(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    scored = make_scored()
    with db.connect(db_path) as conn:
        db.upsert_scored_listing(conn, scored)
    with db.connect(db_path) as conn:
        is_new = db.upsert_scored_listing(conn, scored)
    assert is_new is False


def test_listing_exists(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    scored = make_scored()
    with db.connect(db_path) as conn:
        assert db.listing_exists(conn, scored.listing.id) is False
        db.upsert_scored_listing(conn, scored)
        assert db.listing_exists(conn, scored.listing.id) is True


def test_mark_notified(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    scored = make_scored()
    with db.connect(db_path) as conn:
        db.upsert_scored_listing(conn, scored)
        db.mark_notified(conn, [scored.listing.id])
        row = db.get_listing(conn, scored.listing.id)
    assert row["notified"] == 1


def test_different_sources_same_external_id_are_distinct(tmp_path):
    db_path = str(tmp_path / "test.db")
    db.init_db(db_path)
    listing_a = make_scored(external_id="999")
    listing_b = make_scored(external_id="999")
    listing_b.listing.source = "gumtree"
    listing_b.listing.url = "https://www.gumtree.com/p/cars/999"
    with db.connect(db_path) as conn:
        is_new_a = db.upsert_scored_listing(conn, listing_a)
        is_new_b = db.upsert_scored_listing(conn, listing_b)
    assert is_new_a is True
    assert is_new_b is True
