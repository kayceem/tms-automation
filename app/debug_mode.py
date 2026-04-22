"""Debug-mode helpers applied once at startup."""

from __future__ import annotations

import logging
import os
from typing import Any


logger = logging.getLogger("main")


def _is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def debug_mode_enabled() -> bool:
    return _is_truthy(os.getenv("DEBUG"))


def apply_debug_host_overrides(user_config: Any) -> Any:
    """Swap ATRAD host/base URL once during config load when debug mode is enabled."""
    if not debug_mode_enabled():
        return user_config

    atrad_base_url = getattr(user_config, "atrad_base_url", None)
    atrad_host = getattr(user_config, "atrad_host", None)
    debug_base_url = getattr(user_config, "debug_base_url", None) or os.getenv("DEBUG_ATRAD_BASE_URL")
    debug_host = getattr(user_config, "debug_host", None) or os.getenv("DEBUG_ATRAD_HOST")

    if atrad_base_url is None or atrad_host is None:
        return user_config

    if not debug_base_url:
        raise ValueError(
            f"DEBUG=true but no debug ATRAD base URL is configured for user {user_config.user_id}. "
            "Set debug_base_url in the user JSON or DEBUG_ATRAD_BASE_URL in the environment."
        )
    if not debug_host:
        raise ValueError(
            f"DEBUG=true but no debug ATRAD host is configured for user {user_config.user_id}. "
            "Set debug_host in the user JSON or DEBUG_ATRAD_HOST in the environment."
        )

    user_config.atrad_base_url = debug_base_url.rstrip("/")
    user_config.atrad_host = debug_host
    logger.info(
        f"[{user_config.user_id}] DEBUG host override enabled: "
        f"atrad_base_url={user_config.atrad_base_url}, atrad_host={user_config.atrad_host}"
    )
    return user_config
