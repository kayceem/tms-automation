"""Order-store adapters for the TUI."""

from __future__ import annotations

from pathlib import Path

from tui.models import OrderRow
from utils.order_store import OrderStore


class OrderStoreService:
    """Wrapper over OrderStore that exposes TUI-friendly summaries."""

    def __init__(self, store_path: str | Path = "stores/order_store.json") -> None:
        self.store = OrderStore(str(store_path))

    def list_rows(self) -> list[OrderRow]:
        rows = []
        for order in self.store.list_orders():
            rows.append(
                OrderRow(
                    id=str(order.get("id", "")),
                    ticker=str(order.get("ticker", "")),
                    mode=str(order.get("mode", "")),
                    queue_id=int(order.get("queue_id", 999)),
                    execute=bool(order.get("execute", False)),
                    success=bool(order.get("success", False)),
                    time=str(order.get("time") or ""),
                    price=float(order.get("price", 0)),
                    limit=float(order.get("limit", 0)),
                    multi_queue=bool(order.get("multi_queue", False)),
                )
            )
        return rows

    def get_order(self, order_id: str) -> dict | None:
        return self.store.get_order(order_id)

    def add_order(self, order: dict) -> dict:
        return self.store.add_order(order)

    def update_order(self, order_id: str, order: dict) -> dict:
        return self.store.update_order(order_id, order)

    def remove_order(self, order_id: str) -> dict:
        return self.store.remove_order(order_id)
