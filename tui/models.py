"""Lightweight TUI-facing view models."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OrderRow:
    display_key: str
    id: str
    parent_order_id: str
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
    row_kind: str = "order"


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


@dataclass(frozen=True)
class MarketDepthLevelRow:
    splits: str
    quantity: str
    price: str


@dataclass(frozen=True)
class MarketDepthSnapshot:
    symbol: str
    last_updated_time: str
    last_price: str
    net_change: str
    percent_change: str
    volume: str
    total_bids: str
    total_asks: str
    bids: list[MarketDepthLevelRow]
    asks: list[MarketDepthLevelRow]
    ltp_raw: dict
    market_raw: dict


@dataclass(frozen=True)
class SectorSummary:
    index_value: str
    points_change: str
    percent_change: str
    turnover: str
    is_up: bool
    is_down: bool


@dataclass(frozen=True)
class PortfolioHoldingRow:
    security_code: str
    quantity: str
    avg_price: str
    total_cost: str
    last_traded: str
    market_value: str
    net_gain: str
    net_change: str
    cleared_balance: str
    available_quantity: str
    unset_buy: str
    unset_sell: str
    pending_buy: str
    pending_sell: str
    raw: dict


@dataclass(frozen=True)
class MeroSharePortfolioRow:
    script: str
    script_desc: str
    current_balance: str
    last_transaction_price: str
    previous_closing_price: str
    value_as_of_last_transaction_price: str
    value_as_of_previous_closing_price: str
    raw: dict


@dataclass(frozen=True)
class MeroShareWaccRow:
    script: str
    demat: str
    total_quantity: str
    average_buy_rate: str
    total_cost: str
    last_modified_date: str
    raw: dict


@dataclass(frozen=True)
class MeroShareIssueRow:
    script: str
    company_name: str
    share_type: str
    share_group: str
    status: str
    open_date: str
    close_date: str
    raw: dict


@dataclass(frozen=True)
class MeroShareApplicationReportRow:
    script: str
    company_name: str
    share_type: str
    share_group: str
    status: str
    applied_date: str
    applied_units: str
    amount: str
    raw: dict
