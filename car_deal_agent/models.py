from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Listing:
    """A single normalized car listing, regardless of source site."""

    source: str
    external_id: str
    url: str
    title: str
    price: Optional[int] = None
    make: Optional[str] = None
    model: Optional[str] = None
    year: Optional[int] = None
    mileage: Optional[int] = None
    location: Optional[str] = None
    fuel_type: Optional[str] = None
    transmission: Optional[str] = None
    image_url: Optional[str] = None
    scraped_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def id(self) -> str:
        """Stable dedupe key, unique per source."""
        return f"{self.source}:{self.external_id}"

    def group_key(self, level: str = "make_model_year") -> Optional[tuple]:
        """Key used to bucket comparable listings for market-price estimation."""
        make = (self.make or "").strip().lower()
        model = (self.model or "").strip().lower()
        if not make or not model:
            return None
        if level == "make_model_year" and self.year:
            return (make, model, self.year)
        if level == "make_model":
            return (make, model)
        return None


@dataclass
class ScoredListing:
    """A Listing plus the market-price comparison results."""

    listing: Listing
    market_price: Optional[float] = None
    deal_score_pct: Optional[float] = None
    comparable_count: int = 0
    is_good_deal: bool = False
    is_new: bool = True
