"""Execution and orchestration helpers for orders and queues."""

import logging
import math
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from config import ATRADUserConfig
from services.scheduling import OrderScheduler
from utils import OrderStore
from services.fetchers.multi_symbol_price_fetcher import (
    MultiSymbolSequentialPriceFetcher,
    SymbolConfig,
    sync_multi_symbol_poll_interval_ms,
)
from services.workflows.order_ladders import calculate_price_levels

from app.config_loader import load_trader_config, load_just_buy_user_specs, load_user_configs_by_paths
from app.factories import (
    create_order_bundles,
    create_fetch_clients,
    create_order_client_and_service,
    log_fetch_client_summary,
    lookup_ticker_name,
    resolve_ticker,
)
from app.order_requests import (
    build_manual_order_params,
    build_store_order_params,
    get_fetch_user_error,
    log_standard_order_plan,
)
from app.pool_users import UserPool, resolve_pool_order_users, validate_pool_orders


logger = logging.getLogger("main")


def _resolve_execution_users(
    *,
    pool: Optional[UserPool],
    pooled_user_id: Optional[str],
    default_user_config,
    default_fetch_user_configs,
    default_is_atrad_fetch: bool,
):
    """Resolve active main/fetch users for one order or queue group."""
    if pool is None:
        return default_user_config, default_fetch_user_configs, default_is_atrad_fetch

    if not pooled_user_id:
        raise ValueError("Pooled order execution requires a user_id")

    main_user, fetch_users = resolve_pool_order_users(pool, pooled_user_id)
    return main_user, fetch_users, pool.is_atrad


def _resolve_order_just_buy_user_configs(order: Dict[str, Any], global_just_buy_user_configs=None):
    """Resolve effective just-buy users for one order, preferring store overrides."""
    if not order.get("just_buy", False):
        return []
    order_just_buy_users = order.get("just_buy_users") or []
    if order_just_buy_users:
        return load_just_buy_user_specs(order_just_buy_users, "order just-buy user")
    return global_just_buy_user_configs


def _build_just_buy_services(just_buy_user_configs=None):
    """Build just-buy worker services with optional per-user quantity overrides."""
    just_buy_bundles = create_order_bundles(just_buy_user_configs)
    just_buy_clients = [bundle.client for bundle in just_buy_bundles] or None
    just_buy_services = (
        [
            {
                "service": bundle.service,
                "quantity_override": bundle.quantity_override,
            }
            for bundle in just_buy_bundles
        ]
        or None
    )
    return just_buy_clients, just_buy_services


def execute_manual_order(user_config, args, fetch_user_configs=None, is_atrad_fetch: bool = False, just_buy_user_configs=None) -> Dict[str, Any]:
    """Execute a manual order from parsed CLI arguments."""
    resolved_ticker = None
    ticker_name = None

    if args.ticker:
        try:
            resolved_ticker = resolve_ticker(args.ticker, fetch_user_configs, is_atrad_fetch)
            ticker_name = resolved_ticker.name
            logger.info(f"Fetch ID for '{args.ticker}': {resolved_ticker.fetch_id}")
            if resolved_ticker.fetch_host:
                logger.debug(f"Fetch ID resolved for host: {resolved_ticker.fetch_host}")
        except Exception as exc:
            logger.warning(f"Could not resolve fetch_id for ticker '{args.ticker}': {exc}")
            try:
                ticker_name = lookup_ticker_name(args.ticker)
            except Exception:
                ticker_name = None

    order_params = build_manual_order_params(args, resolved_ticker=resolved_ticker)

    scheduled_time = getattr(args, "time", None)

    mode = "SCHEDULED" if scheduled_time else "IMMEDIATE"
    if args.ipo_trigger:
        mode += " (IPO TRIGGER)"
    elif args.ipo_trigger_low:
        mode += " (IPO TRIGGER LOW)"
    elif args.trigger_sell:
        mode += " (TRIGGER SELL)"

    log_standard_order_plan(
        user_id=user_config.user_id,
        mode=mode,
        is_sell=args.sell,
        ticker=args.ticker,
        ticker_name=ticker_name,
        security_id=args.security_id,
        exchange_security_id=args.exchange_security_id,
        price=args.price,
        quantity=args.quantity,
        limit_price=args.limit,
        scheduled_time=scheduled_time,
    )
    logger.info("=" * 60)

    kwargs = {
        "user_config": user_config,
        "order_params": order_params,
        "scheduled_time": scheduled_time,
        "fetch_user_configs": fetch_user_configs,
        "is_atrad_fetch": is_atrad_fetch,
    }
    if just_buy_user_configs:
        kwargs["just_buy_user_configs"] = just_buy_user_configs
    return execute_order_for_user(**kwargs)


def execute_order_for_user(user_config, order_params: Dict[str, Any], scheduled_time: str = None, fetch_user_configs=None, is_atrad_fetch: bool = False, just_buy_user_configs=None) -> Dict[str, Any]:
    """Execute an order for a single user."""
    user_id = user_config.user_id

    try:
        logger.info(f"[{user_id}] Starting order execution")
        fetch_clients = create_fetch_clients(fetch_user_configs, is_atrad_fetch)
        log_fetch_client_summary(user_id, fetch_user_configs, fetch_clients, is_atrad_fetch)
        just_buy_clients, just_buy_services = _build_just_buy_services(just_buy_user_configs)

        platform = create_order_client_and_service(user_config)
        if scheduled_time:
            schedule_kwargs = {
                "time_str": scheduled_time,
                "order_func": platform.service.execute_order,
                "main_client": platform.client,
                "fetch_clients": fetch_clients,
                "user_id": user_id,
                **order_params,
            }
            if just_buy_clients:
                schedule_kwargs["just_buy_clients"] = just_buy_clients
            if just_buy_services:
                schedule_kwargs["just_buy_services"] = just_buy_services
            result = OrderScheduler.schedule_order(**schedule_kwargs)
        else:
            execute_kwargs = {"fetch_clients": fetch_clients, **order_params}
            if just_buy_services:
                execute_kwargs["just_buy_services"] = just_buy_services
            result = platform.service.execute_order(**execute_kwargs)

        logger.info(f"[{user_id}] Order execution completed successfully")
        return result
    except Exception as exc:
        logger.error(f"[{user_id}] Order execution failed: {str(exc)}", exc_info=True)
        raise


def execute_multi_queue_group(
    user_config,
    orders: List[Dict[str, Any]],
    order_store,
    fetch_user_configs=None,
    is_atrad_fetch: bool = False,
    just_buy_user_configs=None,
    user_pool: Optional[UserPool] = None,
) -> Dict[str, Any]:
    """Execute a multi-queue order group."""
    logger.info(f"Preparing multi-queue execution for {len(orders)} orders:")
    for order in orders:
        logger.info(f"  - {order['id']} ({order['ticker']})")

    monitoring_user_config = user_config
    monitoring_fetch_user_configs = fetch_user_configs
    monitoring_is_atrad_fetch = is_atrad_fetch
    if user_pool is not None:
        monitoring_user_config = user_pool.ordered_users[0]
        monitoring_fetch_user_configs = user_pool.ordered_users
        monitoring_is_atrad_fetch = user_pool.is_atrad

    platform = create_order_client_and_service(monitoring_user_config)
    if not monitoring_fetch_user_configs:
        raise ValueError("Fetch user configs required for multi-queue mode")
    fetch_clients = create_fetch_clients(monitoring_fetch_user_configs, monitoring_is_atrad_fetch)
    prepared_orders = []
    for order in orders:
        order = dict(order)
        try:
            resolved = resolve_ticker(order['ticker'], monitoring_fetch_user_configs, monitoring_is_atrad_fetch)
            order['security_id'] = resolved.security_id
            order['exchange_security_id'] = resolved.exchange_security_id
            order['fetch_id'] = resolved.fetch_id
            order['symbol'] = resolved.symbol
            logger.info(
                f"  {order['id']}: security_id={resolved.security_id}, "
                f"exchange_security_id={resolved.exchange_security_id}, fetch_id={resolved.fetch_id}"
            )
        except Exception as exc:
            raise ValueError(f"Ticker lookup failed for '{order['ticker']}': {exc}")

        effective_just_buy_user_configs = _resolve_order_just_buy_user_configs(
            order,
            global_just_buy_user_configs=just_buy_user_configs,
        )
        if effective_just_buy_user_configs:
            _just_buy_clients, just_buy_services = _build_just_buy_services(effective_just_buy_user_configs)
            order["just_buy_services"] = just_buy_services
        prepared_orders.append(order)

    orders = prepared_orders

    scheduled_time = orders[0].get('time') if orders else None
    if scheduled_time:
        different_times = [order['id'] for order in orders if order.get('time') != scheduled_time]
        if different_times:
            logger.warning(
                f"Multi-queue group has orders with different scheduled times. "
                f"Using first order's time ({scheduled_time}). "
                f"Orders with different times: {', '.join(different_times)}"
            )
        logger.info(f"Multi-queue group has scheduled time: {scheduled_time}")
        logger.info(f"All orders in this group will execute at: {scheduled_time}")

    try:
        def execute_order_with_resolved_user(order: Dict[str, Any], already_triggered: bool) -> Dict[str, Any]:
            if user_pool is None:
                return platform.service._execute_single_ipo_order(order, fetch_clients, already_triggered)

            pooled_user_id = str(order.get("user_id") or "").strip()
            if not pooled_user_id:
                raise ValueError(f"Order '{order.get('id', 'unknown')}' is missing required field 'user_id' for --pool-users mode")
            order_user_config, order_fetch_user_configs, order_is_atrad_fetch = _resolve_execution_users(
                pool=user_pool,
                pooled_user_id=pooled_user_id,
                default_user_config=monitoring_user_config,
                default_fetch_user_configs=monitoring_fetch_user_configs,
                default_is_atrad_fetch=monitoring_is_atrad_fetch,
            )
            order_platform = create_order_client_and_service(order_user_config)
            order_fetch_clients = create_fetch_clients(order_fetch_user_configs, order_is_atrad_fetch)
            return order_platform.service._execute_single_ipo_order(order, order_fetch_clients, already_triggered)

        def handle_order_complete(order_id: str, success: bool, _error: Exception | None = None) -> None:
            if success:
                order_store.mark_success(order_id)
                logger.info(f"Order '{order_id}' marked as successful in store")
            else:
                order_store.mark_failed(order_id)
                logger.error(f"Order '{order_id}' marked as failed in store")

        if scheduled_time:
            def execute_multi_queue(**kwargs):
                active_fetch_clients = kwargs.get('fetch_clients', fetch_clients)
                return platform.service._execute_multi_queue_ipo_trigger(
                    orders=orders,
                    fetch_clients=active_fetch_clients,
                    on_order_complete=handle_order_complete,
                    order_executor=execute_order_with_resolved_user,
                )

            result = OrderScheduler.schedule_order(
                time_str=scheduled_time,
                order_func=execute_multi_queue,
                main_client=platform.client,
                fetch_clients=fetch_clients,
                user_id=monitoring_user_config.user_id,
            )
        else:
            result = platform.service._execute_multi_queue_ipo_trigger(
                orders=orders,
                fetch_clients=fetch_clients,
                on_order_complete=handle_order_complete,
                order_executor=execute_order_with_resolved_user,
            )

        if len(result['failed_orders']) > 0:
            logger.warning(
                f"Multi-queue group completed with failures: "
                f"{len(result['successful_orders'])} successful, {len(result['failed_orders'])} failed"
            )
            raise ValueError(f"Multi-queue had {len(result['failed_orders'])} failed order(s): {', '.join(result['failed_orders'])}")

        logger.info(f"Multi-queue group completed successfully - all {len(result['successful_orders'])} orders succeeded")
        return result
    except Exception as exc:
        logger.error(f"Multi-queue execution failed: {str(exc)}")
        raise


def execute_trigger_sell_queue_group(
    user_config,
    orders: List[Dict[str, Any]],
    order_store,
    fetch_user_configs=None,
    is_atrad_fetch: bool = False,
    user_pool: Optional[UserPool] = None,
) -> Dict[str, Any]:
    """Execute a trigger-sell queue group with rotating trigger checks."""
    logger.info(f"Preparing trigger-sell queue execution for {len(orders)} orders:")
    for order in orders:
        logger.info(f"  - {order['id']} ({order['ticker']})")

    monitoring_user_config = user_config
    monitoring_fetch_user_configs = fetch_user_configs
    monitoring_is_atrad_fetch = is_atrad_fetch
    if user_pool is not None:
        monitoring_user_config = user_pool.ordered_users[0]
        monitoring_fetch_user_configs = user_pool.ordered_users
        monitoring_is_atrad_fetch = user_pool.is_atrad

    if not monitoring_fetch_user_configs:
        raise ValueError("Fetch user configs required for trigger-sell queue mode")

    platform = create_order_client_and_service(monitoring_user_config)
    fetch_clients = create_fetch_clients(monitoring_fetch_user_configs, monitoring_is_atrad_fetch)
    if not fetch_clients:
        raise ValueError("At least one fetch client is required for trigger-sell queue mode")

    prepared_orders = []
    for order in orders:
        try:
            resolved = resolve_ticker(order["ticker"], monitoring_fetch_user_configs, monitoring_is_atrad_fetch)
            enriched_order = dict(order)
            enriched_order["security_id"] = resolved.security_id
            enriched_order["exchange_security_id"] = resolved.exchange_security_id
            enriched_order["fetch_id"] = resolved.fetch_id
            enriched_order["symbol"] = resolved.symbol
            prepared_orders.append(enriched_order)
        except Exception as exc:
            raise ValueError(f"Ticker lookup failed for '{order['ticker']}': {exc}")

    fast_poll_interval_ms = monitoring_user_config.multi_fetch_poll_interval_ms
    slow_poll_interval_ms = getattr(
        monitoring_user_config,
        "multi_fetch_slow_poll_interval_ms",
        fast_poll_interval_ms,
    )
    sleep_duration = max(fast_poll_interval_ms / 10000.0, 0.001)

    def calculate_trigger_sell_targets(order: Dict[str, Any]) -> tuple[float, float]:
        limit_price = order.get("limit")
        sell_price = float(order["price"])
        if limit_price is not None:
            price_levels, _ = calculate_price_levels(sell_price, limit_price)
            second_last_index = len(price_levels) - 2 if len(price_levels) >= 2 else -1
            trigger_price = price_levels[second_last_index] if second_last_index >= 0 else price_levels[0]
            return trigger_price, price_levels[-1]

        trigger_price = math.ceil((sell_price / 1.03) * 10) / 10
        return trigger_price, sell_price

    def place_triggered_sell(order: Dict[str, Any], market_price: float) -> Dict[str, Any]:
        trigger_price, final_sell_price = calculate_trigger_sell_targets(order)
        order_user_config = monitoring_user_config
        order_is_atrad_fetch = monitoring_is_atrad_fetch
        if user_pool is not None:
            pooled_user_id = str(order.get("user_id") or "").strip()
            if not pooled_user_id:
                raise ValueError(
                    f"Order '{order.get('id', 'unknown')}' is missing required field 'user_id' for --pool-users mode"
                )
            order_user_config, _order_fetch_user_configs, order_is_atrad_fetch = _resolve_execution_users(
                pool=user_pool,
                pooled_user_id=pooled_user_id,
                default_user_config=monitoring_user_config,
                default_fetch_user_configs=monitoring_fetch_user_configs,
                default_is_atrad_fetch=monitoring_is_atrad_fetch,
            )
        order_platform = create_order_client_and_service(order_user_config)
        logger.info(
            f"[{order_user_config.user_id}] Trigger-sell queue order triggered: {order['id']} "
            f"({order['ticker']}) LTP={market_price} >= Trigger={trigger_price}. "
            f"Placing SELL at Rs. {final_sell_price}"
        )

        if isinstance(order_user_config, ATRADUserConfig) or order_is_atrad_fetch:
            return order_platform.service._place_single_order(
                price=final_sell_price,
                quantity=order["quantity"],
                symbol=order["symbol"],
                side="SELL",
                market_price=market_price,
            )

        return order_platform.service._place_single_order(
            price=final_sell_price,
            quantity=order["quantity"],
            security_id=order["security_id"],
            exchange_security_id=order["exchange_security_id"],
            buy_or_sell=2,
            order_type="LMT",
            order_validity="DAY",
            market_price=market_price,
        )

    def execute_group() -> Dict[str, Any]:
        remaining_orders = list(prepared_orders)
        responses = []
        successful_orders = []
        failed_orders = []

        while remaining_orders:
            symbols_config = []
            for order in remaining_orders:
                trigger_price, _ = calculate_trigger_sell_targets(order)
                symbol_config = SymbolConfig(
                    symbol=order["symbol"] if is_atrad_fetch else order["ticker"],
                    switch_threshold=trigger_price,
                    order_id=order["id"],
                    security_id=order.get("security_id"),
                    fetch_security_id=order.get("fetch_id"),
                )
                symbols_config.append(symbol_config)
                logger.info(
                    f"[{monitoring_user_config.user_id}] Trigger-sell queue order: {order['id']} "
                    f"({symbol_config.symbol}) trigger_price=Rs. {trigger_price}"
                )

            multi_fetcher = MultiSymbolSequentialPriceFetcher(
                symbols_config=symbols_config,
                fetch_clients=fetch_clients,
                poll_interval_ms=slow_poll_interval_ms,
                user_id=monitoring_user_config.user_id,
                is_atrad=monitoring_is_atrad_fetch,
            )
            current_poll_interval_ms = slow_poll_interval_ms

            multi_fetcher.start()
            try:
                logger.info(f"[{monitoring_user_config.user_id}] Waiting for next trigger-sell queue order to trigger...")
                while True:
                    current_ltps = multi_fetcher.get_all_ltps()
                    previous_poll_interval_ms = current_poll_interval_ms
                    current_poll_interval_ms = sync_multi_symbol_poll_interval_ms(
                        fetcher=multi_fetcher,
                        latest_ltps=current_ltps,
                        symbols_config=symbols_config,
                        current_poll_interval_ms=current_poll_interval_ms,
                        slow_poll_interval_ms=slow_poll_interval_ms,
                        fast_poll_interval_ms=fast_poll_interval_ms,
                    )
                    if current_poll_interval_ms != previous_poll_interval_ms:
                        mode_label = "FAST" if current_poll_interval_ms == fast_poll_interval_ms else "SLOW"
                        logger.info(
                            f"[{monitoring_user_config.user_id}] Trigger-sell queue switched to {mode_label} polling "
                            f"({current_poll_interval_ms}ms)"
                        )
                    if multi_fetcher.get_priority_symbol() is not None:
                        break
                    time.sleep(sleep_duration)
                priority_symbol = multi_fetcher.get_priority_symbol()
                all_ltps = multi_fetcher.get_all_ltps()
            finally:
                multi_fetcher.stop()

            ltps_str = ", ".join([f"{sym}={ltp if ltp else 'N/A'}" for sym, ltp in all_ltps.items()])
            logger.info(f"[{monitoring_user_config.user_id}] Trigger-sell queue LTPs: {ltps_str}")

            triggered_order = None
            remaining_after_trigger = []
            for order in remaining_orders:
                symbol = order["symbol"] if is_atrad_fetch else order["ticker"]
                if symbol == priority_symbol and triggered_order is None:
                    triggered_order = order
                else:
                    remaining_after_trigger.append(order)

            if triggered_order is None:
                raise ValueError(f"Triggered symbol {priority_symbol} not found in trigger-sell queue orders")

            current_ltp = all_ltps.get(priority_symbol)
            try:
                response = place_triggered_sell(triggered_order, current_ltp)
                responses.append(response)
                successful_orders.append(triggered_order["id"])
                order_store.mark_success(triggered_order["id"])
                logger.info(f"Order '{triggered_order['id']}' marked as successful in store")
            except Exception as exc:
                failed_orders.append(triggered_order["id"])
                order_store.mark_failed(triggered_order["id"])
                logger.error(f"Trigger-sell queue order '{triggered_order['id']}' failed: {str(exc)}")

            remaining_orders = remaining_after_trigger

        if failed_orders:
            raise ValueError(
                f"Trigger-sell queue had {len(failed_orders)} failed order(s): {', '.join(failed_orders)}"
            )

        return {
            "responses": responses,
            "successful_orders": successful_orders,
            "failed_orders": failed_orders,
        }

    scheduled_time = prepared_orders[0].get("time") if prepared_orders else None
    if scheduled_time:
        return OrderScheduler.schedule_order(
            time_str=scheduled_time,
            order_func=lambda **_kwargs: execute_group(),
            main_client=platform.client,
            fetch_clients=fetch_clients,
            user_id=monitoring_user_config.user_id,
        )

    return execute_group()


def execute_ipo_sell_buy_trigger(seller_config, buyer_config, fetch_user_configs: List[Any], is_atrad_fetch: bool, ticker: str, security_id: int, exchange_security_id: int, price: float, quantity: int, sell_quantity: int, sell_pre_wait_ms: int, limit_price: Optional[float] = None, just_buy_interval_ms: int = 100, just_buy_timeout: int = 5, scheduled_time: str = None) -> Dict[str, Any]:
    """Execute IPO sell-buy-trigger mode."""
    logger.info("=" * 70)
    logger.info("IPO SELL-BUY-TRIGGER MODE")
    logger.info("=" * 70)

    is_seller_atrad = isinstance(seller_config, ATRADUserConfig)
    is_buyer_atrad = isinstance(buyer_config, ATRADUserConfig)
    logger.info(f"Seller: {seller_config.user_id} ({'ATRAD' if is_seller_atrad else 'TMS'})")
    logger.info(f"Buyer: {buyer_config.user_id} ({'ATRAD' if is_buyer_atrad else 'TMS'})")
    logger.info(f"Stock: {ticker}, Price: Rs. {price}, Limit: {limit_price or 'None'}")
    logger.info(f"Buy Quantity: {quantity}, Sell Quantity: {sell_quantity}")
    logger.info(f"Sell Pre-Wait: {sell_pre_wait_ms}ms")

    if seller_config.user_id == buyer_config.user_id:
        logger.warning(
            f"Seller and buyer are the same user: {seller_config.user_id}. "
            f"This is allowed but may have account limitations."
        )

    fetch_clients = create_fetch_clients(fetch_user_configs, is_atrad_fetch) or []
    seller_platform = create_order_client_and_service(seller_config)
    buyer_platform = create_order_client_and_service(buyer_config)

    exec_params = {
        'buyer_service': buyer_platform.service,
        'ticker': ticker,
        'security_id': security_id,
        'exchange_security_id': exchange_security_id,
        'symbol': ticker.upper() if ticker else None,
        'base_price': price,
        'buy_quantity': quantity,
        'sell_quantity': sell_quantity,
        'sell_pre_wait_ms': sell_pre_wait_ms,
        'limit_price': limit_price,
        'just_buy_interval_ms': just_buy_interval_ms,
        'just_buy_timeout': just_buy_timeout,
    }

    if scheduled_time:
        return OrderScheduler.schedule_order_sell_buy(
            time_str=scheduled_time,
            order_func=seller_platform.service._execute_ipo_sell_buy_trigger,
            seller_client=seller_platform.client,
            buyer_client=buyer_platform.client,
            fetch_clients=fetch_clients,
            user_id=seller_config.user_id,
            **exec_params,
        )

    return seller_platform.service._execute_ipo_sell_buy_trigger(fetch_clients=fetch_clients, **exec_params)


def execute_from_order_store(
    user_config,
    order_store_path: str,
    fetch_user_configs=None,
    just_buy_user_configs=None,
    is_atrad_fetch: bool = False,
    start_time: Optional[str] = None,
    user_pool: Optional[UserPool] = None,
) -> Dict[str, Any]:
    """Execute queued orders from an order store."""
    logger.info(f"Loading order store from {order_store_path}")
    order_store = OrderStore(order_store_path)
    logger.info("\n" + order_store.get_order_summary())

    orders = order_store.get_executable_orders()
    if not orders:
        raise ValueError("No orders marked for execution in order store")

    validated_orders = [order_store.validate_order(order) for order in orders]
    if user_pool is not None:
        validate_pool_orders(validated_orders, user_pool)

    logger.info(f"Found {len(validated_orders)} order(s) in execution queue")
    logger.info("=" * 70)

    last_result = None
    queue_groups = defaultdict(list)
    for order in validated_orders:
        queue_groups[order['queue_id']].append(order)

    total_executed = 0
    for queue_id in sorted(queue_groups.keys()):
        group_orders = queue_groups[queue_id]
        if total_executed == 0 and start_time and not group_orders[0].get('time'):
            group_orders[0]['time'] = start_time

        is_multi_queue = group_orders[0].get('multi_queue', False)
        is_trigger_sell_queue = group_orders[0].get('trigger_sell_queue', False)
        if is_multi_queue and len(group_orders) > 1:
            group_user_id = group_orders[0].get("user_id")
            active_user_config, active_fetch_user_configs, active_is_atrad_fetch = _resolve_execution_users(
                pool=user_pool,
                pooled_user_id=group_user_id,
                default_user_config=user_config,
                default_fetch_user_configs=fetch_user_configs,
                default_is_atrad_fetch=is_atrad_fetch,
            )
            logger.info("")
            logger.info(f"Queue {queue_id}: MULTI-QUEUE MODE ({len(group_orders)} orders)")
            logger.info("=" * 70)
            try:
                last_result = execute_multi_queue_group(
                    user_config=active_user_config,
                    orders=group_orders,
                    order_store=order_store,
                    fetch_user_configs=active_fetch_user_configs,
                    is_atrad_fetch=active_is_atrad_fetch,
                    just_buy_user_configs=just_buy_user_configs,
                    user_pool=user_pool,
                )
                total_executed += len(group_orders)
            except Exception as exc:
                logger.error(f"Multi-queue group (Queue {queue_id}) failed: {str(exc)}")
                continue
        elif is_trigger_sell_queue and len(group_orders) > 1:
            group_user_id = group_orders[0].get("user_id")
            active_user_config, active_fetch_user_configs, active_is_atrad_fetch = _resolve_execution_users(
                pool=user_pool,
                pooled_user_id=group_user_id,
                default_user_config=user_config,
                default_fetch_user_configs=fetch_user_configs,
                default_is_atrad_fetch=is_atrad_fetch,
            )
            logger.info("")
            logger.info(f"Queue {queue_id}: TRIGGER-SELL QUEUE MODE ({len(group_orders)} orders)")
            logger.info("=" * 70)
            try:
                last_result = execute_trigger_sell_queue_group(
                    user_config=active_user_config,
                    orders=group_orders,
                    order_store=order_store,
                    fetch_user_configs=active_fetch_user_configs,
                    is_atrad_fetch=active_is_atrad_fetch,
                    user_pool=user_pool,
                )
                total_executed += len(group_orders)
            except Exception as exc:
                logger.error(f"Trigger-sell queue group (Queue {queue_id}) failed: {str(exc)}")
                continue
        else:
            for idx, order in enumerate(group_orders, 1):
                order_id = order['id']
                total_executed += 1
                logger.info(f"Executing order {total_executed}/{len(orders)} (Queue ID: {queue_id}): {order_id}")
            logger.info("=" * 70)

            try:
                active_user_config, active_fetch_user_configs, active_is_atrad_fetch = _resolve_execution_users(
                    pool=user_pool,
                    pooled_user_id=order.get("user_id"),
                    default_user_config=user_config,
                    default_fetch_user_configs=fetch_user_configs,
                    default_is_atrad_fetch=is_atrad_fetch,
                )

                resolved = resolve_ticker(order['ticker'], active_fetch_user_configs, active_is_atrad_fetch)
                security_id = resolved.security_id
                exchange_security_id = resolved.exchange_security_id
                fetch_id = resolved.fetch_id
                logger.info(
                    f"Ticker '{order['ticker']}' resolved to "
                    f"security_id={security_id}, exchange_security_id={exchange_security_id}, fetch_id={fetch_id}"
                )
                if resolved.fetch_host:
                    logger.debug(f"Fetch ID resolved for host: {resolved.fetch_host}")
            except (FileNotFoundError, ValueError) as exc:
                order_store.mark_failed(order_id)
                raise ValueError(f"Ticker lookup failed for '{order['ticker']}': {exc}")

            ipo_sell_buy_trigger_mode = order['mode'] == 'ipo-sell-buy-trigger'

            fetch_error = get_fetch_user_error(order["mode"])
            if fetch_error and not active_fetch_user_configs:
                order_store.mark_failed(order_id)
                raise ValueError(fetch_error)

            if ipo_sell_buy_trigger_mode:
                seller_config = load_trader_config(order['seller_config'], "seller")
                buyer_config = load_trader_config(order['buyer_config'], "buyer")
                logger.info("Execution Mode: IPO-SELL-BUY-TRIGGER")
                logger.info(f"Seller: {seller_config.user_id}")
                logger.info(f"Buyer: {buyer_config.user_id}")
                logger.info(f"Ticker: {order['ticker']}")
                logger.info(f"Security ID: {security_id}")
                logger.info(f"Exchange Security ID: {exchange_security_id}")
                logger.info(f"Buy Price: {order['price']}, Buy Quantity: {order['quantity']}")
                logger.info(f"Sell Quantity: {order['sell_quantity']}")
                logger.info(f"Sell Pre-Wait: {order['sell_pre_wait_ms']}ms")
                if order['limit']:
                    logger.info(f"Limit: {order['limit']}")
                if order['time']:
                    logger.info(f"Scheduled Time: {order['time']}")
                logger.info("=" * 70)

                try:
                    result = execute_ipo_sell_buy_trigger(
                        seller_config=seller_config,
                        buyer_config=buyer_config,
                        fetch_user_configs=fetch_user_configs,
                        is_atrad_fetch=is_atrad_fetch,
                        ticker=order['ticker'],
                        security_id=security_id,
                        exchange_security_id=exchange_security_id,
                        price=order['price'],
                        quantity=order['quantity'],
                        sell_quantity=order['sell_quantity'],
                        sell_pre_wait_ms=order['sell_pre_wait_ms'],
                        limit_price=order['limit'],
                        just_buy_interval_ms=order.get('just_buy_interval_ms', 100),
                        just_buy_timeout=order.get('just_buy_timeout', 5),
                        scheduled_time=order['time'],
                    )
                    order_store.mark_success(order_id)
                    logger.info(f"Order '{order_id}' marked as successful in store")
                    last_result = result
                except Exception as exc:
                    order_store.mark_failed(order_id)
                    logger.error(f"Order '{order_id}' failed: {str(exc)}")
                    if idx < len(group_orders):
                        logger.warning("Continuing to next order in queue despite failure...")
                        logger.info("")
                    else:
                        raise
            else:
                order_params = build_store_order_params(order, resolved)
                mode_str = order["mode"].upper()
                log_standard_order_plan(
                    user_id=active_user_config.user_id,
                    mode=mode_str,
                    is_sell=order["sell"],
                    ticker=order["ticker"],
                    security_id=security_id,
                    exchange_security_id=exchange_security_id,
                    price=order["price"],
                    quantity=order["quantity"],
                    limit_price=order["limit"],
                    scheduled_time=order["time"]
                )
                logger.info("=" * 70)

                try:
                    execute_kwargs = {
                        "user_config": active_user_config,
                        "order_params": order_params,
                        "scheduled_time": order['time'],
                        "fetch_user_configs": active_fetch_user_configs,
                        "is_atrad_fetch": active_is_atrad_fetch,
                    }
                    effective_just_buy_user_configs = _resolve_order_just_buy_user_configs(
                        order,
                        global_just_buy_user_configs=just_buy_user_configs,
                    )
                    if effective_just_buy_user_configs:
                        execute_kwargs["just_buy_user_configs"] = effective_just_buy_user_configs
                    result = execute_order_for_user(**execute_kwargs)
                    order_store.mark_success(order_id)
                    logger.info(f"Order '{order_id}' marked as successful in store")
                    last_result = result
                except Exception as exc:
                    order_store.mark_failed(order_id)
                    logger.error(f"Order '{order_id}' failed: {str(exc)}")
                    if idx < len(group_orders):
                        logger.warning("Continuing to next order in queue despite failure...")
                        logger.info("")
                    else:
                        raise

            if idx < len(group_orders):
                logger.info(f"Order {idx}/{len(group_orders)} completed. Proceeding to next order in queue...")
                logger.info("")

    logger.info("=" * 70)
    logger.info(f"Queue execution completed: {len(orders)} order(s) processed")
    logger.info("=" * 70)
    return last_result
