from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator, Optional

from car_deal_agent.models import Listing, ScoredListing

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT,
    make TEXT,
    model TEXT,
    year INTEGER,
    price INTEGER,
    mileage INTEGER,
    location TEXT,
    fuel_type TEXT,
    transmission TEXT,
    market_price REAL,
    deal_score_pct REAL,
    is_good_deal INTEGER DEFAULT 0,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    notified INTEGER DEFAULT 0
);
"""


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def listing_exists(conn: sqlite3.Connection, listing_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM listings WHERE id = ?", (listing_id,)).fetchone()
    return row is not None


def upsert_scored_listing(conn: sqlite3.Connection, scored: ScoredListing) -> bool:
    """Insert or update a listing. Returns True if this was a brand-new listing."""
    listing = scored.listing
    now = datetime.now(timezone.utc).isoformat()
    is_new = not listing_exists(conn, listing.id)

    if is_new:
        conn.execute(
            """
            INSERT INTO listings (
                id, source, external_id, url, title, make, model, year, price,
                mileage, location, fuel_type, transmission, market_price,
                deal_score_pct, is_good_deal, first_seen, last_seen, notified
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                listing.id, listing.source, listing.external_id, listing.url, listing.title,
                listing.make, listing.model, listing.year, listing.price, listing.mileage,
                listing.location, listing.fuel_type, listing.transmission,
                scored.market_price, scored.deal_score_pct, int(scored.is_good_deal),
                now, now,
            ),
        )
    else:
        conn.execute(
            """
            UPDATE listings SET
                price = ?, mileage = ?, market_price = ?, deal_score_pct = ?,
                is_good_deal = ?, last_seen = ?
            WHERE id = ?
            """,
            (
                listing.price, listing.mileage, scored.market_price, scored.deal_score_pct,
                int(scored.is_good_deal), now, listing.id,
            ),
        )
    return is_new


def mark_notified(conn: sqlite3.Connection, listing_ids: list[str]) -> None:
    conn.executemany(
        "UPDATE listings SET notified = 1 WHERE id = ?",
        [(lid,) for lid in listing_ids],
    )


def get_listing(conn: sqlite3.Connection, listing_id: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()


def get_historical_prices(
    conn: sqlite3.Connection,
    make: str,
    model: str,
    year: Optional[int] = None,
    exclude_id: Optional[str] = None,
) -> list[int]:
    """Returns past prices seen for a make/model(/year), for market-price estimation."""
    make = (make or "").strip().lower()
    model = (model or "").strip().lower()
    if not make or not model:
        return []

    query = "SELECT price FROM listings WHERE lower(make) = ? AND lower(model) = ? AND price IS NOT NULL"
    params: list = [make, model]
    if year is not None:
        query += " AND year = ?"
        params.append(year)
    if exclude_id is not None:
        query += " AND id != ?"
        params.append(exclude_id)

    rows = conn.execute(query, params).fetchall()
    return [row["price"] for row in rows]
