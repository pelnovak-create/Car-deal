import os

import pytest

from car_deal_agent.config import ConfigError, load_config


MINIMAL_CONFIG = """
filters:
  make: "Volkswagen"
  model: "Golf"
"""

EMPTY_FILTERS_CONFIG = """
filters:
  max_price: 6000
"""


def write_config(tmp_path, content):
    path = tmp_path / "config.yaml"
    path.write_text(content)
    return str(path)


def test_loads_minimal_config_with_defaults(tmp_path):
    path = write_config(tmp_path, MINIMAL_CONFIG)
    config = load_config(path)
    assert config["filters"]["make"] == "Volkswagen"
    assert config["sources"]["autotrader"]["enabled"] is True
    assert config["pricing"]["deal_threshold_pct"] == 15.0
    assert config["notifications"]["backends"] == ["console"]


def test_make_and_model_are_optional(tmp_path):
    """Leaving make/model unset means 'any make/any model'."""
    path = write_config(tmp_path, EMPTY_FILTERS_CONFIG)
    config = load_config(path)
    assert config["filters"]["make"] is None
    assert config["filters"]["model"] is None
    assert config["filters"]["max_price"] == 6000


def test_missing_file_raises():
    with pytest.raises(ConfigError):
        load_config("/nonexistent/config.yaml")


def test_all_sources_disabled_raises(tmp_path):
    content = MINIMAL_CONFIG + """
sources:
  autotrader:
    enabled: false
  gumtree:
    enabled: false
"""
    path = write_config(tmp_path, content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_email_backend_requires_credentials(tmp_path):
    content = MINIMAL_CONFIG + """
notifications:
  backends:
    - email
"""
    path = write_config(tmp_path, content)
    with pytest.raises(ConfigError):
        load_config(path)


def test_env_var_expansion(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "abc123")
    content = MINIMAL_CONFIG + """
notifications:
  backends:
    - telegram
  telegram:
    bot_token: "${TEST_BOT_TOKEN}"
    chat_id: "42"
"""
    path = write_config(tmp_path, content)
    config = load_config(path)
    assert config["notifications"]["telegram"]["bot_token"] == "abc123"
