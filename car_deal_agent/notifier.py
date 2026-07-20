from __future__ import annotations

import html
import logging
import shutil
import smtplib
import subprocess
from abc import ABC, abstractmethod
from email.mime.text import MIMEText

import requests

from car_deal_agent.models import ScoredListing

logger = logging.getLogger(__name__)


def _format_listing(scored: ScoredListing) -> str:
    l = scored.listing
    price = f"£{l.price:,}" if l.price is not None else "price n/a"
    mileage = f"{l.mileage:,} mi" if l.mileage is not None else "mileage n/a"
    deal = (
        f"{scored.deal_score_pct:.0f}% below market (est. £{scored.market_price:,.0f}, "
        f"{scored.comparable_count} comparables)"
        if scored.deal_score_pct is not None
        else "no market estimate"
    )
    return (
        f"{l.title} — {price}, {mileage}, {l.location or 'location n/a'}\n"
        f"  {deal}\n"
        f"  {l.url}"
    )


def _format_listing_telegram(scored: ScoredListing) -> str:
    """Telegram version of the listing summary: uses HTML formatting (Telegram's
    parse_mode=HTML) to put the %-below-market figure in bold right at the
    top, so it's visible without reading the rest of the message. Target
    shape: "💥 <b>41% below market</b> (est. £2,645, 26 comparables)"."""
    l = scored.listing
    price = f"£{l.price:,}" if l.price is not None else "price n/a"
    mileage = f"{l.mileage:,} mi" if l.mileage is not None else "mileage n/a"
    location = html.escape(l.location) if l.location else "location n/a"
    title = html.escape(l.title)

    if scored.deal_score_pct is not None:
        comparable_word = "comparable" if scored.comparable_count == 1 else "comparables"
        headline = (
            f"💥 <b>{scored.deal_score_pct:.0f}% below market</b> "
            f"(est. £{scored.market_price:,.0f}, {scored.comparable_count} {comparable_word})"
        )
    else:
        headline = "💥 <b>Good deal</b> (no market estimate available)"

    return (
        f"{headline}\n"
        f"<b>{title}</b> — {price}, {mileage}, {location}\n"
        f"{html.escape(l.url)}"
    )


def _chunk_telegram_messages(parts: list[str], limit: int = 4000) -> list[str]:
    """Group whole message parts into <=limit-char chunks without ever
    splitting a part's markup across two messages (Telegram's HTML parser
    would reject a message with an unclosed tag)."""
    messages: list[str] = []
    current = ""
    for part in parts:
        candidate = f"{current}\n\n{part}" if current else part
        if len(candidate) > limit and current:
            messages.append(current)
            current = part
        else:
            current = candidate
    if current:
        messages.append(current)
    return messages


class Notifier(ABC):
    @abstractmethod
    def send(self, listings: list[ScoredListing]) -> None: ...


class ConsoleNotifier(Notifier):
    def send(self, listings: list[ScoredListing]) -> None:
        if not listings:
            return
        print(f"\n=== {len(listings)} good deal(s) found ===")
        for scored in listings:
            print(_format_listing(scored))
            print()


class DesktopNotifier(Notifier):
    """Best-effort local desktop notification via `notify-send` (Linux). Silently
    no-ops if notify-send isn't available, e.g. when running headless/in a container."""

    def send(self, listings: list[ScoredListing]) -> None:
        if not listings:
            return
        if not shutil.which("notify-send"):
            logger.warning("notify-send not found; skipping desktop notification")
            return
        title = f"{len(listings)} good car deal(s) found"
        body = "\n".join(f"{s.listing.title} — £{s.listing.price:,}" for s in listings[:5])
        try:
            subprocess.run(["notify-send", title, body], check=True, timeout=10)
        except (subprocess.SubprocessError, OSError) as e:
            logger.warning("Failed to send desktop notification: %s", e)


class EmailNotifier(Notifier):
    def __init__(self, config: dict) -> None:
        self.smtp_host = config["smtp_host"]
        self.smtp_port = config.get("smtp_port", 587)
        self.use_tls = config.get("use_tls", True)
        self.username = config["username"]
        self.password = config["password"]
        self.from_addr = config["from_addr"]
        self.to_addr = config["to_addr"]

    def send(self, listings: list[ScoredListing]) -> None:
        if not listings:
            return
        subject = f"{len(listings)} good car deal(s) found"
        body = "\n\n".join(_format_listing(s) for s in listings)
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = self.to_addr

        with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
            if self.use_tls:
                server.starttls()
            server.login(self.username, self.password)
            server.sendmail(self.from_addr, [self.to_addr], msg.as_string())


class TelegramNotifier(Notifier):
    def __init__(self, config: dict) -> None:
        self.bot_token = config["bot_token"]
        self.chat_id = config["chat_id"]

    def send(self, listings: list[ScoredListing]) -> None:
        if not listings:
            return
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        header = f"<b>{len(listings)} good car deal(s) found</b>"
        parts = [header] + [_format_listing_telegram(s) for s in listings]
        # Telegram caps message length at 4096 chars; split on listing
        # boundaries (never mid-HTML-tag) if needed.
        for chunk in _chunk_telegram_messages(parts):
            payload = {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            # Log the exact outgoing text (tags and all) right before it's
            # sent, so a formatting regression is visible in the logs rather
            # than only discoverable by eye in the Telegram app.
            logger.debug("Telegram outgoing payload: %r", payload)
            resp = requests.post(url, json=payload, timeout=15)
            resp.raise_for_status()
            logger.debug("Telegram API response [%s]: %s", resp.status_code, resp.text)


class MultiNotifier(Notifier):
    def __init__(self, notifiers: list[Notifier]) -> None:
        self.notifiers = notifiers

    def send(self, listings: list[ScoredListing]) -> None:
        for notifier in self.notifiers:
            try:
                notifier.send(listings)
            except Exception:
                logger.exception("Notifier %s failed", type(notifier).__name__)


def build_notifier(config: dict) -> Notifier:
    notif_config = config["notifications"]
    backends = notif_config.get("backends", ["console"])
    notifiers: list[Notifier] = []
    for backend in backends:
        if backend == "console":
            notifiers.append(ConsoleNotifier())
        elif backend == "desktop":
            notifiers.append(DesktopNotifier())
        elif backend == "email":
            notifiers.append(EmailNotifier(notif_config["email"]))
        elif backend == "telegram":
            notifiers.append(TelegramNotifier(notif_config["telegram"]))
        else:
            raise ValueError(f"Unknown notification backend: {backend}")
    return MultiNotifier(notifiers)
