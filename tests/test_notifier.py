from unittest.mock import MagicMock, patch

from car_deal_agent.models import Listing, ScoredListing
from car_deal_agent.notifier import (
    TelegramNotifier,
    _chunk_telegram_messages,
    _format_listing_telegram,
)


def make_scored(deal_score_pct=18.0, market_price=12000, title="Volkswagen Golf", url="https://example.com/1"):
    listing = Listing(
        source="autotrader",
        external_id="1",
        url=url,
        title=title,
        price=9840,
        make="Volkswagen",
        model="Golf",
        year=2018,
        mileage=40000,
        location="London",
    )
    return ScoredListing(
        listing=listing, market_price=market_price, deal_score_pct=deal_score_pct,
        comparable_count=5, is_good_deal=True,
    )


def test_format_listing_telegram_bolds_percentage_near_top():
    scored = make_scored(deal_score_pct=18.4)
    text = _format_listing_telegram(scored)
    lines = text.splitlines()
    assert lines[0] == "🔥 <b>18% below market average</b>"
    assert "<b>Volkswagen Golf</b>" in text
    assert "£9,840" in text
    assert "Est. market price: £12,000" in text


def test_format_listing_telegram_handles_missing_market_estimate():
    scored = make_scored(deal_score_pct=None, market_price=None)
    text = _format_listing_telegram(scored)
    assert "<b>Good deal</b>" in text
    assert "No market estimate available" in text
    # must not crash formatting a percentage against None
    assert "None" not in text


def test_format_listing_telegram_escapes_html_special_chars():
    scored = make_scored(title="AT&T Deal <script>", url="https://example.com/x?a=1&b=2")
    text = _format_listing_telegram(scored)
    assert "AT&amp;T Deal &lt;script&gt;" in text
    assert "a=1&amp;b=2" in text
    # raw unescaped chars must not leak into the HTML message
    assert "<script>" not in text


def test_chunk_telegram_messages_keeps_parts_whole():
    parts = ["A" * 3000, "B" * 3000, "C" * 100]
    chunks = _chunk_telegram_messages(parts, limit=4000)
    assert len(chunks) == 2
    assert chunks[0] == "A" * 3000
    assert chunks[1] == ("B" * 3000) + "\n\n" + ("C" * 100)
    for chunk in chunks:
        assert len(chunk) <= 4000 or chunk.count("\n\n") == 0  # never split a part


def test_chunk_telegram_messages_single_chunk_when_small():
    parts = ["header", "listing 1", "listing 2"]
    chunks = _chunk_telegram_messages(parts, limit=4000)
    assert chunks == ["header\n\nlisting 1\n\nlisting 2"]


@patch("car_deal_agent.notifier.requests.post")
def test_telegram_notifier_sends_html_parse_mode(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    notifier = TelegramNotifier({"bot_token": "TOKEN", "chat_id": "42"})
    notifier.send([make_scored(deal_score_pct=18.4)])

    assert mock_post.call_count == 1
    _, kwargs = mock_post.call_args
    payload = kwargs["json"]
    assert payload["chat_id"] == "42"
    assert payload["parse_mode"] == "HTML"
    assert "🔥 <b>18% below market average</b>" in payload["text"]
    assert "https://api.telegram.org/botTOKEN/sendMessage" == mock_post.call_args[0][0]


@patch("car_deal_agent.notifier.requests.post")
def test_telegram_notifier_splits_long_messages(mock_post):
    mock_post.return_value = MagicMock(status_code=200)
    notifier = TelegramNotifier({"bot_token": "TOKEN", "chat_id": "42"})
    many_listings = [
        make_scored(title=f"Car number {i}" + "x" * 500, url=f"https://example.com/{i}")
        for i in range(10)
    ]
    notifier.send(many_listings)
    assert mock_post.call_count > 1
    for _, kwargs in mock_post.call_args_list:
        assert len(kwargs["json"]["text"]) <= 4000


@patch("car_deal_agent.notifier.requests.post")
def test_telegram_notifier_noop_on_empty_listings(mock_post):
    notifier = TelegramNotifier({"bot_token": "TOKEN", "chat_id": "42"})
    notifier.send([])
    mock_post.assert_not_called()
