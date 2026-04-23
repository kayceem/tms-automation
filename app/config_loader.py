"""Configuration loading helpers for the application entrypoint."""

import logging
from typing import Any
from config.loaders import load_config_by_system, load_configs_for_platform
from app.pool_users import UserPool, load_user_pool


logger = logging.getLogger("main")


def load_user_configs_by_paths(config_paths, role_label: str):
    """Load a list of user configs from explicit JSON paths."""
    loaded_configs = []
    if not config_paths:
        return loaded_configs

    logger.info(f"Loading {len(config_paths)} {role_label} configurations")
    for idx, config_path in enumerate(config_paths, 1):
        try:
            loaded_configs.append(load_config_by_system(config_path, f"{role_label} {idx}"))
        except Exception as exc:
            logger.warning(f"Failed to load {role_label} from {config_path}: {exc}")

    if not loaded_configs:
        raise ValueError(f"No valid {role_label} configurations loaded")

    logger.info(f"Total {role_label} users loaded: {len(loaded_configs)}")
    return loaded_configs


def load_just_buy_user_specs(spec_entries: list[Any], role_label: str):
    """Load just-buy user specs from strings or {user, quantity} mappings."""
    loaded_specs = []
    if not spec_entries:
        return loaded_specs

    logger.info(f"Loading {len(spec_entries)} {role_label} configurations")
    for idx, entry in enumerate(spec_entries, 1):
        if isinstance(entry, dict):
            config_path = entry.get("user")
            quantity_override = entry.get("quantity")
        else:
            config_path = entry
            quantity_override = None

        try:
            user_config = load_config_by_system(config_path, f"{role_label} {idx}")
            loaded_specs.append(
                {
                    "user_config": user_config,
                    "quantity_override": quantity_override,
                }
            )
        except Exception as exc:
            logger.warning(f"Failed to load {role_label} from {config_path}: {exc}")

    if not loaded_specs:
        raise ValueError(f"No valid {role_label} configurations loaded")

    logger.info(f"Total {role_label} users loaded: {len(loaded_specs)}")
    return loaded_specs


def load_user_config(args):
    """Load the main user configuration from JSON."""
    if not getattr(args, "user_config", None):
        return None
    logger.info(f"Loading user configuration from {args.user_config}")
    return load_config_by_system(args.user_config, "configuration for user")


def load_pool_user_config(args) -> UserPool | None:
    """Load pooled user configs for order-store execution."""
    if not getattr(args, "pool_users", None):
        return None
    logger.info(f"Loading {len(args.pool_users)} pooled user configurations")
    return load_user_pool(list(args.pool_users))


def load_fetch_user_configs(args):
    """Load optional fetch-user configurations."""
    fetch_user_configs = []
    is_atrad_fetch = args.atrad_fetch if hasattr(args, 'atrad_fetch') else False

    if args.fetch_user:
        logger.info(f"Loading single fetch user configuration from {args.fetch_user}")
        fetch_user_configs = load_configs_for_platform([args.fetch_user], "fetch user", is_atrad_fetch)
    elif args.fetch_users:
        logger.info(f"Loading {len(args.fetch_users)} fetch user configurations")
        for idx, fetch_user_file in enumerate(args.fetch_users, 1):
            try:
                fetch_user_configs.extend(load_configs_for_platform([fetch_user_file], "fetch user", is_atrad_fetch))
            except Exception as exc:
                logger.warning(f"Failed to load fetch user from {fetch_user_file}: {exc}")

        if not fetch_user_configs:
            raise ValueError("No valid fetch user configurations loaded")

    if fetch_user_configs:
        logger.info(f"Total {'ATRAD' if is_atrad_fetch else 'TMS'} fetch users loaded: {len(fetch_user_configs)}")

    return fetch_user_configs, is_atrad_fetch


def load_just_buy_user_configs(args):
    """Load optional just-buy order-user configurations."""
    just_buy_users = getattr(args, "just_buy_users", None) or []
    return load_user_configs_by_paths(just_buy_users, "just-buy user")


def load_trader_config(config_path: str, role: str):
    """Load seller/buyer configuration from JSON."""
    logger.info(f"Loading {role} configuration from {config_path}")
    return load_config_by_system(config_path, f"{role} configuration")
