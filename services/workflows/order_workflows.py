"""Workflow helpers for IPO trigger execution paths."""

from typing import Any, Dict, List, Optional, Tuple


def execute_no_ladder_mode(
    service: Any,
    price_fetcher: Any,
    price_levels: List[float],
    order_quantity: int,
    just_buy: bool,
    just_buy_interval_ms: int,
    just_buy_timeout: int,
    just_buy_pre_wait_ms: int,
    just_buy_max_requests: Optional[int],
    just_buy_fade_interval_ms: Optional[int],
    just_buy_fade_timeout: Optional[int],
    platform_params: Dict[str, Any],
    already_triggered: bool = False,
) -> Optional[Dict[str, Any]]:
    """Execute the no-ladder IPO workflow."""
    second_last_index = len(price_levels) - 2 if len(price_levels) >= 2 else -1

    if second_last_index < 0:
        service.logger.warning(f"[{service.user_id}] Only one level available, placing immediately")
        try:
            return service._place_single_order(
                price=price_levels[0],
                quantity=order_quantity,
                **platform_params,
            )
        except Exception as exc:
            service.logger.error(f"[{service.user_id}] Failed to place immediate order: {exc}")
            return None

    trigger_price = price_levels[second_last_index]
    final_price = price_levels[-1]

    third_last_index = len(price_levels) - 3 if len(price_levels) >= 3 else -1
    switch_threshold = price_levels[third_last_index] if third_last_index >= 0 else price_levels[0]

    fast_poll_ms = service.client.user_config.trigger_mode_poll_interval_ms
    slow_poll_ms = service.client.user_config.trigger_mode_slow_poll_interval_ms

    just_buy_params = {
        "order_quantity": order_quantity,
        "interval_ms": just_buy_interval_ms,
        "timeout": just_buy_timeout,
        "pre_wait_ms": just_buy_pre_wait_ms,
        "max_requests": just_buy_max_requests,
        "fade_interval_ms": just_buy_fade_interval_ms,
        "fade_timeout": just_buy_fade_timeout,
    }

    triggered, just_buy_response = service._wait_for_no_ladder_trigger(
        price_fetcher=price_fetcher,
        trigger_price=trigger_price,
        final_price=final_price,
        switch_threshold=switch_threshold,
        fast_poll_ms=fast_poll_ms,
        slow_poll_ms=slow_poll_ms,
        just_buy=just_buy,
        just_buy_params=just_buy_params,
        platform_params=platform_params,
        already_triggered=already_triggered,
    )

    if just_buy_response:
        service.logger.info(f"[{service.user_id}] Just buy succeeded, skipping normal ladder placement")
        return just_buy_response

    if not triggered:
        service.logger.warning(f"[{service.user_id}] Skipping for already triggered order in multi-queue priority")
        return None

    ltp = price_fetcher.get_latest_ltp()
    order_params = {**platform_params, "market_price": ltp}

    if hasattr(price_fetcher, "start_market_details"):
        price_fetcher.start_market_details()

    return service._place_order_with_retries(
        price_fetcher=price_fetcher,
        target_price=final_price,
        quantity=order_quantity,
        level_display=len(price_levels),
        total_levels=len(price_levels),
        ltp=ltp,
        platform_params=order_params,
    )


def execute_ladder_mode(
    service: Any,
    price_fetcher: Any,
    price_levels: List[float],
    actual_increments: List[int],
    order_quantity: int,
    base_quantity: Optional[int],
    skip_first: bool,
    skip_second_last: bool,
    second_last_index: int,
    double_buy: bool,
    double_buy_quantity: Optional[int],
    platform_params: Dict[str, Any],
) -> Tuple[int, Optional[Dict[str, Any]]]:
    """Execute the full ladder IPO workflow."""
    if skip_first:
        service._wait_for_skip_first_trigger(
            price_fetcher,
            price_levels[0],
            service.client.user_config.trigger_mode_slow_poll_interval_ms,
        )
        current_level_index = 1
    else:
        current_level_index = 0

    last_response = None

    while current_level_index < len(price_levels):
        _, response, next_index = service._place_ladder_order(
            price_fetcher=price_fetcher,
            current_level_index=current_level_index,
            price_levels=price_levels,
            actual_increments=actual_increments,
            order_quantity=order_quantity,
            base_quantity=base_quantity,
            second_last_index=second_last_index,
            skip_second_last=skip_second_last,
            double_buy=double_buy,
            double_buy_quantity=double_buy_quantity,
            platform_params=platform_params,
        )

        if response:
            last_response = response

        current_level_index = next_index

    return current_level_index, last_response
