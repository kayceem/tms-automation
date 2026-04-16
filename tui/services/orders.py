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
        ordered = sorted(
            self.store.list_orders(),
            key=lambda order: (int(order.get("queue_id", 999)), str(order.get("id", ""))),
        )
        rows = []
        cumulative_cost = 0.0
        for order in ordered:
            price = float(order.get("price", 0))
            limit = float(order.get("limit", 0) if order.get("limit") is not None else 0)
            quantity = int(order.get("quantity", 0))
            total_cost = (limit * quantity * 1.1) if limit != 0 else (price * quantity * 1.1)
            cumulative_cost += total_cost
            rows.append(
                OrderRow(
                    id=str(order.get("id", "")),
                    ticker=str(order.get("ticker", "")),
                    user_id=str(order.get("user_id") or ""),
                    mode=str(order.get("mode", "")),
                    queue_id=int(order.get("queue_id", 999)),
                    execute=bool(order.get("execute", False)),
                    success=bool(order.get("success", False)),
                    time=str(order.get("time") or ""),
                    price=price,
                    limit=limit,
                    quantity=quantity,
                    total_cost=total_cost,
                    cumulative_cost=cumulative_cost,
                    multi_queue=bool(order.get("multi_queue", False)),
                    no_ladder=bool(order.get("no_ladder", False)),
                    just_buy=bool(order.get("just_buy", False)),
                )
            )
        return rows

    def refresh_store(self) -> None:
        self.store.refresh()

    def get_order(self, order_id: str) -> dict | None:
        return self.store.get_order(order_id)

    def add_order(self, order: dict) -> dict:
        return self.store.add_order(order)

    def update_order(self, order_id: str, order: dict) -> dict:
        return self.store.update_order(order_id, order)

    def remove_order(self, order_id: str) -> dict:
        return self.store.remove_order(order_id)
