"""Trigger-wait helper functions extracted from BaseOrderService."""

import time
from typing import Any, Dict, List, Optional, Tuple


def wait_for_no_ladder_trigger(
    service: Any,
    price_fetcher: Any,
    trigger_price: float,
    final_price: float,
    switch_threshold: float,
    fast_poll_ms: int,
    slow_poll_ms: int,
    just_buy: bool,
    just_buy_params: Dict[str, Any],
    platform_params: Dict[str, Any],
    already_triggered: bool = False,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Wait for a no-ladder trigger with dynamic polling and optional just-buy."""
    if already_triggered and just_buy:
        service.logger.info(
            f"[{service.user_id}] Already triggered from multi-queue priority. "
            f"Executing JUST BUY immediately at Rs. {final_price}"
        )
        success, response = service._execute_just_buy(
            final_price=final_price,
            trigger_price=trigger_price,
            order_quantity=just_buy_params["order_quantity"],
            just_buy_interval_ms=just_buy_params["interval_ms"],
            just_buy_timeout=just_buy_params["timeout"],
            just_buy_pre_wait_ms=just_buy_params["pre_wait_ms"],
            price_fetcher=price_fetcher,
            platform_params=platform_params,
            just_buy_max_requests=just_buy_params["max_requests"],
            just_buy_fade_interval_ms=just_buy_params.get("fade_interval_ms"),
            just_buy_fade_timeout=just_buy_params.get("fade_timeout"),
        )
        if success:
            return True, response
        service.logger.warning(f"[{service.user_id}] Just buy failed.")
        return False, None

    service.logger.info(
        f"[{service.user_id}] NO LADDER MODE: Waiting for LTP >= Rs. {trigger_price} "
        f"to place FINAL order at Rs. {final_price}"
    )
    service.logger.info(
        f"[{service.user_id}] Dynamic polling: Fast={fast_poll_ms}ms, Slow={slow_poll_ms}ms, "
        f"Switch threshold=Rs. {switch_threshold}"
    )
    if just_buy:
        service.logger.info(
            f"[{service.user_id}] JUST BUY MODE enabled: Will aggressively place orders "
            f"when switch threshold is reached"
        )

    using_fast_poll = True
    permanently_fast = False
    switched_to_parallel = False
    slow_sleep = slow_poll_ms / 5000.0
    fast_sleep = min((fast_poll_ms / 5000.0), 0.001)
    should_use_parallel = getattr(service.client.user_config, "trigger_mode_parallel_fetch_enabled", False)

    while True:
        ltp = price_fetcher.get_latest_ltp()

        if ltp is not None:
            if (
                not switched_to_parallel
                and should_use_parallel
                and ltp >= switch_threshold
                and not permanently_fast
                and using_fast_poll
            ):
                service.logger.info(
                    f"[{service.user_id}] LTP Rs. {ltp} >= Rs. {switch_threshold} - "
                    f"starting in FAST parallel mode"
                )
                if hasattr(price_fetcher, "update_scheduler_mode"):
                    price_fetcher.update_scheduler_mode("parallel")
                switched_to_parallel = True

            if ltp >= trigger_price:
                service.logger.info(f"[{service.user_id}] TRIGGERED! LTP={ltp} >= Rs. {trigger_price}. ")
                return True, None

            if not permanently_fast:
                if using_fast_poll and ltp < switch_threshold:
                    using_fast_poll = False
                    service.logger.info(
                        f"[{service.user_id}] LTP Rs. {ltp} < Rs. {switch_threshold} - "
                        f"switching to SLOW polling ({slow_poll_ms}ms, cooldown OFF)"
                    )
                    if hasattr(price_fetcher, "update_scheduler_mode"):
                        price_fetcher.update_scheduler_mode("sequential")
                    if hasattr(price_fetcher, "update_poll_settings"):
                        price_fetcher.update_poll_settings(slow_poll_ms, enable_cooldown=False)
                    switched_to_parallel = False

                elif not using_fast_poll and ltp >= switch_threshold:
                    using_fast_poll = True
                    permanently_fast = True
                    service.logger.info(
                        f"[{service.user_id}] LTP Rs. {ltp} >= Rs. {switch_threshold} - "
                        f"switch threshold reached!"
                    )

                    if just_buy:
                        success, response = service._execute_just_buy(
                            final_price=final_price,
                            trigger_price=trigger_price,
                            order_quantity=just_buy_params["order_quantity"],
                            just_buy_interval_ms=just_buy_params["interval_ms"],
                            just_buy_timeout=just_buy_params["timeout"],
                            just_buy_pre_wait_ms=just_buy_params["pre_wait_ms"],
                            price_fetcher=price_fetcher,
                            platform_params=platform_params,
                            just_buy_max_requests=just_buy_params["max_requests"],
                            just_buy_fade_interval_ms=just_buy_params.get("fade_interval_ms"),
                            just_buy_fade_timeout=just_buy_params.get("fade_timeout"),
                        )
                        if success:
                            return True, response

                    service.logger.info(
                        f"[{service.user_id}] Switching to FAST polling ({fast_poll_ms}ms, cooldown ON) PERMANENTLY"
                    )
                    if getattr(service.client.user_config, "trigger_mode_parallel_fetch_enabled", False):
                        if hasattr(price_fetcher, "update_scheduler_mode"):
                            price_fetcher.update_scheduler_mode("parallel")
                        switched_to_parallel = True
                    if hasattr(price_fetcher, "update_poll_settings"):
                        price_fetcher.update_poll_settings(fast_poll_ms, enable_cooldown=True)

        try:
            time.sleep(slow_sleep if not using_fast_poll else fast_sleep)
        except KeyboardInterrupt:
            service.logger.info(f"[{service.user_id}] IPO trigger interrupted by user")
            raise


def wait_for_skip_first_trigger(
    service: Any,
    price_fetcher: Any,
    first_price: float,
    slow_poll_ms: int,
) -> None:
    """Wait for the initial trigger when skip-first is enabled."""
    service.logger.info(
        f"[{service.user_id}] Skip-first enabled: waiting for LTP >= Rs. {first_price}"
    )
    sleep_duration = slow_poll_ms / 5000.0

    while True:
        ltp = price_fetcher.get_latest_ltp()
        if ltp is not None and ltp >= first_price:
            service.logger.info(
                f"[{service.user_id}] Initial trigger reached! LTP={ltp} >= "
                f"Rs. {first_price}. Starting from level 2."
            )
            return

        try:
            time.sleep(sleep_duration)
        except KeyboardInterrupt:
            service.logger.info(f"[{service.user_id}] IPO trigger interrupted by user")
            raise


def wait_for_ladder_trigger(
    service: Any,
    price_fetcher: Any,
    trigger_price: float,
    increment_pct: int,
    current_level_index: int,
    price_levels: List[float],
    second_last_index: int,
    skip_second_last: bool,
) -> Tuple[Optional[float], int]:
    """Wait for LTP to reach a ladder trigger and handle skipped levels."""
    target_price = price_levels[current_level_index]

    if increment_pct == -1:
        service.logger.info(
            f"[{service.user_id}] Waiting for LTP >= Rs. {trigger_price} "
            f"to place order at Rs. {target_price} (Limit +10%)"
        )
    else:
        service.logger.info(
            f"[{service.user_id}] Waiting for LTP >= Rs. {trigger_price} "
            f"to place order at Rs. {target_price} (+{increment_pct}%)"
        )

    while True:
        ltp = price_fetcher.get_latest_ltp()

        if ltp is not None and ltp >= trigger_price:
            while current_level_index < len(price_levels) - 1 and ltp >= price_levels[current_level_index]:
                service.logger.warning(
                    f"[{service.user_id}] LTP={ltp} >= Rs. {price_levels[current_level_index]}, "
                    f"skipping missed level {current_level_index + 1}"
                )
                current_level_index += 1

            if current_level_index == second_last_index and skip_second_last:
                service.logger.info(
                    f"[{service.user_id}] Skipping second-to-last level {current_level_index + 1} "
                    f"(Rs. {price_levels[current_level_index]}) as requested"
                )
                current_level_index += 1

            service.logger.info(
                f"[{service.user_id}] TRIGGERED! LTP={ltp} >= "
                f"Rs. {trigger_price}. Placing order at Rs. {price_levels[current_level_index]}"
            )

            if hasattr(price_fetcher, "start_market_details"):
                service.logger.info(f"[{service.user_id}] Starting market details monitoring for order placement")
                price_fetcher.start_market_details()

            return ltp, current_level_index

        try:
            time.sleep(0.05)
        except KeyboardInterrupt:
            service.logger.info(f"[{service.user_id}] IPO trigger interrupted by user")
            raise
