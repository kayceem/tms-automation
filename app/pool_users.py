"""Helpers for resolving pooled users in order-store mode."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from config import ATRADUserConfig
from config.loaders import load_config_by_system


@dataclass(frozen=True)
class UserPool:
    """Loaded pool of same-platform user configs addressable by user_id."""

    users_by_id: dict[str, Any]
    ordered_users: list[Any]
    is_atrad: bool


def load_user_pool(config_paths: list[str]) -> UserPool:
    """Load a same-platform user pool and validate uniqueness/size."""
    if len(config_paths) < 2:
        raise ValueError("--pool-users requires at least 2 user configuration files")

    ordered_users: list[Any] = []
    users_by_id: dict[str, Any] = {}
    seen_paths_by_user_id: dict[str, str] = {}
    first_platform_is_atrad: bool | None = None

    for index, config_path in enumerate(config_paths, start=1):
        config = load_config_by_system(config_path, f"pool user {index}")
        is_atrad = isinstance(config, ATRADUserConfig)
        if first_platform_is_atrad is None:
            first_platform_is_atrad = is_atrad
        elif first_platform_is_atrad != is_atrad:
            raise ValueError("--pool-users must all belong to the same platform (all TMS or all ATRAD)")

        if config.user_id in users_by_id:
            prior_path = seen_paths_by_user_id[config.user_id]
            raise ValueError(
                f"Duplicate pooled user_id '{config.user_id}' found in {prior_path} and {config_path}"
            )

        ordered_users.append(config)
        users_by_id[config.user_id] = config
        seen_paths_by_user_id[config.user_id] = config_path

    return UserPool(
        users_by_id=users_by_id,
        ordered_users=ordered_users,
        is_atrad=bool(first_platform_is_atrad),
    )


def validate_pool_orders(orders: list[dict[str, Any]], pool: UserPool) -> None:
    """Validate that executable orders are compatible with pooled-user execution."""
    for order in orders:
        order_id = str(order.get("id", "unknown"))
        mode = str(order.get("mode", ""))
        user_id = _normalized_user_id(order)

        if not user_id:
            raise ValueError(f"Order '{order_id}' is missing required field 'user_id' for --pool-users mode")
        if user_id not in pool.users_by_id:
            available = ", ".join(sorted(pool.users_by_id))
            raise ValueError(
                f"Order '{order_id}' references unknown pooled user_id '{user_id}'. Available users: {available}"
            )
        if mode == "ipo-sell-buy-trigger":
            raise ValueError("Orders with mode 'ipo-sell-buy-trigger' are incompatible with --pool-users")


def resolve_pool_order_users(pool: UserPool, user_id: str) -> tuple[Any, list[Any]]:
    """Return (main_user, fetch_users) for a pooled order/queue execution."""
    normalized_user_id = user_id.strip()
    main_user = pool.users_by_id[normalized_user_id]
    fetch_users = [user for user in pool.ordered_users if user.user_id != normalized_user_id]
    if not fetch_users:
        raise ValueError(
            f"Pooled order user '{normalized_user_id}' leaves no remaining fetch users. --pool-users requires at least 2 distinct users."
        )
    return main_user, fetch_users


def _normalized_user_id(order: dict[str, Any]) -> str:
    return str(order.get("user_id") or "").strip()
