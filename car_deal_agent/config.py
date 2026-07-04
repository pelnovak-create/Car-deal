from __future__ import annotations

import copy
import os
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "filters": {
        "make": None,
        "model": None,
        "min_year": None,
        "max_year": None,
        "max_mileage": None,
        "min_price": None,
        "max_price": None,
        "postcode": None,
        "radius_miles": 20,
        "fuel_type": None,
        "transmission": None,
    },
    "sources": {
        "autotrader": {"enabled": True, "max_pages": 3},
        "gumtree": {"enabled": True, "max_pages": 3},
    },
    "pricing": {
        "group_by": "make_model_year",  # or "make_model"
        "deal_threshold_pct": 15.0,
        "min_group_size": 3,
    },
    "notifications": {
        "backends": ["console"],  # console | desktop | email | telegram
        "email": {
            "smtp_host": None,
            "smtp_port": 587,
            "use_tls": True,
            "username": None,
            "password": None,
            "from_addr": None,
            "to_addr": None,
        },
        "telegram": {
            "bot_token": None,
            "chat_id": None,
        },
    },
    "database": {
        "path": "car_deals.db",
    },
    "scraping": {
        "request_delay_seconds": 3.0,
        "timeout_seconds": 15,
        "user_agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
    },
}


class ConfigError(ValueError):
    pass


def _deep_merge(base: dict, overrides: dict) -> dict:
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _expand_env(value: Any) -> Any:
    """Allow config values like '${TELEGRAM_BOT_TOKEN}' to pull from the environment."""
    if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
        return os.environ.get(value[2:-1])
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        raise ConfigError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise ConfigError(f"Config file must contain a mapping at the top level: {path}")
    config = _deep_merge(DEFAULTS, raw)
    config = _expand_env(config)
    validate_config(config)
    return config


def validate_config(config: dict) -> None:
    filters = config.get("filters", {})
    if not filters.get("make"):
        raise ConfigError("filters.make is required")
    if not filters.get("model"):
        raise ConfigError("filters.model is required")

    sources = config.get("sources", {})
    if not any(s.get("enabled") for s in sources.values()):
        raise ConfigError("At least one source under 'sources' must be enabled")

    backends = config.get("notifications", {}).get("backends", [])
    valid_backends = {"console", "desktop", "email", "telegram"}
    unknown = set(backends) - valid_backends
    if unknown:
        raise ConfigError(f"Unknown notification backend(s): {sorted(unknown)}")

    if "email" in backends:
        email = config["notifications"]["email"]
        required = ["smtp_host", "username", "password", "from_addr", "to_addr"]
        missing = [k for k in required if not email.get(k)]
        if missing:
            raise ConfigError(f"notifications.email missing required fields: {missing}")

    if "telegram" in backends:
        tg = config["notifications"]["telegram"]
        missing = [k for k in ("bot_token", "chat_id") if not tg.get(k)]
        if missing:
            raise ConfigError(f"notifications.telegram missing required fields: {missing}")
