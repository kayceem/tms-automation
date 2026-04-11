"""Shared dispatch helpers for order-service trigger flows."""

from typing import Any, List, Optional


def normalize_fetch_clients(fetch_client: Optional[Any], fetch_clients: Optional[List[Any]], mode_label: str) -> List[Any]:
    """Normalize trigger-mode fetch client inputs to a list."""
    if fetch_clients:
        return fetch_clients
    if fetch_client:
        return [fetch_client]
    raise ValueError(f"fetch_client or fetch_clients is required for {mode_label}")


def select_trigger_sell_client(fetch_client: Optional[Any], fetch_clients: Optional[List[Any]]) -> Any:
    """Select the single fetch client used by trigger-sell flows."""
    normalized = normalize_fetch_clients(fetch_client, fetch_clients, "trigger sell mode")
    return normalized[0]


def resolve_fetch_security_id(fetch_id: Optional[int], fallback: Any) -> Any:
    """Use host-specific fetch_id when available, otherwise fall back."""
    return fetch_id if fetch_id is not None else fallback
