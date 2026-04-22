"""System-aware configuration loading helpers."""

import logging
from pathlib import Path
from typing import Union

from app.debug_mode import apply_debug_host_overrides
from utils import detect_system_from_config

from config.loaders.defaults import apply_inherited_defaults
from config.loaders.file_utils import load_json_file
from config.models.atrad_user_config import ATRADUserConfig
from config.models.user_config import UserConfig


logger = logging.getLogger("main")

ConfigType = Union[UserConfig, ATRADUserConfig]


def load_config_by_system(config_path: str, role_label: str, is_atrad: bool = False) -> ConfigType:
    """Load a TMS or ATRAD configuration file based on its contents."""
    config_data = load_json_file(config_path, f"Failed to load {role_label} configuration: {{file_path}}")
    config_data, inherited_keys = apply_inherited_defaults(config_path, config_data)

    system_type = detect_system_from_config(config_data) if not is_atrad else "atrad"

    config_cls = ATRADUserConfig if system_type == "atrad" else UserConfig
    user_config = config_cls.from_dict(config_data)
    user_config._config_file_path = str(Path(config_path).resolve())
    user_config._inherited_default_keys = inherited_keys
    user_config = apply_debug_host_overrides(user_config)

    logger.info(f"Loaded {system_type.upper()} {role_label}: {user_config.user_id}")
    return user_config


def load_configs_for_platform(config_paths, role_label: str, is_atrad: bool):
    """Load one or more configs for a known platform."""
    loaded_configs = []
    for idx, config_path in enumerate(config_paths, 1):
        config = load_config_by_system(config_path, f"{role_label} {idx}", is_atrad)
        loaded_configs.append(config)
    return loaded_configs
