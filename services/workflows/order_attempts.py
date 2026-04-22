"""Order attempt and retry helpers extracted from BaseOrderService."""

import threading
import time
from typing import Any, Dict, List, Optional, Tuple


def place_order_with_retries(
    service: Any,
    price_fetcher: Any,
    target_price: float,
    quantity: int,
    level_display: int,
    total_levels: int,
    ltp: Optional[float],
    platform_params: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Place an order with up to three attempts."""
    service.logger.debug(
        f"[{service.user_id}] Placing order level {level_display}/{total_levels} "
        f"at Rs. {target_price}, Qty={quantity}"
    )

    for attempt in range(1, 4):
        if attempt > 1:
            service.logger.debug(f"[{service.user_id}] Attempt #{attempt}/3")

        try:
            order_params = {**platform_params, "market_price": ltp}
            response = service._place_single_order(
                price=target_price,
                quantity=quantity,
                **order_params,
            )

            if response:
                service.logger.info(
                    f"[{service.user_id}] Order level {level_display} placed successfully"
                )
                if hasattr(price_fetcher, "stop_market_details"):
                    price_fetcher.stop_market_details()
                return response

        except KeyboardInterrupt:
            service.logger.info(f"[{service.user_id}] IPO trigger interrupted by user")
            raise
        except Exception as exc:
            error_msg = str(exc)
            if "401" in error_msg or "Unauthorized" in error_msg:
                service.logger.debug(f"[{service.user_id}] Token issue, retrying")
            elif "400" in error_msg or "Bad Request" in error_msg:
                service.logger.warning(
                    f"[{service.user_id}] Error placing order level {level_display}: {error_msg}"
                )
            else:
                service.logger.error(
                    f"[{service.user_id}] Error placing order level {level_display}: {error_msg}"
                )

            try:
                time.sleep(0.001)
            except KeyboardInterrupt:
                service.logger.info(f"[{service.user_id}] IPO trigger interrupted by user")
                raise

    return None


def _place_direct_ladder_order_via_fetch_thread(
    *,
    service: Any,
    price_fetcher: Any,
    current_level_index: int,
    trigger_price: float,
    price_levels: List[float],
    order_quantity: int,
    base_quantity: Optional[int],
    second_last_index: int,
    skip_second_last: bool,
    double_buy: bool,
    double_buy_quantity: Optional[int],
    platform_params: Dict[str, Any],
) -> Tuple[bool, Optional[Dict[str, Any]], int] | None:
    """Place the ladder order directly from the fetch thread when supported."""
    if not hasattr(price_fetcher, "set_trigger_callback") or not hasattr(price_fetcher, "clear_trigger_callback"):
        return None

    done = threading.Event()
    state: dict[str, Any] = {
        "handled": False,
        "success": False,
        "response": None,
        "next_index": current_level_index + 1,
        "error": None,
    }
    guard = threading.Lock()

    def on_trigger(ltp: float) -> None:
        if ltp is None or ltp < trigger_price:
            return
        with guard:
            if state["handled"]:
                return
            state["handled"] = True

        resolved_level_index = current_level_index
        while resolved_level_index < len(price_levels) - 1 and ltp >= price_levels[resolved_level_index]:
            service.logger.warning(
                f"[{service.user_id}] LTP={ltp} >= Rs. {price_levels[resolved_level_index]}, "
                f"skipping missed level {resolved_level_index + 1}"
            )
            resolved_level_index += 1

        if resolved_level_index == second_last_index and skip_second_last:
            service.logger.info(
                f"[{service.user_id}] Skipping second-to-last level {resolved_level_index + 1} "
                f"(Rs. {price_levels[resolved_level_index]}) as requested"
            )
            resolved_level_index += 1

        target_price = price_levels[resolved_level_index]
        service.logger.debug(
            f"[{service.user_id}] TRIGGERED! LTP={ltp} >= "
            f"Rs. {trigger_price}. Placing order at Rs. {target_price}"
        )

        if hasattr(price_fetcher, "start_market_details"):
            service.logger.debug(f"[{service.user_id}] Starting market details monitoring for order placement")
            price_fetcher.start_market_details()

        is_final = resolved_level_index == len(price_levels) - 1
        qty = order_quantity if is_final else (base_quantity or order_quantity)
        try:
            response = service._place_order_with_retries(
                price_fetcher=price_fetcher,
                target_price=target_price,
                quantity=qty,
                level_display=resolved_level_index + 1,
                total_levels=len(price_levels),
                ltp=ltp,
                platform_params=platform_params,
            )
            state["success"] = bool(response)
            state["response"] = response
            state["next_index"] = resolved_level_index + 1

            if response and double_buy and is_final:
                order_params = {**platform_params, "market_price": ltp}
                service._execute_double_buy(
                    price=target_price,
                    quantity=qty,
                    double_buy_quantity=double_buy_quantity,
                    **order_params,
                )
        except BaseException as exc:  # pragma: no cover - surfaced on caller thread
            state["error"] = exc
        finally:
            done.set()

    price_fetcher.set_trigger_callback(on_trigger)
    try:
        current_ltp = None
        if hasattr(price_fetcher, "get_latest_ltp"):
            current_ltp = price_fetcher.get_latest_ltp()
        if current_ltp is not None and current_ltp >= trigger_price:
            on_trigger(current_ltp)
        done.wait()
    finally:
        price_fetcher.clear_trigger_callback(on_trigger)

    if state["error"] is not None:
        raise state["error"]

    if state["success"]:
        next_index = state["next_index"]
        if next_index < len(price_levels):
            try:
                time.sleep(0.005)
            except KeyboardInterrupt:
                service.logger.info(f"[{service.user_id}] IPO trigger interrupted by user")
                raise
        return True, state["response"], next_index

    service.logger.warning(
        f"[{service.user_id}] Failed to place order at Rs. {price_levels[state['next_index'] - 1]} "
        f"after 3 attempts. Skipping to next level."
    )
    return False, None, state["next_index"]


def place_ladder_order(
    service: Any,
    price_fetcher: Any,
    current_level_index: int,
    price_levels: List[float],
    actual_increments: List[int],
    order_quantity: int,
    base_quantity: Optional[int],
    second_last_index: int,
    skip_second_last: bool,
    double_buy: bool,
    double_buy_quantity: Optional[int],
    platform_params: Dict[str, Any],
) -> Tuple[bool, Optional[Dict[str, Any]], int]:
    """Place one ladder order and return progression state."""
    if current_level_index == second_last_index and skip_second_last:
        service.logger.info(
            f"[{service.user_id}] Skipping second-to-last level {current_level_index + 1} "
            f"(Rs. {price_levels[current_level_index]}) as requested"
        )
        return True, None, current_level_index + 1

    target_price = price_levels[current_level_index]
    increment_pct = actual_increments[current_level_index]

    if current_level_index > 0:
        trigger_price = price_levels[current_level_index - 1]
        direct_result = _place_direct_ladder_order_via_fetch_thread(
            service=service,
            price_fetcher=price_fetcher,
            current_level_index=current_level_index,
            trigger_price=trigger_price,
            price_levels=price_levels,
            order_quantity=order_quantity,
            base_quantity=base_quantity,
            second_last_index=second_last_index,
            skip_second_last=skip_second_last,
            double_buy=double_buy,
            double_buy_quantity=double_buy_quantity,
            platform_params=platform_params,
        )
        if direct_result is not None:
            return direct_result
        ltp, current_level_index = service._wait_for_ladder_trigger(
            price_fetcher=price_fetcher,
            trigger_price=trigger_price,
            increment_pct=increment_pct,
            current_level_index=current_level_index,
            price_levels=price_levels,
            actual_increments=actual_increments,
            second_last_index=second_last_index,
            skip_second_last=skip_second_last,
        )
        target_price = price_levels[current_level_index]
    else:
        service.logger.info(
            f"[{service.user_id}] Placing first order at Rs. {target_price}"
        )
        ltp = None

    is_final = current_level_index == len(price_levels) - 1
    qty = order_quantity if is_final else (base_quantity or order_quantity)

    response = service._place_order_with_retries(
        price_fetcher=price_fetcher,
        target_price=target_price,
        quantity=qty,
        level_display=current_level_index + 1,
        total_levels=len(price_levels),
        ltp=ltp,
        platform_params=platform_params,
    )

    if response:
        if double_buy and is_final:
            order_params = {**platform_params, "market_price": ltp}
            service._execute_double_buy(
                price=target_price,
                quantity=qty,
                double_buy_quantity=double_buy_quantity,
                **order_params,
            )

        if current_level_index + 1 < len(price_levels):
            try:
                time.sleep(0.01)
            except KeyboardInterrupt:
                service.logger.info(f"[{service.user_id}] IPO trigger interrupted by user")
                raise

        return True, response, current_level_index + 1

    service.logger.warning(
        f"[{service.user_id}] Failed to place order at Rs. {target_price} "
        f"after 3 attempts. Skipping to next level."
    )
    return False, None, current_level_index + 1
