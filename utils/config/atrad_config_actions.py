"""Reusable ATRAD user-config actions for CLI and TUI workflows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable

from config.loaders.defaults import (
    DEFAULT_CONFIG_FILENAME,
    INHERITED_TRIGGER_SETTING_KEYS,
)
from config.loaders.file_utils import save_json_file


TRIGGER_DEFAULT_KEYS = (
    "trigger_mode_poll_interval_ms",
    "multi_fetch_poll_interval_ms",
    "trigger_mode_refresh_interval_seconds",
    "trigger_sell_poll_interval_ms",
    "trigger_mode_slow_poll_interval_ms",
    "trigger_mode_requests_per_fetch_user",
    "trigger_mode_parallel_fetch_enabled",
    "trigger_mode_parallel_spawn_interval_ms",
    "trigger_mode_parallel_cycle_timeout_ms",
    "trigger_mode_parallel_wait",
)

ALLOWED_DEFAULT_KEYS = frozenset(TRIGGER_DEFAULT_KEYS)
BOOLEAN_DEFAULT_KEYS = frozenset(
    {
        "trigger_mode_parallel_fetch_enabled",
        "trigger_mode_parallel_wait",
    }
)


@dataclass(frozen=True)
class ActionResult:
    """Outcome for a single updated file."""

    path: Path
    details: str


def get_project_root() -> Path:
    """Return the repository root for config actions."""
    return Path(__file__).resolve().parents[2]


def get_users_dir(users_dir: str | Path | None = None) -> Path:
    """Resolve the users directory."""
    return Path(users_dir) if users_dir is not None else get_project_root() / "users"


def _load_json(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def iter_atrad_user_paths(users_dir: str | Path | None = None) -> list[Path]:
    """
    Find ATRAD user config files.

    Files are selected by filename compatibility first (`atrad_user*.json`) and then by
    ATRAD-shaped content for any additional JSON files in the directory.
    """
    root = get_users_dir(users_dir)
    if not root.exists():
        return []

    paths: dict[Path, None] = {}
    for path in sorted(root.glob("atrad_user*.json")):
        if path.name != DEFAULT_CONFIG_FILENAME:
            paths[path] = None

    for path in sorted(root.glob("*.json")):
        if path.name == DEFAULT_CONFIG_FILENAME or path in paths:
            continue
        try:
            payload = _load_json(path)
        except (OSError, json.JSONDecodeError):
            continue
        if payload.get("system") == "atrad" or "atrad_base_url" in payload:
            paths[path] = None

    return list(paths)


def reset_atrad_jsession_ids(users_dir: str | Path | None = None) -> list[ActionResult]:
    """Reset saved JSESSIONID values for all ATRAD user config files."""
    results: list[ActionResult] = []
    for path in iter_atrad_user_paths(users_dir):
        payload = _load_json(path)
        cookies = payload.setdefault("_cookies", {})
        cookies["JSESSIONID"] = ""
        save_json_file(str(path), payload)
        results.append(ActionResult(path=path, details="JSESSIONID reset"))
    return results


def load_default_trigger_settings(users_dir: str | Path | None = None) -> Dict[str, Any]:
    """Load supported trigger defaults from `users/default.json`."""
    default_path = get_users_dir(users_dir) / DEFAULT_CONFIG_FILENAME
    if not default_path.exists():
        return {}
    payload = _load_json(default_path)
    return {
        key: payload[key]
        for key in INHERITED_TRIGGER_SETTING_KEYS
        if key in payload
    }


def _validate_default_values(values: Dict[str, Any]) -> Dict[str, int]:
    validated: Dict[str, Any] = {}
    for key, value in values.items():
        if key not in ALLOWED_DEFAULT_KEYS:
            raise ValueError(
                f"Unsupported default key '{key}'. "
                f"Allowed keys: {', '.join(sorted(ALLOWED_DEFAULT_KEYS))}"
            )
        if key in BOOLEAN_DEFAULT_KEYS:
            if isinstance(value, bool):
                validated[key] = value
                continue
            normalized = str(value).strip().lower()
            if normalized in {"true", "1", "yes", "on"}:
                validated[key] = True
                continue
            if normalized in {"false", "0", "no", "off"}:
                validated[key] = False
                continue
            raise ValueError(f"Value for '{key}' must be a boolean")
        try:
            numeric_value = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Value for '{key}' must be an integer") from exc
        if numeric_value <= 0:
            raise ValueError(f"Value for '{key}' must be greater than 0")
        validated[key] = numeric_value
    return validated


def save_default_trigger_settings(
    values: Dict[str, Any],
    users_dir: str | Path | None = None,
) -> ActionResult:
    """Create or update `users/default.json` with supported inherited trigger defaults."""
    validated_values = _validate_default_values(values)
    default_path = get_users_dir(users_dir) / DEFAULT_CONFIG_FILENAME
    payload = _load_json(default_path) if default_path.exists() else {}
    payload.update(validated_values)
    save_json_file(str(default_path), payload)
    updated_keys = ", ".join(sorted(validated_values))
    return ActionResult(path=default_path, details=f"Updated {updated_keys}")


def set_atrad_numeric_key(
    key: str,
    value: Any,
    users_dir: str | Path | None = None,
) -> list[ActionResult]:
    """
    Set a supported numeric key directly on ATRAD user files.

    This remains available for the existing CLI workflow even though the new TUI edits
    `default.json` instead of every ATRAD user file.
    """
    validated = _validate_default_values({key: value})
    results: list[ActionResult] = []
    for path in iter_atrad_user_paths(users_dir):
        payload = _load_json(path)
        old_value = payload.get(key, "not set")
        payload[key] = validated[key]
        save_json_file(str(path), payload)
        results.append(
            ActionResult(
                path=path,
                details=f"{key} = {validated[key]} (was: {old_value})",
            )
        )
    return results
