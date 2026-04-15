"""Order log adapters used by the TUI."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from itertools import zip_longest
from pathlib import Path


@dataclass(frozen=True)
class OrderLogRow:
    symbol: str
    fetch_time_ms: int
    bid_quantity: str
    bid_price: str
    splits: str
    order_quantity: str
    order_price: str
    fetch_time: str
    end_time: str
    highlight: bool = False


@dataclass(frozen=True)
class OrderLogsPayload:
    symbols: list[str]
    rows_by_symbol: dict[str, list[OrderLogRow]]
    market_counts: dict[str, int]
    completed_counts: dict[str, int]


class OrderLogsService:
    """Read and merge market ticks + completed orders for the order-logs panel."""

    def __init__(self, logs_dir: str | Path = "logs/orders") -> None:
        self.logs_dir = Path(logs_dir)

    def load(self, date: str) -> OrderLogsPayload:
        """Return merged order-log data for the given date."""
        date_dir = self.logs_dir / date
        market = self._read_json_list(date_dir / "market.json")
        completed = self._read_json_list(date_dir / "completed.json")
        market_by_symbol = self._group_by_symbol(market)
        completed_by_symbol = self._group_by_symbol(completed)
        symbols = sorted(completed_by_symbol)

        rows_by_symbol: dict[str, list[OrderLogRow]] = {}
        market_counts: dict[str, int] = {}
        completed_counts: dict[str, int] = {}
        for symbol in symbols:
            market_entries = market_by_symbol.get(symbol, [])
            completed_entries = completed_by_symbol.get(symbol, [])
            rows_by_symbol[symbol] = self._merge_symbol_rows(symbol, market_entries, completed_entries)
            market_counts[symbol] = len(market_entries)
            completed_counts[symbol] = len(completed_entries)
        return OrderLogsPayload(
            symbols=symbols,
            rows_by_symbol=rows_by_symbol,
            market_counts=market_counts,
            completed_counts=completed_counts,
        )

    @staticmethod
    def _read_json_list(path: Path) -> list[dict]:
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return []
        return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []

    @staticmethod
    def _group_by_symbol(entries: list[dict]) -> dict[str, list[dict]]:
        grouped: dict[str, list[dict]] = {}
        for entry in entries:
            sym = str(entry.get("symbol", "")).strip()
            if not sym:
                continue
            grouped.setdefault(sym, []).append(entry)
        return grouped

    def _merge_symbol_rows(
        self,
        symbol: str,
        market_entries: list[dict],
        completed_entries: list[dict],
    ) -> list[OrderLogRow]:
        market_by_time = self._group_by_time(market_entries, "fetched_time_ms")
        completed_by_time = self._group_by_time(completed_entries, "start_time_ms")
        timestamps = sorted(set(market_by_time) | set(completed_by_time))

        merged: list[OrderLogRow] = []
        for timestamp in timestamps:
            market_group = market_by_time.get(timestamp, [])
            completed_group = completed_by_time.get(timestamp, [])
            for market_entry, completed_entry in zip_longest(market_group, completed_group):
                bid_quantity = self._text(market_entry, "qty")
                bid_price = self._text(market_entry, "price")
                splits = self._text(market_entry, "splits")
                order_quantity = self._text(completed_entry, "qty")
                order_price = self._text(completed_entry, "price")
                highlight = self._should_highlight_market_entry(
                    bid_qty=bid_quantity,
                    bid_price=bid_price,
                    completed_entries=completed_entries,
                )
                end_time_ms = self._to_int(completed_entry.get("end_time_ms")) if completed_entry else 0
                merged.append(
                    OrderLogRow(
                        symbol=symbol,
                        fetch_time_ms=timestamp,
                        bid_quantity=bid_quantity,
                        bid_price=bid_price,
                        splits=splits,
                        order_quantity=order_quantity,
                        order_price=order_price,
                        fetch_time=self._fmt_ms(timestamp),
                        end_time=self._fmt_ms(end_time_ms),
                        highlight=highlight,
                    )
                )
        merged.sort(key=lambda row: row.fetch_time_ms)
        return merged

    @staticmethod
    def _group_by_time(entries: list[dict], time_key: str) -> dict[int, list[dict]]:
        grouped: dict[int, list[dict]] = {}
        for entry in entries:
            timestamp = OrderLogsService._to_int(entry.get(time_key))
            grouped.setdefault(timestamp, []).append(entry)
        return grouped

    @staticmethod
    def _should_highlight_market_entry(
        bid_qty: str,
        bid_price: str,
        completed_entries: list[dict],
    ) -> bool:
        if bid_qty == "-" or bid_price == "-":
            return False
        for completed_entry in completed_entries:
            if OrderLogsService._should_highlight(
                bid_qty=bid_qty,
                bid_price=bid_price,
                order_qty=OrderLogsService._text(completed_entry, "qty"),
                order_price=OrderLogsService._text(completed_entry, "price"),
            ):
                return True
        return False

    @staticmethod
    def _should_highlight(bid_qty: str, bid_price: str, order_qty: str, order_price: str) -> bool:
        if not bid_price.strip() or not order_price.strip() or bid_price.strip() != order_price.strip():
            return False
        try:
            bid_qty_int = int(str(bid_qty).replace(",", ""))
            order_qty_int = int(str(order_qty).replace(",", ""))
        except (TypeError, ValueError):
            return False
        last_digit = bid_qty_int % 10
        base = order_qty_int % 10
        targets = {(base + 1) % 10, (base + 2) % 10, base % 10, (base + 5) % 10, (base + 10) % 10}
        return last_digit in targets

    @staticmethod
    def _text(entry: dict | None, key: str) -> str:
        if not entry:
            return "-"
        value = entry.get(key)
        if value in (None, ""):
            return "-"
        return str(value)

    @staticmethod
    def _to_int(value) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        if not ms:
            return "-"
        dt = datetime.fromtimestamp(ms / 1000.0)
        return dt.strftime("%H:%M:%S") + f".{ms % 1000:03d}"
