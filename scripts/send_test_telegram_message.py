"""Fire one real Telegram notification through the actual production code
path (car_deal_agent.notifier.TelegramNotifier) and print the raw API
response, so formatting/delivery issues can be confirmed against the live
API instead of guessed at.

Usage:
    python3 scripts/send_test_telegram_message.py [--config config.yaml]

Requires notifications.telegram.bot_token/chat_id to be set in the config
(directly or via environment variables referenced with ${VAR_NAME}).
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from car_deal_agent.config import load_config
from car_deal_agent.models import Listing, ScoredListing
from car_deal_agent.notifier import TelegramNotifier

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s %(name)s: %(message)s")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="config.yaml")
    args = parser.parse_args()

    config = load_config(args.config)
    telegram_config = config["notifications"]["telegram"]
    if not telegram_config.get("bot_token") or not telegram_config.get("chat_id"):
        print(
            "notifications.telegram.bot_token/chat_id are not set in "
            f"{args.config} -- fill them in (or the env vars they reference) first.",
            file=sys.stderr,
        )
        return 1

    # Deliberately includes '&' and '<...>' in the title to prove escaping
    # survives Telegram's real HTML parser, not just our own regex checks.
    listing = Listing(
        source="test", external_id="0",
        url="https://www.autotrader.co.uk/car-details/0",
        title="Test & <Special> Edition Car", price=1560,
        make="Test", model="Car", year=2016, mileage=63342,
        location="Glasgow (15 miles)",
    )
    scored = ScoredListing(
        listing=listing, market_price=2645, deal_score_pct=41.0,
        comparable_count=26, is_good_deal=True,
    )

    notifier = TelegramNotifier(telegram_config)
    notifier.send([scored])
    print("\nSent -- check your Telegram chat now.")
    print("(The DEBUG lines above show the exact payload sent and the raw API response.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
