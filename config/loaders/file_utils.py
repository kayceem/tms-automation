"""Shared JSON file helpers for configuration modules."""

import json
from pathlib import Path
from typing import Any, Dict


def ensure_existing_path(file_path: str, missing_message: str) -> Path:
    """Resolve and validate a configuration file path."""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(missing_message.format(file_path=file_path))
    return path


def load_json_file(file_path: str, missing_message: str) -> Dict[str, Any]:
    """Load a JSON object from disk."""
    path = ensure_existing_path(file_path, missing_message)
    with open(path, "r") as handle:
        return json.load(handle)


def save_json_file(file_path: str, data: Dict[str, Any]) -> None:
    """Persist a JSON object to disk."""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as handle:
        json.dump(data, handle, indent=2)
