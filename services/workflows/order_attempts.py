"""Order attempt and retry helpers extracted from BaseOrderService."""

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
    service.logger.info(
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
