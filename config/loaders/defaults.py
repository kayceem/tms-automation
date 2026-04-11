"""Shared default-config helpers for user configuration files."""

from pathlib import Path
from typing import Any, Dict, Iterable, Tuple

from config.loaders.file_utils import load_json_file


DEFAULT_CONFIG_FILENAME = "default.json"
INHERITED_TRIGGER_SETTING_KEYS = (
    "trigger_mode_poll_interval_ms",
    "multi_fetch_poll_interval_ms",
    "trigger_mode_refresh_interval_seconds",
    "trigger_sell_poll_interval_ms",
    "trigger_mode_slow_poll_interval_ms",
    "trigger_mode_requests_per_fetch_user",
)


def apply_inherited_defaults(file_path: str, data: Dict[str, Any], allowed_keys: Iterable[str] = INHERITED_TRIGGER_SETTING_KEYS) -> Tuple[Dict[str, Any], set[str]]:
    """Merge selected fields from sibling default.json when absent in the user file."""
    path = Path(file_path)
    default_path = path.with_name(DEFAULT_CONFIG_FILENAME)
    if not default_path.exists() or default_path.resolve() == path.resolve():
        return data, set()
    defaults = load_json_file(str(default_path), "Default configuration file not found: {file_path}")
    merged = dict(data)
    inherited_keys = set()
    for key in allowed_keys:
        if key not in merged and key in defaults:
            merged[key] = defaults[key]
            inherited_keys.add(key)
    return merged, inherited_keys
