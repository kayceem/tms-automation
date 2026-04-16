"""Lightweight TUI-facing view models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderRow:
    id: str
    ticker: str
    user_id: str
    mode: str
    queue_id: int
    execute: bool
    success: bool
    time: str
    price: float
    limit: float
    quantity: int
    total_cost: float
    cumulative_cost: float
    multi_queue: bool = False
    no_ladder: bool = False
    just_buy: bool = False


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


@dataclass(frozen=True)
class CustomWatchlistRow:
    watch_list_id: str
    watch_list_name: str
    exchange_id: str
    raw: dict


@dataclass(frozen=True)
class WatchlistEntryRow:
    security_code: str
    bid_quantity: str
    bid_price: str
    ask_quantity: str
    ask_price: str
    net_change: str
    percent_change: str
    last_price: str
    last_traded_time: str
    opening_price: str
    high_price: str
    low_price: str
    volume: str
    turnover: str
    raw: dict
