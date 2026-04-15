"""Workflow helpers for IPO trigger execution paths."""
import threading
from typing import Any, Dict, List, Optional, Tuple


class _PrestartedOrderPlacementWorker:
    """Run the blocking order-placement path on a prestarted worker thread."""

    def __init__(self, target: Any) -> None:
        self._target = target
        self._dispatch_event = threading.Event()
        self._started_event = threading.Event()
        self._done_event = threading.Event()
        self._shutdown = False
        self._lock = threading.Lock()
        self._kwargs: dict[str, Any] | None = None
        self._response: Optional[Dict[str, Any]] = None
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="OrderPlacementWorker", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while True:
            self._dispatch_event.wait()
            self._dispatch_event.clear()
            if self._shutdown:
                return
            with self._lock:
                kwargs = dict(self._kwargs or {})
            self._started_event.set()
            try:
                response = self._target(**kwargs)
            except BaseException as exc:  # pragma: no cover - re-raised on caller thread
                self._error = exc
                self._response = None
            else:
                self._response = response
                self._error = None
            finally:
                self._done_event.set()

    def dispatch(self, **kwargs: Any) -> None:
        with self._lock:
            self._kwargs = kwargs
            self._response = None
            self._error = None
        self._started_event.clear()
        self._done_event.clear()
        self._dispatch_event.set()
        self._started_event.wait()

    def result(self) -> Optional[Dict[str, Any]]:
        self._done_event.wait()
        if self._error is not None:
            raise self._error
        return self._response

    def close(self) -> None:
        self._shutdown = True
        self._dispatch_event.set()
        self._thread.join(timeout=1.0)


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
    order_worker = _PrestartedOrderPlacementWorker(service._place_order_with_retries)

    try:
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

        order_worker.dispatch(
            price_fetcher=price_fetcher,
            target_price=final_price,
            quantity=order_quantity,
            level_display=len(price_levels),
            total_levels=len(price_levels),
            ltp=ltp,
            platform_params=order_params,
        )

        if hasattr(price_fetcher, "start_market_details"):
            price_fetcher.start_market_details()

        return order_worker.result()
    finally:
        order_worker.close()


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
