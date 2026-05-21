#!/usr/bin/env python3
"""Independent FastAPI server for ATRAD debug-mode timing runs."""

import argparse
import asyncio
import random
from collections import defaultdict
from dataclasses import dataclass, field
import math
import time
from typing import Any
from urllib.parse import parse_qs
import sys 
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from services.workflows.order_ladders import calculate_price_levels, calculate_lower_price_levels
from utils.order_store import OrderStore


@dataclass
class TickerProfile:
    symbol: str
    mode: str
    price_levels: list[float]
    start_level_index: int
    requests_per_step: int
    request_count: int = 0
    market_detail_request_count: int = 0
    order_request_count: int = 0
    source_order_ids: list[str] = field(default_factory=list)
    is_multi_queue: bool = False
    just_buy_enabled: bool = False
    trigger_price: float | None = None
    final_order_price: float | None = None

    def current_level_index(self) -> int:
        step = max(1, self.requests_per_step)
        advance = self.request_count // step
        return min(self.start_level_index + advance, len(self.price_levels) - 1)

    def current_price(self) -> float:
        c = self.current_level_index()
        # if c == len(self.price_levels) - 2:
        #     print(time.time() * 1000)
        return self.price_levels[c]

    def record_quote_and_get_price(self) -> float:
        price = self.current_price()
        self.request_count += 1
        return price

    def record_market_details_and_get_price(self) -> float:
        price = self.current_price()
        self.market_detail_request_count += 1
        return price

    def snapshot(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "mode": self.mode,
            "price_levels": self.price_levels,
            "start_level_index": self.start_level_index,
            "current_level_index": self.current_level_index(),
            "current_price": self.current_price(),
            "requests_per_step": self.requests_per_step,
            "request_count": self.request_count,
            "market_detail_request_count": self.market_detail_request_count,
            "order_request_count": self.order_request_count,
            "source_order_ids": list(self.source_order_ids),
            "is_multi_queue": self.is_multi_queue,
            "just_buy_enabled": self.just_buy_enabled,
            "trigger_price": self.trigger_price,
            "final_order_price": self.final_order_price,
        }

    def reset(self) -> None:
        self.request_count = 0
        self.market_detail_request_count = 0
        self.order_request_count = 0


@dataclass
class DebugServerState:
    min_delay_ms: float
    max_delay_ms: float
    broker_code: str
    watch_id: int
    fallback_profile: TickerProfile
    ticker_profiles: dict[str, TickerProfile] = field(default_factory=dict)
    order_accept_after_requests: int = 10
    inactivity_reset_seconds: float = 5.0
    last_request_monotonic: float = field(default_factory=time.monotonic)
    event_history_limit: int = 1000
    quote_events: list[dict[str, Any]] = field(default_factory=list)
    market_detail_events: list[dict[str, Any]] = field(default_factory=list)
    order_events: list[dict[str, Any]] = field(default_factory=list)

    def get_profile(self, symbol: str | None) -> TickerProfile:
        normalized_symbol = (symbol or "").upper()
        return self.ticker_profiles.get(normalized_symbol, self.fallback_profile)

    def reset_count_for_symbol(self, symbol: str | None) -> None:
        normalized_symbol = (symbol or "").upper()
        profile = self.ticker_profiles.get(normalized_symbol)
        if profile:
            profile.reset()

    def reset_all_state(self) -> None:
        self.fallback_profile.reset()
        for profile in self.ticker_profiles.values():
            profile.reset()
        self.quote_events.clear()
        self.market_detail_events.clear()
        self.order_events.clear()

    def note_request(self, now: float | None = None) -> None:
        current = time.monotonic() if now is None else now
        if current - self.last_request_monotonic >= self.inactivity_reset_seconds:
            self.reset_all_state()
        self.last_request_monotonic = current

    async def apply_delay(self, short_delay: bool = False) -> None:
        delay_ms = random.uniform(self.min_delay_ms, self.max_delay_ms)
        if short_delay:
            delay_ms *= 0.1
        await asyncio.sleep(delay_ms / 1000.0)

    def _append_event(self, target: list[dict[str, Any]], payload: dict[str, Any]) -> None:
        target.append(payload)
        if len(target) > self.event_history_limit:
            del target[: len(target) - self.event_history_limit]

    def record_quote(self, symbol: str, price: float) -> None:
        self._append_event(
            self.quote_events,
            {"ts_ms": int(time.time() * 1000), "symbol": symbol, "price": price},
        )

    def record_market_details(self, symbol: str, price: float) -> None:
        self._append_event(
            self.market_detail_events,
            {"ts_ms": int(time.time() * 1000), "symbol": symbol, "price": price},
        )

    def record_order(self, *, symbol: str, accepted: bool, payload: dict[str, Any]) -> None:
        self._append_event(
            self.order_events,
            {
                "ts_ms": int(time.time() * 1000),
                "symbol": symbol,
                "accepted": accepted,
                "payload": payload,
            },
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "delay_ms": {"min": self.min_delay_ms, "max": self.max_delay_ms},
            "order_accept_after_requests": self.order_accept_after_requests,
            "inactivity_reset_seconds": self.inactivity_reset_seconds,
            "profiles": {
                symbol: profile.snapshot()
                for symbol, profile in sorted(self.ticker_profiles.items())
            },
            "fallback_profile": self.fallback_profile.snapshot(),
            "quote_events": list(self.quote_events),
            "market_detail_events": list(self.market_detail_events),
            "order_events": list(self.order_events),
        }


def _build_market_depth(price: float) -> list[dict[str, Any]]:
    price_offsets = [0.0, 0.1, 0.2, 0.3, 0.4]
    bid = []
    ask = []
    for index, offset in enumerate(price_offsets, 1):
        bid.append(
            {
                "price": f"{max(price - offset, 0):.1f}",
                "qty": str(1500 - (index * 120)),
                "orders": str(10 - index),
                "splits": str(10 - index),
            }
        )
        ask.append(
            {
                "price": f"{price + offset + 0.1:.1f}",
                "qty": str(1100 + (index * 90)),
                "orders": str(4 + index),
                "splits": str(4 + index),
            }
        )
    return [{"bid": bid, "ask": ask}]


def _build_fallback_profile(start_price: float, price_step: float, requests_per_step: int) -> TickerProfile:
    levels = [round(start_price + (price_step * idx), 1) for idx in range(6)]
    return TickerProfile(
        symbol="DEFAULT",
        mode="fallback",
        price_levels=levels,
        start_level_index=0,
        requests_per_step=max(1, requests_per_step),
    )


def _select_representative_order(orders: list[dict[str, Any]]) -> dict[str, Any]:
    def sort_key(order: dict[str, Any]) -> tuple[float, float, int]:
        limit = float(order["limit"]) if order.get("limit") is not None else float(order["price"])
        return (float(order["price"]), limit, int(order.get("queue_id", 999)))

    return max(orders, key=sort_key)


def build_profiles_from_order_store(order_store_path: str, base_requests_per_step: int) -> dict[str, TickerProfile]:
    order_store = OrderStore(order_store_path)
    executable_orders = order_store.get_executable_orders()
    validated_orders = [order_store.validate_order(order) for order in executable_orders]

    queue_position_by_order_id: dict[str, int] = {}
    queue_order_counts: dict[int, int] = defaultdict(int)
    for order in validated_orders:
        if order.get("multi_queue", False) or order.get("trigger_sell_queue", False):
            queue_id = int(order.get("queue_id", 999))
            queue_order_counts[queue_id] += 1
            queue_position_by_order_id[str(order["id"])] = queue_order_counts[queue_id]

    orders_by_ticker: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for order in validated_orders:
        mode = order.get("mode")
        if mode not in {"ipo-trigger", "ipo-sell-buy-trigger", "ipo-trigger-low", "trigger-sell"}:
            continue
        orders_by_ticker[order["ticker"]].append(order)

    profiles: dict[str, TickerProfile] = {}
    for ticker, orders in orders_by_ticker.items():
        representative = _select_representative_order(orders)
        mode = str(representative["mode"])
        trigger_price = None
        final_order_price = None

        if mode == "trigger-sell":
            sell_price = float(representative["price"])
            if representative.get("limit") is not None:
                price_levels, _ = calculate_price_levels(
                    base_price=sell_price,
                    limit_price=float(representative["limit"]),
                    no_ladder=False,
                )
                trigger_price = price_levels[-2] if len(price_levels) >= 2 else price_levels[0]
                final_order_price = price_levels[-1]
                start_level_index = max(len(price_levels) - 3, 0)
            else:
                trigger_price = math.ceil((sell_price / 1.03) * 10) / 10
                warmup_price = max(round(trigger_price - 0.1, 1), 0.1)
                price_levels = [warmup_price, trigger_price, sell_price]
                final_order_price = sell_price
                start_level_index = 0
        elif mode == "ipo-trigger-low":
            low_levels, _ = calculate_lower_price_levels(
                base_price=float(representative["price"]),
                limit_price=representative.get("limit"),
            )
            if not low_levels:
                continue
            warmup_price = max(float(representative["price"]), float(representative.get("limit") or representative["price"]))
            trigger_price = low_levels[0]
            final_order_price = low_levels[-1]
            price_levels = [round(warmup_price, 1)] + [round(level, 1) for level in low_levels]
            start_level_index = 0
        else:
            price_levels, _ = calculate_price_levels(
                base_price=float(representative["price"]),
                limit_price=representative.get("limit"),
                no_ladder=False,
            )
            trigger_price = price_levels[-3] if len(price_levels) >= 3 else price_levels[0]
            final_order_price = price_levels[-1]
            start_level_index = max(len(price_levels) - 4, 0)
        if not price_levels:
            continue

        requests_per_step = max(1, base_requests_per_step)
        is_multi_queue = any(
            order.get("multi_queue", False) or order.get("trigger_sell_queue", False)
            for order in orders
        )
        just_buy_enabled = any(order.get("just_buy", False) for order in orders)
        representative_queue_position = queue_position_by_order_id.get(str(representative["id"]), 1)
        if is_multi_queue:
            requests_per_step = requests_per_step * max(1, representative_queue_position)


        profiles[ticker] = TickerProfile(
            symbol=ticker,
            mode=mode,
            price_levels=price_levels,
            start_level_index=start_level_index,
            requests_per_step=requests_per_step,
            source_order_ids=[str(order["id"]) for order in orders],
            is_multi_queue=is_multi_queue,
            just_buy_enabled=just_buy_enabled,
            trigger_price=trigger_price,
            final_order_price=final_order_price,
        )

    return profiles


def build_app(state: DebugServerState):
    from fastapi import FastAPI, Form, Request
    from fastapi.responses import JSONResponse

    app = FastAPI(title="ATRAD Debug Server")

    @app.middleware("http")
    async def reset_on_inactivity(request: Request, call_next):
        state.note_request()
        return await call_next(request)

    @app.post("/atsweb/login")
    async def login(txtUserName: str = Form(...), txtPassword: str = Form(...), action: str = Form(...), format: str = Form(...)) -> JSONResponse:  # noqa: N803
        await state.apply_delay()
        response = JSONResponse(
            {
                "code": "0",
                "description": "login ok",
                "role": "OnlineUser",
                "broker_code": state.broker_code,
                "watchID": str(state.watch_id),
                "max_basket_limit": "25",
                "is_dvp_enabled": "Y",
            }
        )
        response.set_cookie("JSESSIONID", f"debug-session-{txtUserName}")
        response.set_cookie("broker_code", state.broker_code)
        response.set_cookie("watchID", str(state.watch_id))
        response.set_cookie("max_basket_limit", "25")
        response.set_cookie("is_dvp_enabled", "Y")
        return response

    @app.get("/atsweb/login")
    async def check_session(request: Request, action: str, format: str, txtUserName: str | None = None) -> JSONResponse:  # noqa: N803
        await state.apply_delay()
        has_session = bool(request.cookies.get("JSESSIONID"))
        return JSONResponse(
            {
                "code": "0",
                "description": "session ok",
                "data": {"validation": [has_session or True]},
            }
        )

    @app.get("/atsweb/watch")
    async def watch(action: str, format: str, exchange: str, bookDefId: int, securityid: str, dojo: str | None = None) -> JSONResponse:  # noqa: N803
        await state.apply_delay()
        profile = state.get_profile(securityid)
        price = profile.record_quote_and_get_price()
        state.record_quote(securityid, price)
        return JSONResponse(
            {
                "code": "0",
                "description": "ok",
                "data": {
                    "securityid": securityid,
                    "tradeprice": f"{price:.1f}",
                    "exchange": exchange,
                    "bookDefId": str(bookDefId),
                },
            }
        )

    @app.get("/atsweb/marketdetails")
    async def market_details(action: str, format: str, board: int, security: str, dojo: str | None = None) -> JSONResponse:  # noqa: N803
        await state.apply_delay()
        profile = state.get_profile(security)
        price = profile.record_market_details_and_get_price()
        state.record_market_details(security, price)
        return JSONResponse(
            {
                "code": "0",
                "description": "ok",
                "data": {
                    "orderbook": _build_market_depth(price),
                },
            }
        )

    @app.post("/atsweb/order")
    async def order(request: Request) -> JSONResponse:
        await state.apply_delay()
        try:
            raw_body = (await request.body()).decode("utf-8", errors="ignore")
            parsed = parse_qs(raw_body, keep_blank_values=True)
            form = {key: values[-1] if values else "" for key, values in parsed.items()}
            profile = state.get_profile(form.get("txtSecurity"))
            if profile.just_buy_enabled and profile.order_request_count < state.order_accept_after_requests:
                profile.order_request_count += 1
                state.record_order(symbol=form.get("txtSecurity", ""), accepted=False, payload=form)
                return JSONResponse({"code": "3907", "description": "not-accepted"})
            state.reset_count_for_symbol(form.get("txtSecurity"))
            state.record_order(symbol=form.get("txtSecurity", ""), accepted=True, payload=form)
            return JSONResponse(
                {
                    "code": "0",
                    "description": "accepted",
                    "data": {
                        "symbol": form.get("txtSecurity"),
                        "price": form.get("spnPrice"),
                        "marketPrice": form.get("marketPrice"),
                        "quantity": form.get("spnQuantity"),
                    },
                }
            )
        except Exception as exc:
            return JSONResponse({"code": "9999", "description": f"error processing order: {exc}"})

    @app.get("/atsweb/home")
    async def market_status(action: str) -> JSONResponse:
        await state.apply_delay()
        return JSONResponse({"code": "0", "description": "ok", "data": {"status": "OPEN"}})

    @app.get("/atsweb/order")
    async def order_views(request: Request, action: str, format: str) -> JSONResponse:
        await state.apply_delay()
        if action in {"getUCCActiveBlotterData", "getUCCInactiveBlotterData"}:
            return JSONResponse({"code": "0", "description": "ok", "data": {"blotterdata": [], "lastUpdatedTime": ""}})
        if action == "cancelOrder":
            return JSONResponse({"code": "0", "description": "cancelled"})
        return JSONResponse({"code": "0", "description": "ok"})

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/__debug/state")
    async def debug_state() -> JSONResponse:
        return JSONResponse(state.snapshot())

    @app.post("/__debug/reset")
    async def debug_reset() -> JSONResponse:
        state.reset_all_state()
        state.last_request_monotonic = time.monotonic()
        return JSONResponse({"status": "reset"})

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an independent ATRAD debug FastAPI server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--order-store", default=None)
    parser.add_argument("--start-price", type=float, default=100.0)
    parser.add_argument("--price-step", type=float, default=1.0)
    parser.add_argument("--price-step-every-requests", type=int, default=100)
    parser.add_argument("--order-accept-after-requests", type=int, default=10)
    parser.add_argument("--min-delay-ms", type=float, default=6.0)
    parser.add_argument("--max-delay-ms", type=float, default=15.0)
    parser.add_argument("--broker-code", default="DBG")
    parser.add_argument("--watch-id", type=int, default=77)
    parser.add_argument("--inactivity-reset-seconds", type=float, default=5.0)
    return parser.parse_args()


def main() -> None:
    import uvicorn

    args = parse_args()
    fallback_profile = _build_fallback_profile(
        start_price=args.start_price,
        price_step=args.price_step,
        requests_per_step=args.price_step_every_requests,
    )
    ticker_profiles = {}
    if args.order_store:
        ticker_profiles = build_profiles_from_order_store(
            order_store_path=args.order_store,
            base_requests_per_step=args.price_step_every_requests,
        )
        for profile in ticker_profiles.values():
            start_price = profile.price_levels[profile.start_level_index]
            print(
                f"[debug-server] {profile.symbol}: levels={profile.price_levels} "
                f"start={start_price:.1f} step_every_requests={profile.requests_per_step} "
                f"multi_queue={profile.is_multi_queue} just_buy={profile.just_buy_enabled} "
                f"orders={','.join(profile.source_order_ids)}"
            )
    state = DebugServerState(
        min_delay_ms=args.min_delay_ms,
        max_delay_ms=args.max_delay_ms,
        broker_code=args.broker_code,
        watch_id=args.watch_id,
        fallback_profile=fallback_profile,
        ticker_profiles=ticker_profiles,
        order_accept_after_requests=args.order_accept_after_requests,
        inactivity_reset_seconds=args.inactivity_reset_seconds,
    )
    app = build_app(state)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
