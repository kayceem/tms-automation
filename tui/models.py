"""Lightweight TUI-facing view models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderRow:
    id: str
    ticker: str
    mode: str
    queue_id: int
    execute: bool
    success: bool
    time: str
    price: float
    limit: float
    multi_queue: bool = False


@dataclass(frozen=True)
class OrderBookRow:
    client_order_id: str
    exchange_order_id: str
    security_code: str
    action: str
    quantity: str
    filled_quantity: str
    remainder: str
    price: str
    amount: str
    order_status: str
    order_time: str
    last_updated_time: str
    raw: dict
