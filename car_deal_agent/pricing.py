from __future__ import annotations

import statistics
from collections import defaultdict
from typing import Iterable

from car_deal_agent.models import Listing, ScoredListing


class MarketPricer:
    """Estimates a "fair market price" for each listing by comparing it against
    other currently-scraped listings of the same make/model(/year), then flags
    listings priced well below that estimate as good deals.

    This is intentionally a simple, dependency-free heuristic (median price of
    comparable listings) rather than a call to a paid valuation API. Accuracy
    improves with more comparable listings per group (see min_group_size).
    """

    def __init__(
        self,
        group_by: str = "make_model_year",
        deal_threshold_pct: float = 15.0,
        min_group_size: int = 3,
    ) -> None:
        self.group_by = group_by
        self.deal_threshold_pct = deal_threshold_pct
        self.min_group_size = min_group_size

    def score(self, listings: Iterable[Listing]) -> list[ScoredListing]:
        listings = [l for l in listings if l.price is not None]
        groups: dict[tuple, list[Listing]] = defaultdict(list)
        fallback_groups: dict[tuple, list[Listing]] = defaultdict(list)

        for listing in listings:
            key = listing.group_key(self.group_by)
            if key:
                groups[key].append(listing)
            fallback_key = listing.group_key("make_model")
            if fallback_key:
                fallback_groups[fallback_key].append(listing)

        results = []
        for listing in listings:
            key = listing.group_key(self.group_by)
            comparables = groups.get(key, []) if key else []

            # Fall back to the broader make/model group (ignoring year) if the
            # precise group doesn't have enough listings to be a reliable estimate.
            if len(comparables) < self.min_group_size:
                fallback_key = listing.group_key("make_model")
                comparables = fallback_groups.get(fallback_key, []) if fallback_key else []

            prices = [c.price for c in comparables if c.price is not None]
            comparable_count = len(prices)

            market_price = None
            deal_score_pct = None
            is_good_deal = False

            if comparable_count >= self.min_group_size:
                market_price = statistics.median(prices)
                if market_price > 0:
                    deal_score_pct = (market_price - listing.price) / market_price * 100
                    is_good_deal = deal_score_pct >= self.deal_threshold_pct

            results.append(
                ScoredListing(
                    listing=listing,
                    market_price=market_price,
                    deal_score_pct=deal_score_pct,
                    comparable_count=comparable_count,
                    is_good_deal=is_good_deal,
                )
            )
        return results
