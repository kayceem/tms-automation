"""Append-only JSON logs for market details and completed orders."""

from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterable

_LOCK = threading.Lock()
_BASE_DIR = Path("logs") / "orders"


def _path_for(name: str) -> Path:
    return _BASE_DIR / datetime.now().strftime("%Y-%m-%d") / f"{name}.json"


def append_trade_log(name: str, entries: Iterable[dict]) -> Path | None:
    items = [e for e in entries if e]
    if not items:
        return None
    path = _path_for(name)
    with _LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        existing: list = []
        if path.exists():
            try:
                loaded = json.loads(path.read_text())
                if isinstance(loaded, list):
                    existing = loaded
            except (json.JSONDecodeError, OSError):
                existing = []
        existing.extend(items)
        path.write_text(json.dumps(existing, indent=2))
    return path
