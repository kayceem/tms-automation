"""Config adapters used by the TUI."""

from __future__ import annotations

from pathlib import Path

from utils.config.atrad_config_actions import (
    load_default_trigger_settings,
    reset_atrad_jsession_ids,
    save_default_trigger_settings,
)


class ConfigActionsService:
    """TUI-friendly wrapper around shared config actions."""

    def __init__(self, users_dir: str | Path = "users") -> None:
        self.users_dir = Path(users_dir)

    def load_defaults(self) -> dict:
        return load_default_trigger_settings(self.users_dir)

    def save_defaults(self, values: dict) -> Path:
        result = save_default_trigger_settings(values, self.users_dir)
        return result.path

    def reset_jsession_ids(self) -> list[Path]:
        return [result.path for result in reset_atrad_jsession_ids(self.users_dir)]
