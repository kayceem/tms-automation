"""ATRAD portfolio and order-book adapters for the TUI."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

from api.atrad_client import ATRADClient
from config import ATRADUserConfig
from tui.models import (
    CustomWatchlistRow,
    MarketDepthLevelRow,
    MarketDepthSnapshot,
    OrderBookRow,
    SectorSummary,
    WatchlistEntryRow,
)
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

    def load_portfolio_defaults(
        self,
        path: str | Path = "stores/default_store.json",
    ) -> tuple[str | None, list[str | None]]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, ValueError):
            return None, [None, None, None, None]

        portfolio = payload.get("portfolio")
        if not isinstance(portfolio, dict):
            return None, [None, None, None, None]

        market_summary = portfolio.get("market_summary")
        market_symbol = str(market_summary).strip().upper() if market_summary else None

        raw_depth = portfolio.get("market_depth")
        market_depth: list[str | None] = [None, None, None, None]
        if isinstance(raw_depth, list):
            for index, symbol in enumerate(raw_depth[:4]):
                cleaned = str(symbol).strip().upper() if symbol else ""
                market_depth[index] = cleaned or None

        if market_symbol is None:
            market_symbol = next((symbol for symbol in market_depth if symbol), None)
        if market_depth[0] is None:
            market_depth[0] = market_symbol

        return market_symbol, market_depth

    def list_atrad_users(self) -> list[Path]:
        return iter_atrad_user_paths(self.users_dir)

    def load_user_config(self, path: str | Path) -> ATRADUserConfig:
        return ATRADUserConfig.from_file(str(path))

    def get_user_label(self, path: str | Path) -> str:
        config = self.load_user_config(path)
        return config.username or config.user_id

    def fetch_order_book(
        self,
        path: str | Path,
        *,
        completed: bool = False,
    ) -> tuple[list[OrderBookRow], dict]:
        client = ATRADClient(self.load_user_config(path))
        payload = client.get_order_book(completed=completed)
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

    def fetch_custom_watchlists(self, path: str | Path) -> list[CustomWatchlistRow]:
        client = ATRADClient(self.load_user_config(path))
        payload = client.get_custom_watchlists()
        if payload is None:
            raise RuntimeError("Unable to fetch ATRAD custom watchlists")

        return [
            CustomWatchlistRow(
                watch_list_id=_pick_first(item, "watchListID", "watchlistid"),
                watch_list_name=_pick_first(item, "watchListName", "watchlistname"),
                exchange_id=_pick_first(item, "exchangeID", "exchangeid", default="-"),
                raw=item,
            )
            for item in payload
        ]

    def fetch_watchlist(self, path: str | Path, watch_id: int) -> tuple[list[WatchlistEntryRow], str]:
        client = ATRADClient(self.load_user_config(path))
        payload = client.get_watchlist(watch_id)
        if payload is None:
            raise RuntimeError("Unable to fetch ATRAD watchlist contents")

        rows = [
            WatchlistEntryRow(
                security_code=_pick_first(item, "security", "securitycode", "securityCode", "symbol", default="-"),
                bid_quantity=_pick_first(item, "bidqty", "bidQty", default="-"),
                bid_price=_pick_first(item, "bidprice", "bidPrice", default="-"),
                ask_quantity=_pick_first(item, "askqty", "askQty", default="-"),
                ask_price=_pick_first(item, "askprice", "askPrice", default="-"),
                net_change=_pick_first(item, "netchange", "change", "changeinprice", "changeValue", default="-"),
                percent_change=_pick_first(item, "perchange", "percentChange", default="-"),
                last_price=_pick_first(item, "tradeprice", "ltp", "lastTradedPrice", default="-"),
                last_traded_time=_pick_first(item, "lasttradedtime", "lastTradedTime", default="-"),
                opening_price=_pick_first(item, "openingprice", "openingPrice", default="-"),
                high_price=_pick_first(item, "highpx", "highPrice", default="-"),
                low_price=_pick_first(item, "lowpx", "lowPrice", default="-"),
                volume=_pick_first(item, "totvolume", "tradeqty", "volume", "ttq", default="-"),
                turnover=_pick_first(item, "totturnover", "turnover", default="-"),
                raw=item,
            )
            for item in payload
        ]
        rows.sort(key=lambda row: row.security_code)
        return rows, datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch_top_gainers_losers(
        self,
        path: str | Path,
        *,
        gainers: bool = True,
    ) -> tuple[list[WatchlistEntryRow], str]:
        client = ATRADClient(self.load_user_config(path))
        payload = client.get_top_gainers_losers(gainers=gainers)
        if payload is None:
            raise RuntimeError("Unable to fetch ATRAD top gainers/losers")

        rows = [
            WatchlistEntryRow(
                security_code=_pick_first(item, "security", "securitycode", "securityCode", "symbol", default="-"),
                bid_quantity=_pick_first(item, "bidqty", "bidQty", default="-"),
                bid_price=_pick_first(item, "bidprice", "bidPrice", default="-"),
                ask_quantity=_pick_first(item, "askqty", "askQty", default="-"),
                ask_price=_pick_first(item, "askprice", "askPrice", default="-"),
                net_change=_pick_first(item, "netchange", "change", "changeinprice", "changeValue", default="-"),
                percent_change=_pick_first(item, "perchange", "percentChange", default="-"),
                last_price=_pick_first(item, "tradeprice", "ltp", "lastTradedPrice", default="-"),
                last_traded_time=_pick_first(item, "lasttradedtime", "lastTradedTime", default="-"),
                opening_price=_pick_first(item, "openingprice", "openingPrice", default="-"),
                high_price=_pick_first(item, "highpx", "highPrice", default="-"),
                low_price=_pick_first(item, "lowpx", "lowPrice", default="-"),
                volume=_pick_first(item, "totvolume", "tradeqty", "volume", "ttq", default="-"),
                turnover=_pick_first(item, "totturnover", "turnover", default="-"),
                raw=item,
            )
            for item in payload
        ]
        rows.sort(
            key=lambda row: float(str(row.percent_change).replace("%", "").replace(",", "") or 0),
            reverse=gainers,
        )
        return rows, datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch_account_summary(self, path: str | Path) -> tuple[dict, str]:
        client = ATRADClient(self.load_user_config(path))
        payload = client.get_account_summary()
        if payload is None:
            raise RuntimeError("Unable to fetch ATRAD account summary")
        summary = payload.get("clientSummary")
        if not isinstance(summary, dict):
            raise RuntimeError("Invalid ATRAD account summary payload")
        return summary, datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch_sector_summary(self, path: str | Path) -> SectorSummary | None:
        client = ATRADClient(self.load_user_config(path))
        payload = client.get_sector_data()
        if not isinstance(payload, list) or not payload:
            return None
        first = payload[0]
        if not isinstance(first, dict):
            return None

        index_value = _pick_first(first, "pr1", default="-")
        points_change = _pick_first(first, "n1", default="-")
        percent_change = _pick_first(first, "p1", default="-")
        turnover = _pick_first(first, "to", default="-")

        try:
            points_float = float(points_change.replace(",", ""))
        except (AttributeError, TypeError, ValueError):
            points_float = 0.0

        return SectorSummary(
            index_value=index_value,
            points_change=points_change,
            percent_change=percent_change,
            turnover=turnover,
            is_up=points_float > 0,
            is_down=points_float < 0,
        )

    def build_cancel_url(self, path: str | Path, order: dict) -> str:
        client = ATRADClient(self.load_user_config(path))
        return client.build_cancel_order_url(order)

    def cancel_order(self, path: str | Path, order: dict) -> dict:
        client = ATRADClient(self.load_user_config(path))
        return client.cancel_order(order)

    def add_symbol_to_watchlist(self, path: str | Path, watch_id: int, symbol: str) -> dict:
        client = ATRADClient(self.load_user_config(path))
        return client.add_or_remove_security_from_watchlist(watch_id, symbol)

    def remove_symbol_from_watchlist(self, path: str | Path, watch_id: int, symbol: str) -> dict:
        client = ATRADClient(self.load_user_config(path))
        return client.add_or_remove_security_from_watchlist(watch_id, symbol, remove=True)

    def fetch_market_details(self, client: ATRADClient, symbol: str) -> dict:
        result = client.get_market_details(symbol, complete=True)
        if not isinstance(result, list) or not result:
            return {}
        return result[0] if isinstance(result[0], dict) else {}

    def fetch_ltp_details(self, client: ATRADClient, symbol: str) -> dict:
        result = client.get_ltp(symbol, complete=True)
        if not isinstance(result, dict) or not result:
            return {}
        return result

    def fetch_script_details(self, path: str | Path, symbol: str) -> tuple[dict, dict, str]:
        client = ATRADClient(self.load_user_config(path))
        ltp = self.fetch_ltp_details(client, symbol)
        market_details = self.fetch_market_details(client, symbol)
        last_updated_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return ltp, market_details, last_updated_time

    @staticmethod
    def _depth_levels(levels: Iterable[dict], *, limit: int = 3) -> list[MarketDepthLevelRow]:
        rows: list[MarketDepthLevelRow] = []
        for item in list(levels)[:limit]:
            if not isinstance(item, dict):
                continue
            rows.append(
                MarketDepthLevelRow(
                    splits=_pick_first(item, "splits", default="-"),
                    quantity=_pick_first(item, "qty", "quantity", default="-"),
                    price=_pick_first(item, "price", default="-"),
                )
            )
        return rows

    def fetch_market_depth_snapshot(
        self,
        path: str | Path,
        symbol: str,
        *,
        levels: int = 5,
    ) -> MarketDepthSnapshot:
        client = ATRADClient(self.load_user_config(path))
        ltp = self.fetch_ltp_details(client, symbol)
        market_details = self.fetch_market_details(client, symbol)
        last_updated_time = datetime.now().strftime("%H:%M:%S")

        bids = self._depth_levels(market_details.get("bid", []), limit=levels)
        asks = self._depth_levels(market_details.get("ask", []), limit=levels)

        return MarketDepthSnapshot(
            symbol=symbol,
            last_updated_time=last_updated_time,
            last_price=_pick_first(ltp, "tradeprice", default="-"),
            net_change=_pick_first(ltp, "netchange", default="-"),
            percent_change=_pick_first(ltp, "perchange", default="-"),
            volume=_pick_first(ltp, "totvolume", default="-"),
            total_bids=_pick_first(market_details, "totalbids", default="0"),
            total_asks=_pick_first(market_details, "totalask", default="0"),
            bids=bids,
            asks=asks,
            ltp_raw=ltp,
            market_raw=market_details,
        )

    def load_tickers(self, path: str | Path = "stores/tickers.json") -> list[dict]:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return []
        if isinstance(data, list):
            return [t for t in data if isinstance(t, dict) and t.get("security")]
        return []
