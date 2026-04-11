"""Configuration loading helpers for the application entrypoint."""

import logging

from config.loaders import load_config_by_system, load_configs_for_platform


logger = logging.getLogger("main")


def load_user_config(args):
    """Load the main user configuration from JSON."""
    logger.info(f"Loading user configuration from {args.user_config}")
    return load_config_by_system(args.user_config, "configuration for user")


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


def load_trader_config(config_path: str, role: str):
    """Load seller/buyer configuration from JSON."""
    logger.info(f"Loading {role} configuration from {config_path}")
    return load_config_by_system(config_path, f"{role} configuration")
