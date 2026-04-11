"""ATRAD portfolio and order-book adapters for the TUI."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from api.atrad_client import ATRADClient
from config import ATRADUserConfig
from tui.models import OrderBookRow
from utils.config.atrad_config_actions import iter_atrad_user_paths


def _pick_first(payload: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _decimal_text(value: str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if number.is_integer():
        return str(int(number))
    return f"{number:.2f}"


def _amount_text(price: str, quantity: str) -> str:
    try:
        return _decimal_text(str(float(price) * float(quantity)))
    except (TypeError, ValueError):
        return "-"


class PortfolioService:
    """TUI adapter around ATRAD portfolio/order-book operations."""

    def __init__(self, users_dir: str | Path = "users") -> None:
        self.users_dir = Path(users_dir)

    def list_atrad_users(self) -> list[Path]:
        return iter_atrad_user_paths(self.users_dir)

    def load_user_config(self, path: str | Path) -> ATRADUserConfig:
        return ATRADUserConfig.from_file(str(path))

    def fetch_order_book(self, path: str | Path) -> tuple[list[OrderBookRow], dict]:
        client = ATRADClient(self.load_user_config(path))
        payload = client.get_order_book()
        if payload is None:
            raise RuntimeError("Unable to fetch ATRAD order book")

        rows = [
            OrderBookRow(
                client_order_id=_pick_first(order, "clientorderid", "clientOrderId"),
                exchange_order_id=_pick_first(order, "exchangeorderid", "exchangeOrderId"),
                security_code=_pick_first(order, "securitycode", "securityCode"),
                action=_pick_first(order, "action", default="-"),
                quantity=_pick_first(order, "orderQuantity", "qty", default="-"),
                filled_quantity=_pick_first(order, "filledquantity", default="-"),
                remainder=_pick_first(order, "remainder", default="-"),
                price=_pick_first(order, "orderprice", default="-"),
                amount=_amount_text(_pick_first(order, "orderprice", default=""),_pick_first(order, "orderQuantity", "qty", default="")),
                order_status=_pick_first(order, "orderstatus", "orderStatus", default="-"),
                order_time=_pick_first(order, "orderplacedate", default=""),
                last_updated_time=_pick_first(order, "lastupdatedtime", default=""),
                raw=order,
            )
            for order in payload.get("blotterdata",[])
        ]
        rows.sort(key=lambda row: row.last_updated_time or "", reverse=True)
        return rows, payload

    def build_cancel_url(self, path: str | Path, order: dict) -> str:
        client = ATRADClient(self.load_user_config(path))
        return client.build_cancel_order_url(order)

    def cancel_order(self, path: str | Path, order: dict) -> dict:
        client = ATRADClient(self.load_user_config(path))
        return client.cancel_order(order)
