from __future__ import annotations

import argparse
import logging
import sys
import time

from car_deal_agent import db
from car_deal_agent.config import ConfigError, load_config
from car_deal_agent.filters import apply_filters
from car_deal_agent.models import ScoredListing
from car_deal_agent.notifier import build_notifier
from car_deal_agent.pricing import MarketPricer
from car_deal_agent.scrapers import SCRAPERS

logger = logging.getLogger("car_deal_agent")


def scrape_all(config: dict):
    listings = []
    for name, scraper_cls in SCRAPERS.items():
        source_config = config["sources"].get(name, {})
        if not source_config.get("enabled"):
            continue
        scraper = scraper_cls(config["scraping"])
        max_pages = source_config.get("max_pages", 3)
        logger.info("Scraping %s (up to %d page(s))...", name, max_pages)
        try:
            source_listings = list(scraper.fetch_listings(config["filters"], max_pages))
        except Exception:
            logger.exception("Scraping %s failed; continuing with other sources", name)
            continue
        logger.info("%s: found %d listing(s) before filtering", name, len(source_listings))
        listings.extend(source_listings)
    return listings


def run_once(config: dict, dry_run: bool = False) -> int:
    """Runs a single scrape+score+notify pass. Returns the number of new good deals found."""
    db.init_db(config["database"]["path"])

    raw_listings = scrape_all(config)
    filtered = apply_filters(raw_listings, config["filters"])
    logger.info("%d listing(s) matched filters after scraping", len(filtered))

    pricer = MarketPricer(
        group_by=config["pricing"]["group_by"],
        deal_threshold_pct=config["pricing"]["deal_threshold_pct"],
        min_group_size=config["pricing"]["min_group_size"],
    )
    scored = pricer.score(filtered)

    new_good_deals: list[ScoredListing] = []
    with db.connect(config["database"]["path"]) as conn:
        for item in scored:
            is_new = db.upsert_scored_listing(conn, item)
            item.is_new = is_new
            if is_new and item.is_good_deal:
                new_good_deals.append(item)

        if new_good_deals and not dry_run:
            notifier = build_notifier(config)
            notifier.send(new_good_deals)
            db.mark_notified(conn, [item.listing.id for item in new_good_deals])
        elif new_good_deals and dry_run:
            logger.info(
                "[dry-run] Would notify about %d good deal(s):", len(new_good_deals)
            )
            for item in new_good_deals:
                logger.info("  %s - £%s (%s)", item.listing.title, item.listing.price, item.listing.url)

    logger.info(
        "Run complete: %d matched, %d new, %d new good deal(s)",
        len(filtered),
        sum(1 for s in scored if s.is_new),
        len(new_good_deals),
    )
    return len(new_good_deals)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Scrape AutoTrader and Gumtree for used car listings, "
        "score them against market price, and notify on good deals."
    )
    parser.add_argument("--config", default="config.yaml", help="Path to config YAML file")
    parser.add_argument(
        "--interval-minutes",
        type=float,
        default=None,
        help="If set, run continuously, sleeping this many minutes between passes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Scrape, score, and log results but don't send notifications",
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Enable debug logging"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        config = load_config(args.config)
    except ConfigError as e:
        logger.error("Config error: %s", e)
        return 1

    if args.interval_minutes:
        logger.info("Starting loop, running every %.1f minute(s). Ctrl+C to stop.", args.interval_minutes)
        while True:
            try:
                run_once(config, dry_run=args.dry_run)
            except Exception:
                logger.exception("Run failed; will retry next interval")
            try:
                time.sleep(args.interval_minutes * 60)
            except KeyboardInterrupt:
                logger.info("Stopped.")
                break
    else:
        run_once(config, dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
