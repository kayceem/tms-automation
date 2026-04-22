#!/usr/bin/env python3
"""Independent FastAPI server for ATRAD debug-mode timing runs."""

from __future__ import annotations

import argparse
import asyncio
import random
from dataclasses import dataclass

import uvicorn
from fastapi import FastAPI, Form, Request
from fastapi.responses import JSONResponse


@dataclass
class DebugServerState:
    start_price: float
    price_step: float
    price_step_every_requests: int
    min_delay_ms: float
    max_delay_ms: float
    broker_code: str
    watch_id: int
    quote_request_count: int = 0

    def current_price(self) -> float:
        requests_per_step = max(1, self.price_step_every_requests)
        steps = self.quote_request_count // requests_per_step
        return self.start_price + (steps * self.price_step)

    async def apply_delay(self, short_delay: bool = False) -> None:
        delay_ms = random.uniform(self.min_delay_ms, self.max_delay_ms)
        if short_delay:
            delay_ms *= 0.1
        await asyncio.sleep(delay_ms / 1000.0)


def build_app(state: DebugServerState) -> FastAPI:
    app = FastAPI(title="ATRAD Debug Server")

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
        state.quote_request_count += 1
        price = state.current_price()
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
        price = state.current_price()
        return JSONResponse(
            {
                "code": "0",
                "description": "ok",
                "data": {
                    "orderbook": [
                        {
                            "bid":[
                                {
                                    "price": f"{price:.1f}",
                                    "qty": "1270",
                                    "splits": "10" 
                                }
                            ]
                        },
                    ]
                },
            }
        )
    @app.post("/atsweb/order")
    async def order(request: Request) -> JSONResponse:
        await state.apply_delay()
        form = dict(await request.form())
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

    return app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an independent ATRAD debug FastAPI server.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8010)
    parser.add_argument("--start-price", type=float, default=100.0)
    parser.add_argument("--price-step", type=float, default=1.0)
    parser.add_argument("--price-step-every-requests", type=int, default=100)
    parser.add_argument("--min-delay-ms", type=float, default=6.0)
    parser.add_argument("--max-delay-ms", type=float, default=15.0)
    parser.add_argument("--broker-code", default="DBG")
    parser.add_argument("--watch-id", type=int, default=77)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    state = DebugServerState(
        start_price=args.start_price,
        price_step=args.price_step,
        price_step_every_requests=args.price_step_every_requests,
        min_delay_ms=args.min_delay_ms,
        max_delay_ms=args.max_delay_ms,
        broker_code=args.broker_code,
        watch_id=args.watch_id,
    )
    app = build_app(state)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
