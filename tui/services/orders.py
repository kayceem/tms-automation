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
            total_cost = (limit * quantity * 1.15) if limit != 0 else (price * quantity * 1.15)
            cumulative_cost += total_cost
            order_id = str(order.get("id", ""))
            rows.append(
                OrderRow(
                    display_key=order_id,
                    id=order_id,
                    parent_order_id=order_id,
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
            for index, (jb_user_id, jb_quantity) in enumerate(self._iter_just_buy_users(order), start=1):
                jb_cost = price * jb_quantity * 1.15
                rows.append(
                    OrderRow(
                        display_key=f"{order_id}::jb:{index}",
                        id=order_id,
                        parent_order_id=order_id,
                        ticker="",
                        user_id=jb_user_id,
                        mode="just-buy-user",
                        queue_id=int(order.get("queue_id", 999)),
                        execute=False,
                        success=False,
                        time="",
                        price=price,
                        limit=0.0,
                        quantity=jb_quantity,
                        total_cost=jb_cost,
                        cumulative_cost=cumulative_cost,
                        row_kind="just_buy_user",
                    )
                )
        return rows

    @staticmethod
    def _iter_just_buy_users(order: dict):
        fallback_quantity = int(order.get("quantity", 0))
        for entry in order.get("just_buy_users") or []:
            if isinstance(entry, dict):
                user_path = str(entry.get("user") or "").strip()
                if not user_path:
                    continue
                yield user_path, int(entry.get("quantity") or fallback_quantity)
            else:
                user_path = str(entry).strip()
                if user_path:
                    yield user_path, fallback_quantity

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
