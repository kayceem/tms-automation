"""Specialized workflow helpers for trigger-sell and ipo-trigger-low modes."""

import math
import time
from typing import Any, Dict, List, Optional

def execute_trigger_sell(
    service: Any,
    sell_price: float,
    order_quantity: int,
    fetch_clients: List[Any],
    fetch_security_id: Optional[int] = None,
    ticker: Optional[str] = None,
    limit_price: Optional[float] = None,
    **platform_params,
) -> Optional[Dict[str, Any]]:
    """Execute the trigger-sell workflow."""
    identifier = service._get_identifier_for_logging(**platform_params)

    if fetch_security_id is None:
        fetch_security_id = platform_params.get("security_id") or platform_params.get("symbol")

    if limit_price:
        service.logger.info(
            f"[{service.user_id}] TRIGGER SELL MODE (with limit): "
            f"{identifier}, Qty={order_quantity}, "
            f"Base price: Rs. {sell_price}, Limit: Rs. {limit_price}"
        )
        price_levels, actual_increments = service._calculate_price_levels(sell_price, limit_price)

        service.logger.info(f"[{service.user_id}] Calculated {len(price_levels)} ladder levels:")
        for i, price in enumerate(price_levels):
            increment = actual_increments[i] if i < len(actual_increments) else -1
            if increment == 15:
                service.logger.debug(f"[{service.user_id}] Level {i+1}: Rs. {price} (Limit +15%)")
            else:
                service.logger.debug(f"[{service.user_id}] Level {i+1}: Rs. {price} (+{increment}%)")

        second_last_index = len(price_levels) - 2 if len(price_levels) >= 2 else -1
        trigger_price = price_levels[second_last_index] if second_last_index >= 0 else price_levels[0]
        final_sell_price = price_levels[-1]

        service.logger.info(
            f"[{service.user_id}] Will monitor for LTP >= Rs. {trigger_price} (level {second_last_index + 1})"
        )
        service.logger.info(
            f"[{service.user_id}] Will place sell order at Rs. {final_sell_price} when triggered"
        )
    else:
        trigger_price = sell_price / 1.03
        trigger_price = math.ceil(trigger_price * 10) / 10
        final_sell_price = sell_price

        service.logger.info(
            f"[{service.user_id}] TRIGGER SELL MODE (legacy): "
            f"{identifier}, Qty={order_quantity}, "
            f"Sell price: Rs. {sell_price}, Trigger price: Rs. {trigger_price}"
        )
        service.logger.info(
            f"[{service.user_id}] Will place sell order at Rs. {final_sell_price} when LTP >= Rs. {trigger_price}"
        )

    fast_poll_interval_ms = getattr(service.client.user_config, "trigger_sell_poll_interval_ms", 500)
    slow_poll_interval_ms = getattr(
        service.client.user_config,
        "trigger_sell_slow_poll_interval_ms",
        500,
    )
    near_trigger_threshold = math.floor((sell_price * 0.94) * 10) / 10
    current_poll_interval_ms = slow_poll_interval_ms
    price_fetcher = service._setup_price_fetcher(
        fetch_clients=fetch_clients,
        fetch_security_id=fetch_security_id,
        symbol=platform_params.get("symbol"),
        ticker=ticker,
        poll_interval_ms=current_poll_interval_ms,
    )

    token_manager = service._setup_token_manager()
    if token_manager:
        refresh_interval = service.client.user_config.trigger_mode_refresh_interval_seconds
        service.logger.info(
            f"[{service.user_id}] Token refresh started (interval: {refresh_interval}s)"
        )

    order_placed = False
    last_response = None

    try:
        service.logger.info(
            f"[{service.user_id}] Starting LTP monitoring "
            f"(slow={slow_poll_interval_ms}ms, fast={fast_poll_interval_ms}ms, near-threshold=Rs. {near_trigger_threshold})"
        )

        while not order_placed:
            ltp = price_fetcher.get_latest_ltp()

            if ltp is None:
                service.logger.debug(f"[{service.user_id}] Waiting for first LTP...")
                time.sleep(current_poll_interval_ms / 1000)
                continue

            target_poll_interval_ms = (
                fast_poll_interval_ms if ltp >= near_trigger_threshold else slow_poll_interval_ms
            )
            if target_poll_interval_ms != current_poll_interval_ms:
                current_poll_interval_ms = target_poll_interval_ms
                if hasattr(price_fetcher, "update_poll_settings"):
                    price_fetcher.update_poll_settings(current_poll_interval_ms, enable_cooldown=False)
                mode_label = "FAST" if current_poll_interval_ms == fast_poll_interval_ms else "SLOW"
                service.logger.info(
                    f"[{service.user_id}] Trigger-sell switched to {mode_label} polling "
                    f"({current_poll_interval_ms}ms) at LTP Rs. {ltp}"
                )

            if ltp >= trigger_price:
                service.logger.info(
                    f"[{service.user_id}] TRIGGER ACTIVATED: LTP Rs. {ltp} >= Trigger Rs. {trigger_price}"
                )
                service.logger.info(
                    f"[{service.user_id}] Placing sell order at Rs. {final_sell_price} x {order_quantity}"
                )

                try:
                    sell_params = platform_params.copy()
                    if "buy_or_sell" in sell_params:
                        sell_params["buy_or_sell"] = 2
                    if "side" in sell_params:
                        sell_params["side"] = "SELL"

                    price_fetcher.pause()
                    sell_params["market_price"] = ltp

                    response = service._place_single_order(
                        price=final_sell_price,
                        quantity=order_quantity,
                        **sell_params,
                    )

                    price_fetcher.resume()

                    service.logger.info(f"[{service.user_id}] Sell order placed successfully")
                    order_placed = True
                    last_response = response
                except Exception as exc:
                    price_fetcher.resume()
                    service.logger.error(f"[{service.user_id}] Failed to place sell order: {str(exc)}")
                    return None
            else:
                service.logger.debug(
                    f"[{service.user_id}] LTP Rs. {ltp} < Trigger Rs. {trigger_price} - waiting..."
                )

            time.sleep(current_poll_interval_ms / 1000)

    finally:
        price_fetcher.stop()
        service._cleanup_token_manager(token_manager)

    service.logger.info(f"[{service.user_id}] TRIGGER SELL COMPLETE")
    return last_response


def execute_ipo_trigger_low(
    service: Any,
    base_price: float,
    order_quantity: int,
    fetch_clients: List[Any],
    limit_price: Optional[float] = None,
    fetch_security_id: Optional[int] = None,
    ticker: Optional[str] = None,
    timeout_ipo_trigger_low: Optional[int] = None,
    **platform_params,
) -> Optional[Dict[str, Any]]:
    """Execute the ipo-trigger-low workflow."""
    security_id = platform_params.get("security_id")
    symbol = platform_params.get("symbol")
    fetch_security_id = fetch_security_id or security_id or symbol

    price_levels, actual_decrements = service._calculate_lower_price_levels(base_price, limit_price)
    trigger_price = price_levels[0]
    order_price = price_levels[1]

    service.logger.info("=" * 70)
    service.logger.info("IPO TRIGGER LOW MODE")
    service.logger.info("=" * 70)
    service.logger.info(f"Base Price: Rs. {base_price}")
    if limit_price:
        service.logger.info(f"Limit Price: Rs. {limit_price}")
    service.logger.info(f"Trigger Price (-{actual_decrements[0]}%): Rs. {trigger_price}")
    service.logger.info(f"Order Price (-{actual_decrements[1]}%): Rs. {order_price}")
    service.logger.info(f"Quantity: {order_quantity}")
    if timeout_ipo_trigger_low:
        service.logger.info(f"Timeout: {timeout_ipo_trigger_low}s")
    service.logger.info(f"Security: {service._get_identifier_for_logging(**platform_params)}")
    service.logger.info("=" * 70)

    poll_interval_ms = service.client.user_config.trigger_mode_slow_poll_interval_ms
    price_fetcher = service._setup_price_fetcher(
        fetch_clients, fetch_security_id, symbol, ticker, poll_interval_ms
    )
    sleep_duration = 0.005
    token_manager = service._setup_token_manager()
    last_response = None

    try:
        price_fetcher.start()
        start_time = time.time()
        timeout_msg = f" (timeout: {timeout_ipo_trigger_low}s)" if timeout_ipo_trigger_low else ""

        service.logger.info(
            f"[{service.user_id}] Monitoring LTP... "
            f"Will place order at Rs. {order_price} when LTP <= Rs. {trigger_price}{timeout_msg}"
        )

        triggered = False
        while True:
            if timeout_ipo_trigger_low:
                elapsed = time.time() - start_time
                if elapsed >= timeout_ipo_trigger_low:
                    service.logger.warning(
                        f"[{service.user_id}] TIMEOUT REACHED: {elapsed:.1f}s >= {timeout_ipo_trigger_low}s. "
                        f"Trigger condition not met, exiting."
                    )
                    break

            ltp = price_fetcher.get_latest_ltp()

            if ltp is not None and ltp <= trigger_price:
                service.logger.info(
                    f"[{service.user_id}] TRIGGER REACHED: LTP={ltp} <= Trigger={trigger_price}"
                )
                triggered = True
                break

            time.sleep(sleep_duration)

        if not triggered:
            service.logger.info(f"[{service.user_id}] Skipping order placement - timeout reached")
            return None

        service.logger.info(
            f"[{service.user_id}] Placing order at Rs. {order_price} (Quantity: {order_quantity})"
        )
        if hasattr(price_fetcher, "start_market_details"):
            service.logger.info(f"[{service.user_id}] Starting market details monitoring for order placement")
            price_fetcher.start_market_details()

        ltp = price_fetcher.get_latest_ltp()
        platform_params_with_ltp = {**platform_params, "market_price": ltp}
        try:
            last_response = service._place_single_order(
                price=order_price,
                quantity=order_quantity,
                **platform_params_with_ltp,
            )
            if last_response:
                service.logger.info(
                    f"[{service.user_id}] Order placed successfully: {last_response}"
                )
            else:
                service.logger.warning(
                    f"[{service.user_id}] Order placement returned no response"
                )
        except Exception as exc:
            service.logger.error(
                f"[{service.user_id}] Error placing order: {str(exc)}"
            )
            raise

    except KeyboardInterrupt:
        service.logger.info(f"[{service.user_id}] IPO TRIGGER LOW cancelled by user")
        raise
    except Exception as exc:
        service.logger.error(f"[{service.user_id}] IPO TRIGGER LOW failed: {str(exc)}")
    finally:
        if hasattr(price_fetcher, "stop_market_details"):
            price_fetcher.stop_market_details()
        price_fetcher.stop()
        service._cleanup_token_manager(token_manager)

    return last_response
