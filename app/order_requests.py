"""Shared application-layer builders for order execution payloads."""

import logging
from typing import Any, Dict, Optional

from app.models import ResolvedTicker


logger = logging.getLogger("main")

FETCH_USER_ERROR_BY_MODE = {
    "ipo-trigger": "Fetch user configuration is required for 'ipo-trigger' mode. Use --fetch-user or --fetch-users argument to specify fetch user JSON file(s).",
    "ipo-trigger-low": "Fetch user configuration is required for 'ipo-trigger-low' mode. Use --fetch-user or --fetch-users argument to specify fetch user JSON file(s).",
    "trigger-sell": "Fetch user configuration is required for 'trigger-sell' mode. Use --fetch-user argument to specify fetch user JSON file.",
    "ipo-sell-buy-trigger": "Fetch user configuration is required for 'ipo-sell-buy-trigger' mode. Use --fetch-user or --fetch-users argument to specify fetch user JSON file(s).",
}


def get_fetch_user_error(mode: str) -> Optional[str]:
    """Return the standard fetch-user validation error for a mode."""
    return FETCH_USER_ERROR_BY_MODE.get(mode)


def build_standard_order_params(
    *,
    security_id: int,
    exchange_security_id: int,
    order_price: float,
    order_quantity: int,
    buy_or_sell: int,
    order_type: Optional[str] = None,
    order_validity: Optional[str] = None,
    ipo_trigger_mode: bool = False,
    ipo_trigger_low_mode: bool = False,
    trigger_sell_mode: bool = False,
    limit_price: Optional[float] = None,
    skip_first: bool = False,
    skip_second_last: bool = False,
    no_ladder: bool = False,
    fetch_id: Any = None,
    base_quantity: Optional[int] = None,
    ticker: Optional[str] = None,
    double_buy: bool = False,
    double_buy_quantity: Optional[int] = None,
    just_buy: bool = False,
    just_buy_interval_ms: int = 100,
    just_buy_timeout: int = 5,
    just_buy_pre_wait_ms: int = 0,
    just_buy_max_requests: Optional[int] = None,
    just_buy_fade_interval_ms: Optional[int] = None,
    just_buy_fade_timeout: Optional[int] = None,
    timeout_ipo_trigger_low: Optional[int] = None,
    symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """Build the shared order-service payload used by TMS and ATRAD flows."""
    return {
        "security_id": security_id,
        "exchange_security_id": exchange_security_id,
        "order_price": order_price,
        "order_quantity": order_quantity,
        "buy_or_sell": buy_or_sell,
        "order_type": order_type,
        "order_validity": order_validity,
        "ipo_trigger_mode": ipo_trigger_mode,
        "ipo_trigger_low_mode": ipo_trigger_low_mode,
        "trigger_sell_mode": trigger_sell_mode,
        "limit_price": limit_price,
        "skip_first": skip_first,
        "skip_second_last": skip_second_last,
        "no_ladder": no_ladder,
        "fetch_id": fetch_id,
        "base_quantity": base_quantity,
        "ticker": ticker,
        "double_buy": double_buy,
        "double_buy_quantity": double_buy_quantity,
        "just_buy": just_buy,
        "just_buy_interval_ms": just_buy_interval_ms,
        "just_buy_timeout": just_buy_timeout,
        "just_buy_pre_wait_ms": just_buy_pre_wait_ms,
        "just_buy_max_requests": just_buy_max_requests,
        "just_buy_fade_interval_ms": just_buy_fade_interval_ms,
        "just_buy_fade_timeout": just_buy_fade_timeout,
        "timeout_ipo_trigger_low": timeout_ipo_trigger_low,
        "symbol": symbol,
    }


def build_store_order_params(order: Dict[str, Any], resolved: ResolvedTicker) -> Dict[str, Any]:
    """Build a standard order payload from a normalized order-store entry."""
    return build_standard_order_params(
        security_id=resolved.security_id,
        exchange_security_id=resolved.exchange_security_id,
        order_price=order["price"],
        order_quantity=order["quantity"],
        buy_or_sell=2 if order["sell"] else 1,
        ipo_trigger_mode=order["mode"] == "ipo-trigger",
        ipo_trigger_low_mode=order["mode"] == "ipo-trigger-low",
        trigger_sell_mode=order["mode"] == "trigger-sell",
        limit_price=order["limit"],
        skip_first=order["skip_first"],
        skip_second_last=order["skip_second_last"],
        no_ladder=order["no_ladder"],
        fetch_id=resolved.fetch_id,
        base_quantity=order["base_quantity"],
        ticker=order["ticker"],
        double_buy=order["double_buy"],
        double_buy_quantity=order["double_buy_quantity"],
        just_buy=order.get("just_buy", False),
        just_buy_interval_ms=order.get("just_buy_interval_ms", 100),
        just_buy_timeout=order.get("just_buy_timeout", 5),
        just_buy_pre_wait_ms=order.get("just_buy_pre_wait_ms", 0),
        just_buy_max_requests=order.get("just_buy_max_requests"),
        just_buy_fade_interval_ms=order.get("just_buy_fade_interval_ms"),
        just_buy_fade_timeout=order.get("just_buy_fade_timeout"),
        timeout_ipo_trigger_low=order.get("timeout_ipo_trigger_low"),
        symbol=resolved.symbol,
    )


def build_manual_order_params(args, resolved_ticker: Optional[ResolvedTicker] = None) -> Dict[str, Any]:
    """Build a standard order payload from parsed CLI arguments."""
    symbol = resolved_ticker.symbol if resolved_ticker else (args.ticker.upper() if args.ticker else None)
    fetch_id = resolved_ticker.fetch_id if resolved_ticker else None

    return build_standard_order_params(
        security_id=args.security_id,
        exchange_security_id=args.exchange_security_id,
        order_price=args.price,
        order_quantity=args.quantity,
        buy_or_sell=2 if args.sell else 1,
        order_type=getattr(args, "order_type", None),
        order_validity=getattr(args, "order_validity", None),
        ipo_trigger_mode=args.ipo_trigger,
        ipo_trigger_low_mode=args.ipo_trigger_low,
        trigger_sell_mode=args.trigger_sell,
        limit_price=args.limit,
        skip_first=getattr(args, "skip_first", False),
        fetch_id=fetch_id,
        ticker=symbol,
        double_buy=getattr(args, "double_buy", False),
        double_buy_quantity=getattr(args, "double_buy_quantity", None),
        just_buy=getattr(args, "just_buy", False),
        just_buy_interval_ms=getattr(args, "just_buy_interval", 100),
        just_buy_timeout=getattr(args, "just_buy_timeout", 5),
        just_buy_pre_wait_ms=getattr(args, "just_buy_pre_wait", 0),
        timeout_ipo_trigger_low=getattr(args, "timeout_ipo_trigger_low", None),
        symbol=symbol,
    )


def log_standard_order_plan(
    *,
    user_id: str,
    mode: str,
    is_sell: bool,
    security_id: int,
    exchange_security_id: int,
    price: float,
    quantity: int,
    ticker: Optional[str] = None,
    ticker_name: Optional[str] = None,
    limit_price: Optional[float] = None,
    scheduled_time: Optional[str] = None,
    refresh_before: Optional[int] = None,
) -> None:
    """Emit a consistent execution summary for standard order flows."""
    logger.info(f"Execution Mode: {mode}")
    logger.info(f"User: {user_id}")
    logger.info(f"Order: {'SELL' if is_sell else 'BUY'}")
    if ticker:
        if ticker_name:
            logger.info(f"Ticker: {ticker} ({ticker_name})")
        else:
            logger.info(f"Ticker: {ticker}")
    logger.info(f"Security ID: {security_id}")
    logger.info(f"Exchange Security ID: {exchange_security_id}")
    logger.info(f"Price: {price}, Quantity: {quantity}")
    if limit_price is not None:
        logger.info(f"Limit: {limit_price}")
    if scheduled_time:
        logger.info(f"Scheduled Time: {scheduled_time}")
    if refresh_before is not None:
        logger.info(f"Token Refresh: {refresh_before}s before execution")
