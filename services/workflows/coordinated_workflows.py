"""Coordinated multi-order workflows extracted from BaseOrderService."""

import threading
import time
from typing import Any, Dict, List, Optional

from api import ATRADClient


def execute_multi_queue_ipo_trigger(
    service: Any,
    orders: List[Dict[str, Any]],
    fetch_clients: List[Any],
    on_order_complete: Optional[Any] = None,
) -> Dict[str, Any]:
    """Execute multi-queue IPO trigger mode for multiple orders."""
    from services.fetchers.multi_symbol_price_fetcher import MultiSymbolSequentialPriceFetcher, SymbolConfig

    service.logger.info(
        f"[{service.user_id}] MULTI-QUEUE MODE: Monitoring {len(orders)} orders concurrently"
    )

    for order in orders:
        if not order.get("multi_queue"):
            raise ValueError(f"Order {order.get('id')} missing multi_queue=true")
        if not order.get("no_ladder"):
            raise ValueError(f"Order {order.get('id')} missing no_ladder=true")

    is_atrad = len(fetch_clients) > 0 and isinstance(fetch_clients[0], ATRADClient)

    symbols_config = []
    for order in orders:
        price_levels, _ = service._calculate_price_levels(order["price"], order.get("limit"))
        third_last_index = len(price_levels) - 3 if len(price_levels) >= 3 else -1
        switch_threshold = price_levels[third_last_index] if third_last_index >= 0 else price_levels[0]

        symbol_config = SymbolConfig(
            symbol=order.get("symbol") if is_atrad else order["ticker"],
            switch_threshold=switch_threshold,
            order_id=order["id"],
            security_id=order.get("security_id"),
            fetch_security_id=order.get("fetch_id"),
        )
        symbols_config.append(symbol_config)

        service.logger.info(
            f"[{service.user_id}] Multi-queue order: {order['id']} ({symbol_config.symbol}) "
            f"switch_threshold=Rs. {switch_threshold}"
        )

    poll_interval_ms = service.client.user_config.multi_fetch_poll_interval_ms
    sleep_duration = max(poll_interval_ms / 10000.0, 0.001)
    multi_fetcher = MultiSymbolSequentialPriceFetcher(
        symbols_config=symbols_config,
        fetch_clients=fetch_clients,
        poll_interval_ms=poll_interval_ms,
        user_id=service.user_id,
        is_atrad=is_atrad,
    )

    multi_fetcher.start()
    try:
        service.logger.info(f"[{service.user_id}] Waiting for first order to reach switch threshold...")
        while multi_fetcher.get_priority_symbol() is None:
            time.sleep(sleep_duration)
        priority_symbol = multi_fetcher.get_priority_symbol()
        all_ltps = multi_fetcher.get_all_ltps()
    finally:
        multi_fetcher.stop()

    ltps_str = ", ".join([f"{sym}={ltp if ltp else 'N/A'}" for sym, ltp in all_ltps.items()])
    service.logger.info(f"[{service.user_id}] Multi-queue final LTPs: {ltps_str}")

    priority_order = None
    remaining_orders = []
    for order in orders:
        symbol = order.get("symbol") if is_atrad else order["ticker"]
        if symbol == priority_symbol:
            priority_order = order
        else:
            remaining_orders.append(order)

    if priority_order is None:
        raise ValueError(f"Priority symbol {priority_symbol} not found in orders")

    service.logger.info(
        f"[{service.user_id}] PRIORITY ORDER: {priority_order['id']} ({priority_symbol})"
    )

    responses = []
    failed_orders = []
    successful_orders = []

    try:
        service.logger.info(f"[{service.user_id}] Executing priority order: {priority_order['id']}")
        response = service._execute_single_ipo_order(priority_order, fetch_clients, True)
        responses.append(response)
        successful_orders.append(priority_order["id"])
        if on_order_complete is not None:
            on_order_complete(priority_order["id"], True, None)
    except Exception as exc:
        service.logger.error(f"[{service.user_id}] Priority order {priority_order['id']} FAILED: {exc}")
        failed_orders.append(priority_order["id"])
        if on_order_complete is not None:
            on_order_complete(priority_order["id"], False, exc)

    for remaining_order in remaining_orders:
        remaining_symbol = remaining_order.get("symbol") if is_atrad else remaining_order["ticker"]
        service.logger.info(
            f"[{service.user_id}] Executing remaining order: {remaining_order['id']} ({remaining_symbol})"
        )
        try:
            response = service._execute_single_ipo_order(remaining_order, fetch_clients, False)
            responses.append(response)
            successful_orders.append(remaining_order["id"])
            if on_order_complete is not None:
                on_order_complete(remaining_order["id"], True, None)
        except Exception as exc:
            service.logger.error(f"[{service.user_id}] Remaining order {remaining_order['id']} FAILED: {exc}")
            failed_orders.append(remaining_order["id"])
            if on_order_complete is not None:
                on_order_complete(remaining_order["id"], False, exc)

    service.logger.info(
        f"[{service.user_id}] MULTI-QUEUE COMPLETE: {len(successful_orders)} successful, {len(failed_orders)} failed"
    )
    return {
        "responses": responses,
        "failed_orders": failed_orders,
        "successful_orders": successful_orders,
    }


def execute_single_ipo_order(
    service: Any,
    order: Dict[str, Any],
    fetch_clients: List[Any],
    already_triggered: bool = False,
) -> Dict[str, Any]:
    """Execute a single IPO order as part of multi-queue flow."""
    is_atrad = len(fetch_clients) > 0 and isinstance(fetch_clients[0], ATRADClient)

    if is_atrad:
        platform_params = {
            "symbol": order["symbol"],
            "side": "SELL" if order.get("sell") else "BUY",
        }
    else:
        platform_params = {
            "security_id": order["security_id"],
            "exchange_security_id": order["exchange_security_id"],
            "buy_or_sell": 2 if order.get("sell") else 1,
            "order_type": "LMT",
            "order_validity": "DAY",
        }

    try:
        return service._execute_ipo_trigger(
            base_price=order["price"],
            order_quantity=order["quantity"],
            fetch_clients=fetch_clients,
            limit_price=order.get("limit"),
            skip_first=order.get("skip_first", False),
            skip_second_last=order.get("skip_second_last", False),
            no_ladder=order.get("no_ladder", False),
            fetch_security_id=order.get("fetch_id"),
            base_quantity=order.get("base_quantity"),
            ticker=order.get("ticker"),
            double_buy=order.get("double_buy", False),
            double_buy_quantity=order.get("double_buy_quantity"),
            just_buy=order.get("just_buy", False),
            just_buy_interval_ms=order.get("just_buy_interval_ms", 100),
            just_buy_timeout=order.get("just_buy_timeout", 5),
            just_buy_pre_wait_ms=order.get("just_buy_pre_wait_ms", 0),
            just_buy_max_requests=order.get("just_buy_max_requests"),
            just_buy_fade_interval_ms=order.get("just_buy_fade_interval_ms"),
            just_buy_fade_timeout=order.get("just_buy_fade_timeout"),
            already_triggered=already_triggered,
            **platform_params,
        )
    finally:
        if hasattr(service.client, "flush_successful_orders"):
            service.client.flush_successful_orders()


def execute_ipo_sell_buy_trigger(
    service: Any,
    buyer_service: Any,
    fetch_clients: List[Any],
    ticker: Optional[str],
    security_id: Optional[int],
    exchange_security_id: Optional[int],
    symbol: Optional[str],
    base_price: float,
    buy_quantity: int,
    sell_quantity: int,
    sell_pre_wait_ms: int,
    limit_price: Optional[float] = None,
    just_buy_interval_ms: int = 100,
    just_buy_timeout: int = 5,
) -> Dict[str, Any]:
    """Execute IPO sell-buy-trigger mode."""
    price_levels, actual_increments = service._calculate_price_levels(base_price, limit_price)

    if len(price_levels) < 3:
        raise ValueError(
            f"Ladder must have at least 3 levels for ipo-sell-buy-trigger mode. "
            f"Current ladder has {len(price_levels)} levels. "
            f"Try increasing limit_price or adjusting base_price."
        )

    third_last_index = len(price_levels) - 3
    second_last_index = len(price_levels) - 2
    final_index = len(price_levels) - 1

    third_last_price = price_levels[third_last_index]
    second_last_price = price_levels[second_last_index]
    final_price = price_levels[final_index]

    service.logger.info(
        f"[{service.user_id}] IPO SELL-BUY-TRIGGER: Ladder calculated with {len(price_levels)} levels"
    )
    for i, (price, inc) in enumerate(zip(price_levels, actual_increments)):
        marker = ""
        if i == third_last_index:
            marker = " [TRIGGER LEVEL]"
        elif i == second_last_index:
            marker = " [SELL LEVEL]"
        elif i == final_index:
            marker = " [BUY LEVEL]"
        service.logger.debug(f"  Level {i+1}: Rs. {price} (+{inc}%){marker}")

    service.logger.info(
        f"[{service.user_id}] Third Last: Rs. {third_last_price}, "
        f"Sell at: Rs. {second_last_price}, Buy at: Rs. {final_price}"
    )
    service.logger.info(
        f"[{service.user_id}] Sell quantity: {sell_quantity}, Buy quantity: {buy_quantity}"
    )

    poll_interval_ms = service.client.user_config.trigger_mode_poll_interval_ms
    fetch_security_id = security_id or symbol
    price_fetcher = service._setup_price_fetcher(
        fetch_clients, fetch_security_id, symbol, ticker, poll_interval_ms
    )

    seller_token_manager = service._setup_token_manager()
    buyer_token_manager = buyer_service._setup_token_manager()
    is_buyer_atrad = isinstance(buyer_service.client, ATRADClient)
    is_seller_atrad = isinstance(service.client, ATRADClient)

    buy_success_flag = threading.Event()
    sell_success_flag = threading.Event()
    buy_response_container = {"response": None}
    sell_response_container = {"response": None}
    threads_lock = threading.Lock()
    active_threads = []
    sleep_duration = 0.005

    try:
        service.logger.info(
            f"[{service.user_id}] Waiting for LTP >= Rs. {third_last_price} (third last level)..."
        )
        while True:
            ltp = price_fetcher.get_latest_ltp()
            if ltp is not None and ltp >= third_last_price:
                service.logger.info(
                    f"[{service.user_id}] TRIGGER REACHED! LTP={ltp} >= Rs. {third_last_price}"
                )
                break
            time.sleep(sleep_duration)

        if hasattr(price_fetcher, "start_market_details"):
            service.logger.info(f"[{service.user_id}] Starting market details monitor for sell-buy trigger")
            price_fetcher.start_market_details()

        service.logger.info(
            f"[{service.user_id}] Starting sell pre-wait timer: {sell_pre_wait_ms}ms"
        )
        timer_start = time.time()
        timer_duration = sell_pre_wait_ms / 1000.0
        buy_start_offset = (sell_pre_wait_ms - 10) / 1000.0

        buy_threads_started = False
        sell_thread_started = False
        current_ltp = price_fetcher.get_latest_ltp()

        while time.time() - timer_start < timer_duration:
            elapsed = time.time() - timer_start
            if not buy_threads_started and elapsed >= buy_start_offset:
                buy_threads_started = True
                service.logger.info(
                    f"[{service.user_id}] Starting BUY threads ({buy_start_offset}s before sell)..."
                )
                buy_spawner_thread = threading.Thread(
                    target=service._spawn_buy_threads,
                    args=(
                        buyer_service,
                        final_price,
                        buy_quantity,
                        just_buy_interval_ms,
                        just_buy_timeout,
                        buy_success_flag,
                        buy_response_container,
                        threads_lock,
                        active_threads,
                        is_buyer_atrad,
                        security_id,
                        exchange_security_id,
                        symbol,
                        second_last_price,
                    ),
                    daemon=True,
                )
                buy_spawner_thread.start()

            time.sleep(sleep_duration)

        service.logger.info(
            f"[{service.user_id}] Timer expired! Placing SELL order at Rs. {second_last_price}..."
        )
        sell_thread = threading.Thread(
            target=service._place_sell_order_with_retry,
            args=(
                second_last_price,
                sell_quantity,
                sell_success_flag,
                sell_response_container,
                is_seller_atrad,
                security_id,
                exchange_security_id,
                symbol,
                current_ltp,
            ),
            daemon=True,
        )
        sell_thread.start()
        sell_thread_started = True

        service.logger.info(
            f"[{service.user_id}] Waiting for buy order to succeed or timeout..."
        )
        buy_success_flag.wait(timeout=just_buy_timeout + 1)

        if buy_success_flag.is_set():
            service.logger.info(f"[{service.user_id}] BUY ORDER SUCCEEDED!")
        else:
            service.logger.warning(
                f"[{service.user_id}] Buy orders did not succeed within timeout"
            )

        if sell_thread_started:
            sell_thread.join(timeout=5)

        if sell_success_flag.is_set():
            service.logger.info(f"[{service.user_id}] SELL ORDER SUCCEEDED!")
        else:
            service.logger.warning(f"[{service.user_id}] Sell order did not succeed")

        return {
            "buy_response": buy_response_container["response"],
            "sell_response": sell_response_container["response"],
            "buy_success": buy_success_flag.is_set(),
            "sell_success": sell_success_flag.is_set(),
        }
    finally:
        if hasattr(price_fetcher, "stop_market_details"):
            price_fetcher.stop_market_details()
        price_fetcher.stop()
        service._cleanup_token_manager(seller_token_manager)
        buyer_service._cleanup_token_manager(buyer_token_manager)

        for thread in active_threads:
            if thread.is_alive():
                thread.join(timeout=1)


def spawn_buy_threads(
    service: Any,
    buyer_service: Any,
    final_price: float,
    buy_quantity: int,
    interval_ms: int,
    timeout: int,
    success_flag: Any,
    response_container: Dict[str, Any],
    threads_lock: Any,
    active_threads: List[Any],
    is_atrad: bool,
    security_id: Optional[int],
    exchange_security_id: Optional[int],
    symbol: Optional[str],
    market_price: Optional[float],
) -> None:
    """Spawn buy order threads at intervals."""
    thread_counter = 0
    start_time = time.time()
    interval_seconds = interval_ms / 1000.0

    def place_buy_order(thread_id: int) -> None:
        try:
            if success_flag.is_set():
                return

            service.logger.debug(
                f"[{buyer_service.user_id}] Buy Thread #{thread_id}: "
                f"Placing order at Rs. {final_price}"
            )

            if is_atrad:
                platform_params = {
                    "symbol": symbol,
                    "side": "BUY",
                    "market_price": market_price,
                }
            else:
                platform_params = {
                    "security_id": security_id,
                    "exchange_security_id": exchange_security_id,
                    "buy_or_sell": 1,
                    "order_type": "LMT",
                    "order_validity": "DAY",
                    "market_price": market_price,
                }

            response = buyer_service._place_single_order(
                price=final_price,
                quantity=buy_quantity,
                **platform_params,
            )

            if response and not success_flag.is_set():
                success_flag.set()
                with threads_lock:
                    response_container["response"] = response
                service.logger.info(
                    f"[{buyer_service.user_id}] Buy Thread #{thread_id}: SUCCESS!"
                )
        except Exception as exc:
            service.logger.debug(
                f"[{buyer_service.user_id}] Buy Thread #{thread_id} failed: {str(exc)}"
            )

    while (time.time() - start_time) < timeout:
        if success_flag.is_set():
            service.logger.info(
                f"[{buyer_service.user_id}] Buy success detected, stopping thread spawner"
            )
            break

        thread_counter += 1
        thread = threading.Thread(
            target=place_buy_order,
            args=(thread_counter,),
            daemon=True,
        )

        with threads_lock:
            active_threads.append(thread)

        thread.start()
        time.sleep(interval_seconds)

    service.logger.info(
        f"[{buyer_service.user_id}] Buy thread spawner finished: {thread_counter} threads spawned"
    )


def place_sell_order_with_retry(
    service: Any,
    sell_price: float,
    sell_quantity: int,
    success_flag: Any,
    response_container: Dict[str, Any],
    is_atrad: bool,
    security_id: Optional[int],
    exchange_security_id: Optional[int],
    symbol: Optional[str],
    market_price: Optional[float],
    max_retries: int = 2,
) -> None:
    """Place a coordinated sell order with retry logic."""
    service.logger.info(
        f"[{service.user_id}] Placing SELL order at Rs. {sell_price} x {sell_quantity}"
    )

    if is_atrad:
        platform_params = {
            "symbol": symbol,
            "side": "SELL",
            "market_price": market_price,
        }
    else:
        platform_params = {
            "security_id": security_id,
            "exchange_security_id": exchange_security_id,
            "buy_or_sell": 2,
            "order_type": "LMT",
            "order_validity": "DAY",
            "market_price": market_price,
        }

    for attempt in range(1, max_retries + 1):
        try:
            service.logger.debug(
                f"[{service.user_id}] Sell order attempt #{attempt}/{max_retries}"
            )
            response = service._place_single_order(
                price=sell_price,
                quantity=sell_quantity,
                **platform_params,
            )
            if response:
                success_flag.set()
                response_container["response"] = response
                service.logger.info(
                    f"[{service.user_id}] SELL order SUCCESS on attempt #{attempt}!"
                )
                return
        except Exception as exc:
            service.logger.warning(
                f"[{service.user_id}] Sell order attempt #{attempt} failed: {str(exc)}"
            )
            if attempt < max_retries:
                time.sleep(0.1)

    service.logger.error(
        f"[{service.user_id}] SELL order FAILED after {max_retries} attempts"
    )
