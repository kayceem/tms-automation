"""Typed application-layer models used by orchestration helpers."""

from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class PlatformBundle:
    """Main client/service pair for a user config."""

    client: Any
    service: Any
    is_atrad: bool


@dataclass(frozen=True)
class ResolvedTicker:
    """Resolved ticker identifiers for orchestration flows."""

    ticker: str
    security_id: int
    exchange_security_id: int
    fetch_id: Any
    symbol: str
    name: Optional[str] = None
    fetch_host: Optional[str] = None
