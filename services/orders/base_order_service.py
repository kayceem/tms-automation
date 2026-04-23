"""
Base Order Service Module

Provides an abstract base class for order placement services (TMS/ATRAD).
Uses the Template Method Pattern to share common order execution logic
while allowing platform-specific implementations through abstract methods.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List, Tuple
import math
import time
from api import ATRADClient
from services.fetchers.atrad_price_fetcher import (
    ATRADFetchUser,
    ATRADMultiUserPriceFetcher,
    ATRADPriceFetcher,
)
from services.fetchers.price_fetcher import FetchUser, MultiUserPriceFetcher, PriceFetcher
from services.workflows.coordinated_workflows import (
    execute_ipo_sell_buy_trigger,
    execute_multi_queue_ipo_trigger,
    execute_single_ipo_order,
    place_sell_order_with_retry,
    spawn_buy_threads,
)
from services.workflows.order_attempts import place_ladder_order, place_order_with_retries
from services.workflows.order_ladders import (
    calculate_lower_price_levels,
    calculate_price_levels,
    get_quantity_for_level,
)
from services.workflows.order_workflows import execute_ladder_mode, execute_no_ladder_mode
from services.workflows.specialized_workflows import execute_ipo_trigger_low, execute_trigger_sell
from services.workflows.trigger_waiters import (
    wait_for_ladder_trigger,
    wait_for_no_ladder_trigger,
    wait_for_skip_first_trigger,
)
from utils.logger import get_logger


class BaseOrderService(ABC):
    """
    Abstract base class for order placement services.

    This class implements the Template Method Pattern to share common logic
    for IPO trigger mode, trigger sell mode, and double buy functionality
    across different trading platforms (TMS, ATRAD).

    Subclasses must implement platform-specific methods for order placement,
    parameter building, and token/session management.
    """

    def __init__(self, client, user_id: str):
        """
        Initialize the base order service.

        Args:
            client: Platform-specific client (TMSClient or ATRADClient)
            user_id: User identifier for logging
        """
        self.client = client
        self.user_id = user_id
        self.logger = get_logger(__name__)


    @abstractmethod
    def _place_single_order(self, price: float, quantity: int, **params) -> Dict[str, Any]:
        """
        Place a single order with platform-specific parameters.

        This method must be implemented by subclasses to handle the actual
        order placement API call with the appropriate platform-specific parameters.

        Args:
            price: Order price per unit
            quantity: Order quantity (number of units)

        Returns:
            API response dictionary
        """
        pass

    @abstractmethod
    def _setup_token_manager(self) -> Optional[Any]:
        """
        Setup token/session refresh manager for trigger modes.

        TMS: Creates and starts a TokenRefreshManager to periodically refresh
             the access token during long-running trigger mode operations.

        ATRAD: Returns None (ATRAD auto-refreshes on 401 errors)

        Returns:
            Token manager instance for TMS, None for ATRAD
        """
        pass

    @abstractmethod
    def _cleanup_token_manager(self, token_manager: Optional[Any]):
        """
        Cleanup token/session refresh manager.

        TMS: Stops the TokenRefreshManager and cleans up resources.
        ATRAD: No-op (nothing to clean up)

        Args:
            token_manager: Token manager instance from _setup_token_manager
        """
        pass

    @abstractmethod
    def _get_identifier_for_logging(self, **params) -> str:
        """
        Get human-readable identifier for logging.

        TMS: Returns "Security={security_id}"
        ATRAD: Returns "Symbol={symbol}"

        Args:
            **params: Platform-specific parameters

        Returns:
            Human-readable identifier string
        """
        pass

    def _calculate_price_levels(
        self,
        base_price: float,
        limit_price: Optional[float] = None,
        no_ladder: bool = False
    ) -> Tuple[List[float], List[int]]:
        """
        Calculate price ladder: [0%, +3%, +6%, +9%, +12%, +15%].

        This method calculates a ladder of prices starting from base_price,
        with each level being approximately 3% higher than the previous one.
        All prices are floored to 1 decimal place.

        Used by IPO Trigger mode to determine order prices at different levels.

        Args:
            base_price: Starting price (level 0)
            limit_price: Optional upper limit. Orders above +15% of this limit
                        will be removed, and +15% of limit becomes the final order.
            no_ladder: If True, returns only the base_price (single level)

        Returns:
            Tuple of (price_levels, actual_increments):
                - price_levels: List of prices (floored to 1 decimal)
                - actual_increments: List of percentage increments used

        Example:
            base_price=1000, limit_price=None
            Returns: ([1000.0, 1030.0, 1060.9, 1092.7, 1125.4, 1159.1], [0, 3, 3, 3, 3, 3])
        """
        price_levels, actual_increments = calculate_price_levels(
            base_price=base_price,
            limit_price=limit_price,
            no_ladder=no_ladder,
        )

        if limit_price is not None:
            self.logger.info(
                f"Price ladder with limit {limit_price}: "
                f"{len(price_levels)} levels up to {price_levels[-1]}"
            )

        return price_levels, actual_increments

    def _calculate_lower_price_levels(
        self,
        base_price: float,
        limit_price: Optional[float] = None
    ) -> Tuple[List[float], List[int]]:
        """
        Calculate lower price ladder for buying at lower prices.

        Used by IPO Trigger Low mode to place orders when price drops.

        Logic:
        - If price >= limit: Use -9% and -10% of price
        - If price < limit: Use -8% and -9% of limit
        - All prices are floored to 1 decimal place

        Args:
            base_price: Starting price
            limit_price: Optional limit price for comparison

        Returns:
            Tuple of (price_levels, actual_decrements):
                - price_levels: List of prices (floored to 1 decimal)
                - actual_decrements: List of percentage decrements used

        Example:
            base_price=1000, limit_price=900
            Returns: ([910.0, 900.0], [9, 10])  # -9% and -10% of 1000

            base_price=1000, limit_price=1100
            Returns: ([1012.0, 1001.0], [8, 9])  # -8% and -9% of 1100
        """
        if limit_price is not None and base_price < limit_price:
            self.logger.info(
                f"Using limit price {limit_price} for lower ladder calculation "
                f"(base_price {base_price} < limit_price) with -8%/-9% decrements"
            )
        else:
            if limit_price:
                self.logger.info(
                    f"Using base price {base_price} for lower ladder calculation "
                    f"(base_price {base_price} >= limit_price {limit_price}) with -9%/-10% decrements"
                )

        price_levels, price_decrements = calculate_lower_price_levels(
            base_price=base_price,
            limit_price=limit_price,
        )
        reference_price = limit_price if limit_price is not None and base_price < limit_price else base_price

        self.logger.info(
            f"Lower price ladder from {reference_price}: "
            f"{price_levels} (trigger at -{price_decrements[0]}%, order at -{price_decrements[1]}%)"
        )

        return price_levels, price_decrements

    def _get_quantity_for_level(
        self,
        level_num: int,
        total_levels: int,
        order_quantity: int,
        base_quantity: Optional[int]
    ) -> int:
        """
        Determine quantity for a specific price level.

        Logic:
        - If base_quantity is provided: Use base_quantity for all levels except final
        - Final level: Use order_quantity (full remaining quantity)
        - If base_quantity is None: Use order_quantity for all levels

        Args:
            level_num: Current level number (1-indexed)
            total_levels: Total number of levels in the ladder
            order_quantity: Full order quantity
            base_quantity: Optional base quantity for non-final levels

        Returns:
            Quantity to use for this level
        """
        return get_quantity_for_level(
            level_num=level_num,
            total_levels=total_levels,
            order_quantity=order_quantity,
            base_quantity=base_quantity,
        )


    def _execute_double_buy(
        self,
        price: float,
        quantity: int,
        double_buy_quantity: Optional[int],
        **platform_params
    ):
        """
        Execute double buy: place a second order 0.5s after first order succeeds.

        This method is called after a successful first order when double_buy=True.
        It waits 0.5 seconds and then places a second order with the same price.

        Args:
            price: Order price per unit (same as first order)
            quantity: Quantity from first order (for reference)
            double_buy_quantity: Quantity for second order (defaults to quantity if None)

        Note:
            Double buy failures are logged but do not raise exceptions - they should
            not stop the overall execution flow.
        """
        import json
        import time

        # Determine quantity for second order
        qty = double_buy_quantity if double_buy_quantity is not None else quantity

        # Determine order side for logging
        buy_or_sell = platform_params.get('buy_or_sell', platform_params.get('side', 'BUY'))
        if isinstance(buy_or_sell, int):
            order_side = 'BUY' if buy_or_sell == 1 else 'SELL'
        else:
            order_side = buy_or_sell.upper()

        self.logger.info(
            f"[{self.user_id}] Double buy enabled: waiting 0.5s before placing second order "
            f"(Price={price}, Qty={qty})"
        )

        # Wait 0.5 seconds
        time.sleep(0.5)

        try:
            identifier = self._get_identifier_for_logging(**platform_params)
            self.logger.info(
                f"[{self.user_id}] Placing double buy {order_side} order: "
                f"{identifier}, Price={price}, Qty={qty}"
            )

            response = self._place_single_order(
                price=price,
                quantity=qty,
                **platform_params
            )

            self.logger.info(f"[{self.user_id}] Double buy order placed successfully")
            self.logger.debug(f"[{self.user_id}] Double buy response: {json.dumps(response, indent=2)}")

        except Exception as e:
            # Log error but don't raise - double buy failure shouldn't stop execution
            self.logger.warning(
                f"[{self.user_id}] Double buy order failed (continuing anyway): {str(e)}"
            )

    def _execute_trigger_sell(
        self,
        sell_price: float,
        order_quantity: int,
        fetch_client: Any,
        fetch_security_id: Optional[int] = None,
        ticker: Optional[str] = None,
        limit_price: Optional[float] = None,
        **platform_params
    ) -> Dict[str, Any]:
        """
        Execute trigger sell mode: Monitor LTP and place sell order when price rises to trigger level.

        Logic (with limit):
        - Calculate ladder levels from sell_price to limit
        - Remove levels above limit + 10%
        - Trigger when LTP >= second-to-last level
        - Place sell order at limit + 10%

        Logic (without limit - legacy):
        - Calculate trigger_price from sell_price: trigger_price = sell_price / 1.02 (floored to 1 decimal)
        - Monitor LTP continuously with less aggressive polling (default 500ms)
        - When LTP >= trigger_price, place sell order at sell_price
        - Ensures no duplicate orders are placed

        This mode is used to sell stocks when the price rises enough. The trigger is set slightly
        below the sell price (about 2% lower) so the sell order is placed before the price drops.

        Args:
            sell_price: The base/starting price for sell (current price expectation)
            order_quantity: Number of units to sell
            fetch_client: Client instance for fetching LTP (TMSClient or ATRADClient)
            fetch_security_id: Security ID/symbol for fetching LTP (optional, defaults to order security)
            ticker: Ticker symbol for resolving per-user fetch_id (optional)
            limit_price: Optional lower limit price for ladder calculation (like buy IPO mode)

        Returns:
            Order placement response dictionary

        Raises:
            Exception: If order placement fails
        """
        return execute_trigger_sell(
            service=self,
            sell_price=sell_price,
            order_quantity=order_quantity,
            fetch_client=fetch_client,
            fetch_security_id=fetch_security_id,
            ticker=ticker,
            limit_price=limit_price,
            **platform_params,
        )


    def _setup_price_fetcher(
        self,
        fetch_clients: List[Any],
        fetch_security_id: Optional[int],
        symbol: Optional[str],
        ticker: Optional[str],
        poll_interval_ms: int
    ) -> Any:
        """
        Setup and start the appropriate price fetcher (TMS or ATRAD, single or multi-user).

        Returns:
            Started price fetcher instance
        """
        # Detect platform type
        is_atrad = len(fetch_clients) > 0 and isinstance(fetch_clients[0], ATRADClient)

        if is_atrad:
            price_fetcher = self._setup_atrad_price_fetcher(
                fetch_clients, symbol, poll_interval_ms
            )
        else:
            price_fetcher = self._setup_tms_price_fetcher(
                fetch_clients, fetch_security_id, ticker, poll_interval_ms
            )

        price_fetcher.start()
        return price_fetcher

    def _setup_atrad_price_fetcher(
        self,
        fetch_clients: List[Any],
        symbol: str,
        poll_interval_ms: int
    ) -> Any:
        """Setup ATRAD price fetcher (single or multi-user)."""
        if len(fetch_clients) > 1:
            # Multi-user ATRAD
            fetch_users = [
                ATRADFetchUser(
                    name=f"AFU-{i+1}",
                    client=client,
                    symbol=symbol
                )
                for i, client in enumerate(fetch_clients)
            ]

            for i, client in enumerate(fetch_clients):
                self.logger.info(
                    f"[{self.user_id}] ATRADFetchUser{i+1} ({client.user_id}) using symbol={symbol}"
                )

            requests_per_user = self.client.user_config.trigger_mode_requests_per_fetch_user
            return ATRADMultiUserPriceFetcher(
                fetch_users=fetch_users,
                poll_interval_ms=poll_interval_ms,
                requests_per_user=requests_per_user,
                scheduler_mode="sequential",
                parallel_fetch_enabled=self.client.user_config.trigger_mode_parallel_fetch_enabled,
                parallel_spawn_interval_ms=self.client.user_config.trigger_mode_parallel_spawn_interval_ms,
                parallel_cycle_timeout_ms=self.client.user_config.trigger_mode_parallel_cycle_timeout_ms,
                parallel_wait=self.client.user_config.trigger_mode_parallel_wait,
            )
        else:
            # Single ATRAD user
            self.logger.info(
                f"[{self.user_id}] Using ATRAD fetch with symbol={symbol} for LTP monitoring"
            )
            return ATRADPriceFetcher(
                fetch_client=fetch_clients[0],
                symbol=symbol,
                poll_interval_ms=poll_interval_ms
            )

    def _setup_tms_price_fetcher(
        self,
        fetch_clients: List[Any],
        fetch_security_id: Optional[int],
        ticker: Optional[str],
        poll_interval_ms: int
    ) -> Any:
        """Setup TMS price fetcher (single or multi-user)."""
        from utils import get_ticker_store

        if len(fetch_clients) > 1:
            # Multi-user TMS
            fetch_users = []
            ticker_store = get_ticker_store() if ticker else None

            for i, client in enumerate(fetch_clients):
                # Resolve fetch_id per user based on their host
                user_fetch_id = self._resolve_fetch_id_for_client(
                    client, ticker, ticker_store, fetch_security_id, i
                )

                fetch_users.append(
                    FetchUser(
                        name=f"FU-{i+1}",
                        client=client,
                        fetch_security_id=user_fetch_id
                    )
                )

            requests_per_user = self.client.user_config.trigger_mode_requests_per_fetch_user
            return MultiUserPriceFetcher(
                fetch_users=fetch_users,
                poll_interval_ms=poll_interval_ms,
                requests_per_user=requests_per_user,
                scheduler_mode="sequential",
                parallel_fetch_enabled=self.client.user_config.trigger_mode_parallel_fetch_enabled,
                parallel_spawn_interval_ms=self.client.user_config.trigger_mode_parallel_spawn_interval_ms,
                parallel_cycle_timeout_ms=self.client.user_config.trigger_mode_parallel_cycle_timeout_ms,
                parallel_wait=self.client.user_config.trigger_mode_parallel_wait,
            )
        else:
            # Single TMS user
            single_fetch_id = fetch_security_id
            self.logger.info(
                f"[{self.user_id}] Using fetch_security_id={single_fetch_id} for LTP monitoring"
            )
            return PriceFetcher(
                fetch_client=fetch_clients[0],
                security_id=single_fetch_id,
                poll_interval_ms=poll_interval_ms
            )

    def _resolve_fetch_id_for_client(
        self,
        client: Any,
        ticker: Optional[str],
        ticker_store: Any,
        fallback_fetch_id: Optional[int],
        client_index: int
    ) -> int:
        """Resolve fetch_id for a specific client based on ticker and host."""
        if ticker and ticker_store:
            try:
                user_fetch_id = ticker_store.get_fetch_id(ticker, host=client.user_config.tms_host)
                self.logger.info(
                    f"[{self.user_id}] FetchUser{client_index+1} ({client.user_id}) using "
                    f"fetch_security_id={user_fetch_id} (host={client.user_config.tms_host})"
                )
                return user_fetch_id
            except Exception as e:
                self.logger.warning(
                    f"[{self.user_id}] Could not resolve fetch_id for FetchUser{client_index+1}, "
                    f"using fallback: {fallback_fetch_id}. Error: {e}"
                )

        return fallback_fetch_id

    def _log_ipo_trigger_config(
        self,
        price_levels: List[float],
        security_id: Any,
        order_quantity: int,
        skip_first: bool,
        skip_second_last: bool,
        no_ladder: bool
    ) -> None:
        """Log IPO trigger configuration."""
        self.logger.info(
            f"[{self.user_id}] IPO TRIGGER MODE: {len(price_levels)} levels, "
            f"Security={security_id}, Qty={order_quantity}, "
            f"Price range: Rs. {price_levels[0]} - Rs. {price_levels[-1]}, "
            f"Skip first: {skip_first}, Skip second-last: {skip_second_last}, No ladder: {no_ladder}"
        )

    def _log_ladder_levels(
        self,
        price_levels: List[float],
        actual_increments: List[int],
        second_last_index: int,
        skip_first: bool,
        skip_second_last: bool
    ) -> None:
        """Log all ladder levels with skip markers."""
        for i, price in enumerate(price_levels):
            increment = actual_increments[i]
            skip_marker = ""

            if i == 0 and skip_first:
                skip_marker = " [SKIP]"
            elif i == second_last_index and skip_second_last:
                skip_marker = " [SKIP]"

            if increment == 15:
                self.logger.info(
                    f"[{self.user_id}] Level {i+1}: Rs. {price} (Limit +15%){skip_marker}"
                )
            else:
                self.logger.info(
                    f"[{self.user_id}] Level {i+1}: Rs. {price} (+{increment}%){skip_marker}"
                )

    def _execute_just_buy(
        self,
        final_price: float,
        trigger_price: float,
        order_quantity: int,
        just_buy_interval_ms: int,
        just_buy_timeout: int,
        just_buy_pre_wait_ms: int,
        price_fetcher: Any,
        platform_params: Dict[str, Any],
        just_buy_services: Optional[List[Any]] = None,
        just_buy_max_requests: Optional[int] = None,
        just_buy_fade_interval_ms: Optional[int] = None,
        just_buy_fade_timeout: Optional[int] = None
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Execute just_buy mode: aggressively place orders in multiple threads.

        Args:
            just_buy_max_requests: Maximum number of order attempts (None = use timeout only)
            just_buy_fade_interval_ms: Slower interval for fade phase after initial phase fails
            just_buy_fade_timeout: Additional timeout for fade phase (extends total duration)

        Returns:
            Tuple of (success: bool, response: Optional[Dict])
        """
        import threading

        # Log configuration
        fade_enabled = just_buy_fade_interval_ms and just_buy_fade_timeout

        if just_buy_max_requests:
            config_str = f"interval={just_buy_interval_ms}ms, max_requests={just_buy_max_requests}"
        else:
            config_str = f"interval={just_buy_interval_ms}ms, timeout={just_buy_timeout}s"

        if fade_enabled:
            config_str += f", fade_interval={just_buy_fade_interval_ms}ms, fade_timeout={just_buy_fade_timeout}s"

        self.logger.info(
            f"[{self.user_id}] JUST BUY ACTIVATED: Starting aggressive order placement "
            f"at Rs. {final_price} ({config_str})"
        )

        price_fetcher.pause()

        try:
            # Pre-wait if configured
            if just_buy_pre_wait_ms > 0:
                self.logger.info(f"[{self.user_id}] Just Buy pre-wait: {just_buy_pre_wait_ms}ms")
                time.sleep(just_buy_pre_wait_ms / 1000.0)

            if just_buy_services:
                worker_services = list(just_buy_services)
                self.logger.info(
                    f"[{self.user_id}] Just Buy parallel user pool enabled: "
                    f"{', '.join(worker.user_id for worker in worker_services)}"
                )

                success_flag = threading.Event()
                success_response = {'response': None}
                active_threads = []
                scheduler_lock = threading.Lock()
                free_worker_indices = list(range(len(worker_services)))

                def place_parallel_just_buy_order(thread_id: int, worker_index: int):
                    worker_service = worker_services[worker_index]
                    try:
                        if success_flag.is_set():
                            return

                        worker_service.logger.debug(
                            f"[{worker_service.user_id}] Just Buy Thread #{thread_id}: "
                            f"Placing order at Rs. {final_price}"
                        )

                        order_params = {**platform_params, 'market_price': trigger_price}
                        response = worker_service._place_single_order(
                            price=final_price,
                            quantity=order_quantity,
                            **order_params
                        )

                        if response and not success_flag.is_set():
                            success_flag.set()
                            with scheduler_lock:
                                success_response['response'] = response
                            self.logger.info(
                                f"[{self.user_id}] Just Buy Thread #{thread_id}: "
                                f"SUCCESS via {worker_service.user_id}"
                            )

                    except Exception as e:
                        worker_service.logger.debug(
                            f"[{worker_service.user_id}] Just Buy Thread #{thread_id} failed: {str(e)}"
                        )
                    finally:
                        with scheduler_lock:
                            free_worker_indices.append(worker_index)

                def run_parallel_phase(
                    *,
                    interval_seconds: float,
                    timeout_seconds: Optional[float],
                    max_requests: Optional[int],
                    thread_counter: int,
                ) -> int:
                    phase_start_time = time.time()
                    next_dispatch_time = phase_start_time

                    while True:
                        if success_flag.is_set():
                            self.logger.info(f"[{self.user_id}] Just Buy SUCCESS detected, stopping new threads")
                            break

                        if max_requests is not None and thread_counter >= max_requests:
                            break
                        if timeout_seconds is not None and (time.time() - phase_start_time) >= timeout_seconds:
                            break

                        now = time.time()
                        if now < next_dispatch_time:
                            time.sleep(next_dispatch_time - now)
                            continue

                        with scheduler_lock:
                            worker_index = free_worker_indices.pop(0) if free_worker_indices else None

                        if worker_index is None:
                            time.sleep(0.001)
                            continue

                        thread_counter += 1
                        thread = threading.Thread(
                            target=place_parallel_just_buy_order,
                            args=(thread_counter, worker_index),
                            daemon=True
                        )

                        active_threads.append(thread)
                        thread.start()
                        next_dispatch_time = time.time() + interval_seconds

                    return thread_counter

                thread_counter = 0
                interval_seconds = just_buy_interval_ms / 1000.0
                thread_counter = run_parallel_phase(
                    interval_seconds=interval_seconds,
                    timeout_seconds=None if just_buy_max_requests else just_buy_timeout,
                    max_requests=just_buy_max_requests,
                    thread_counter=thread_counter,
                )

                self.logger.info(
                    f"[{self.user_id}] Just Buy phase ended. Waiting for {len(active_threads)} threads to complete..."
                )
                for thread in active_threads:
                    thread.join(timeout=1)

                if success_flag.is_set():
                    self.logger.info(
                        f"[{self.user_id}] Just Buy SUCCEEDED! "
                        f"Placed {thread_counter} orders, at least one succeeded"
                    )
                    return True, success_response['response']

                if fade_enabled:
                    if just_buy_max_requests:
                        self.logger.warning(
                            f"[{self.user_id}] Just Buy main phase FAILED after {thread_counter} attempts "
                            f"(max_requests={just_buy_max_requests}). Starting FADE phase..."
                        )
                    else:
                        self.logger.warning(
                            f"[{self.user_id}] Just Buy main phase FAILED after {just_buy_timeout}s "
                            f"({thread_counter} attempts). Starting FADE phase..."
                        )

                    self.logger.info(
                        f"[{self.user_id}] FADE PHASE: Placing orders at slower interval "
                        f"({just_buy_fade_interval_ms}ms for {just_buy_fade_timeout}s)"
                    )
                    thread_counter = run_parallel_phase(
                        interval_seconds=just_buy_fade_interval_ms / 1000.0,
                        timeout_seconds=just_buy_fade_timeout,
                        max_requests=None,
                        thread_counter=thread_counter,
                    )

                    self.logger.info(
                        f"[{self.user_id}] Fade phase ended. Waiting for remaining threads to complete..."
                    )
                    for thread in active_threads:
                        if thread.is_alive():
                            thread.join(timeout=1)

                    if success_flag.is_set():
                        self.logger.info(
                            f"[{self.user_id}] FADE PHASE SUCCEEDED! "
                            f"Total {thread_counter} orders placed, at least one succeeded"
                        )
                        return True, success_response['response']

                    self.logger.warning(
                        f"[{self.user_id}] FADE PHASE FAILED after {just_buy_fade_timeout}s. "
                        f"Total {thread_counter} attempts. Falling back to normal trigger logic."
                    )
                    return False, None

                if just_buy_max_requests:
                    self.logger.warning(
                        f"[{self.user_id}] Just Buy FAILED after {thread_counter} attempts "
                        f"(max_requests={just_buy_max_requests}). Falling back to normal trigger logic."
                    )
                else:
                    self.logger.warning(
                        f"[{self.user_id}] Just Buy FAILED after {just_buy_timeout}s "
                        f"({thread_counter} attempts). Falling back to normal trigger logic."
                    )
                return False, None

            # Thread coordination
            success_flag = threading.Event()
            success_response = {'response': None}
            threads_lock = threading.Lock()
            submit_lock = threading.Lock()
            active_threads = []

            def place_just_buy_order(thread_id: int):
                """Place a single order in a separate thread"""
                try:
                    if success_flag.is_set():
                        return

                    self.logger.debug(
                        f"[{self.user_id}] Just Buy Thread #{thread_id}: Placing order at Rs. {final_price}"
                    )

                    with submit_lock:
                        if success_flag.is_set():
                            self.logger.debug(
                                f"[{self.user_id}] Just Buy Thread #{thread_id}: "
                                "Success already recorded, skipping queued submit"
                            )
                            return

                        order_params = {**platform_params, 'market_price': trigger_price}
                        response = self._place_single_order(
                            price=final_price,
                            quantity=order_quantity,
                            **order_params
                        )

                    if response and not success_flag.is_set():
                        success_flag.set()
                        with threads_lock:
                            success_response['response'] = response
                        self.logger.info(
                            f"[{self.user_id}] Just Buy Thread #{thread_id}: "
                            f"SUCCESS! Order placed at Rs. {final_price}"
                        )

                except Exception as e:
                    self.logger.debug(
                        f"[{self.user_id}] Just Buy Thread #{thread_id} failed: {str(e)}"
                    )

            # Spawn threads at intervals
            start_time = time.time()
            thread_counter = 0
            interval_seconds = just_buy_interval_ms / 1000.0

            # Determine stopping condition
            if just_buy_max_requests:
                # Use max_requests as stopping condition
                while thread_counter < just_buy_max_requests:
                    if success_flag.is_set():
                        self.logger.info(
                            f"[{self.user_id}] Just Buy SUCCESS detected, stopping new threads"
                        )
                        break

                    thread_counter += 1
                    thread = threading.Thread(
                        target=place_just_buy_order,
                        args=(thread_counter,),
                        daemon=True
                    )

                    with threads_lock:
                        active_threads.append(thread)

                    thread.start()

                    try:
                        time.sleep(interval_seconds)
                    except KeyboardInterrupt:
                        self.logger.info(f"[{self.user_id}] Just Buy interrupted by user")
                        raise

                self.logger.info(
                    f"[{self.user_id}] Just Buy max_requests ({just_buy_max_requests}) reached. "
                    f"Waiting for threads to complete..."
                )
            else:
                # Use timeout as stopping condition
                while (time.time() - start_time) < just_buy_timeout:
                    if success_flag.is_set():
                        self.logger.info(
                            f"[{self.user_id}] Just Buy SUCCESS detected, stopping new threads"
                        )
                        break

                    thread_counter += 1
                    thread = threading.Thread(
                        target=place_just_buy_order,
                        args=(thread_counter,),
                        daemon=True
                    )

                    with threads_lock:
                        active_threads.append(thread)

                    thread.start()

                    try:
                        time.sleep(interval_seconds)
                    except KeyboardInterrupt:
                        self.logger.info(f"[{self.user_id}] Just Buy interrupted by user")
                        raise

            # Wait for all threads to complete
            self.logger.info(
                f"[{self.user_id}] Just Buy phase ended. Waiting for {len(active_threads)} threads to complete..."
            )
            for thread in active_threads:
                thread.join(timeout=1)

            # Check result from main phase
            if success_flag.is_set():
                self.logger.info(
                    f"[{self.user_id}] Just Buy SUCCEEDED! "
                    f"Placed {thread_counter} orders, at least one succeeded"
                )
                return True, success_response['response']

            # Main phase failed - check if fade phase is enabled
            if fade_enabled:
                if just_buy_max_requests:
                    self.logger.warning(
                        f"[{self.user_id}] Just Buy main phase FAILED after {thread_counter} attempts "
                        f"(max_requests={just_buy_max_requests}). Starting FADE phase..."
                    )
                else:
                    self.logger.warning(
                        f"[{self.user_id}] Just Buy main phase FAILED after {just_buy_timeout}s "
                        f"({thread_counter} attempts). Starting FADE phase..."
                    )

                self.logger.info(
                    f"[{self.user_id}] FADE PHASE: Placing orders at slower interval "
                    f"({just_buy_fade_interval_ms}ms for {just_buy_fade_timeout}s)"
                )

                # Execute fade phase with slower interval
                fade_start_time = time.time()
                fade_interval_seconds = just_buy_fade_interval_ms / 1000.0

                while (time.time() - fade_start_time) < just_buy_fade_timeout:
                    if success_flag.is_set():
                        self.logger.info(
                            f"[{self.user_id}] FADE PHASE: SUCCESS detected, stopping"
                        )
                        break

                    thread_counter += 1
                    thread = threading.Thread(
                        target=place_just_buy_order,
                        args=(thread_counter,),
                        daemon=True
                    )

                    with threads_lock:
                        active_threads.append(thread)

                    thread.start()

                    try:
                        time.sleep(fade_interval_seconds)
                    except KeyboardInterrupt:
                        self.logger.info(f"[{self.user_id}] Fade phase interrupted by user")
                        raise

                # Wait for fade phase threads to complete
                self.logger.info(
                    f"[{self.user_id}] Fade phase ended. Waiting for remaining threads to complete..."
                )
                for thread in active_threads:
                    if thread.is_alive():
                        thread.join(timeout=1)

                # Check final result
                if success_flag.is_set():
                    self.logger.info(
                        f"[{self.user_id}] FADE PHASE SUCCEEDED! "
                        f"Total {thread_counter} orders placed, at least one succeeded"
                    )
                    return True, success_response['response']
                else:
                    self.logger.warning(
                        f"[{self.user_id}] FADE PHASE FAILED after {just_buy_fade_timeout}s. "
                        f"Total {thread_counter} attempts. Falling back to normal trigger logic."
                    )
                    return False, None

            else:
                # No fade phase - return failure
                if just_buy_max_requests:
                    self.logger.warning(
                        f"[{self.user_id}] Just Buy FAILED after {thread_counter} attempts "
                        f"(max_requests={just_buy_max_requests}). Falling back to normal trigger logic."
                    )
                else:
                    self.logger.warning(
                        f"[{self.user_id}] Just Buy FAILED after {just_buy_timeout}s "
                        f"({thread_counter} attempts). Falling back to normal trigger logic."
                    )
                return False, None

        finally:
            pass

    def _wait_for_no_ladder_trigger(
        self,
        price_fetcher: Any,
        trigger_price: float,
        final_price: float,
        switch_threshold: float,
        fast_poll_ms: int,
        slow_poll_ms: int,
        just_buy: bool,
        just_buy_params: Dict[str, Any],
        platform_params: Dict[str, Any],
        already_triggered: bool = False
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[float]]:
        """
        Wait for no_ladder trigger with dynamic polling and optional just_buy.

        Returns:
            Tuple of (triggered: bool, response: Optional[Dict], ltp: Optional[float])
        """
        return wait_for_no_ladder_trigger(
            service=self,
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

    def _wait_for_skip_first_trigger(
        self,
        price_fetcher: Any,
        first_price: float,
        slow_poll_ms: int
    ) -> None:
        """Wait for initial trigger when skip_first is enabled."""
        wait_for_skip_first_trigger(
            service=self,
            price_fetcher=price_fetcher,
            first_price=first_price,
            slow_poll_ms=slow_poll_ms,
        )

    def _wait_for_ladder_trigger(
        self,
        price_fetcher: Any,
        trigger_price: float,
        increment_pct: int,
        current_level_index: int,
        price_levels: List[float],
        actual_increments: List[int],
        second_last_index: int,
        skip_second_last: bool
    ) -> Tuple[Optional[float], int]:
        """
        Wait for LTP to reach trigger price, handling level skips if LTP jumps ahead.

        Returns:
            Tuple of (current_ltp: float, updated_level_index: int)
        """
        return wait_for_ladder_trigger(
            service=self,
            price_fetcher=price_fetcher,
            trigger_price=trigger_price,
            increment_pct=increment_pct,
            current_level_index=current_level_index,
            price_levels=price_levels,
            second_last_index=second_last_index,
            skip_second_last=skip_second_last,
        )

    def _place_order_with_retries(
        self,
        price_fetcher: Any,
        target_price: float,
        quantity: int,
        level_display: int,
        total_levels: int,
        ltp: Optional[float],
        platform_params: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Place order with retry logic (up to 3 attempts).

        Returns:
            Order response if successful, None if all attempts failed
        """
        return place_order_with_retries(
            service=self,
            price_fetcher=price_fetcher,
            target_price=target_price,
            quantity=quantity,
            level_display=level_display,
            total_levels=total_levels,
            ltp=ltp,
            platform_params=platform_params,
        )

    def _place_ladder_order(
        self,
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
        platform_params: Dict[str, Any]
    ) -> Tuple[bool, Optional[Dict[str, Any]], int]:
        """
        Place a single ladder order at the specified level.

        Returns:
            Tuple of (success: bool, response: Optional[Dict], next_level_index: int)
        """
        return place_ladder_order(
            service=self,
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

    def _execute_no_ladder_mode(
        self,
        price_fetcher: Any,
        price_levels: List[float],
        order_quantity: int,
        just_buy: bool,
        just_buy_interval_ms: int,
        just_buy_timeout: int,
        just_buy_pre_wait_ms: int,
        just_buy_max_requests: int,
        just_buy_fade_interval_ms: Optional[int],
        just_buy_fade_timeout: Optional[int],
        platform_params: Dict[str, Any],
        just_buy_services: Optional[List[Any]] = None,
        already_triggered: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Execute no-ladder mode: wait for trigger, optionally use just_buy, then place final order.

        Returns:
            Order response if successful, None otherwise
        """
        return execute_no_ladder_mode(
            service=self,
            price_fetcher=price_fetcher,
            price_levels=price_levels,
            order_quantity=order_quantity,
            just_buy=just_buy,
            just_buy_interval_ms=just_buy_interval_ms,
            just_buy_timeout=just_buy_timeout,
            just_buy_pre_wait_ms=just_buy_pre_wait_ms,
            just_buy_max_requests=just_buy_max_requests,
            just_buy_fade_interval_ms=just_buy_fade_interval_ms,
            just_buy_fade_timeout=just_buy_fade_timeout,
            just_buy_services=just_buy_services,
            platform_params=platform_params,
            already_triggered=already_triggered,
        )

    def _execute_ladder_mode(
        self,
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
        platform_params: Dict[str, Any]
    ) -> Tuple[int, Optional[Dict[str, Any]]]:
        """
        Execute ladder mode: place orders at each ladder level.

        Returns:
            Tuple of (orders_placed: int, last_response: Optional[Dict])
        """
        return execute_ladder_mode(
            service=self,
            price_fetcher=price_fetcher,
            price_levels=price_levels,
            actual_increments=actual_increments,
            order_quantity=order_quantity,
            base_quantity=base_quantity,
            skip_first=skip_first,
            skip_second_last=skip_second_last,
            second_last_index=second_last_index,
            double_buy=double_buy,
            double_buy_quantity=double_buy_quantity,
            platform_params=platform_params,
        )


    def _execute_ipo_trigger(
        self,
        base_price: float,
        order_quantity: int,
        fetch_clients: List[Any],
        limit_price: Optional[float] = None,
        skip_first: bool = False,
        skip_second_last: bool = False,
        no_ladder: bool = False,
        fetch_security_id: Optional[int] = None,
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
        just_buy_services: Optional[List[Any]] = None,
        already_triggered: bool = False,
        **platform_params
    ) -> Dict[str, Any]:
        """
        Execute IPO trigger mode: Monitor LTP and place orders when LTP reaches ladder levels.

        New trigger logic:
        - When LTP >= ladder[i], place order at ladder[i+1]
        - If skip_first=True, skip ladder[0] and start from ladder[1]
        - If skip_second_last=True, skip the second-to-last ladder level
        - If no_ladder=True, skip ALL ladder levels and only place final order when LTP >= second-to-last
        - Skip missed levels if LTP jumps ahead
        - Uses base_quantity for all levels except final, which uses order_quantity

        Just Buy Mode (only active when no_ladder=True):
        - When LTP reaches switch_threshold, starts aggressive multi-threaded order placement
        - Optionally waits just_buy_pre_wait_ms before starting order placement
        - Places orders at final_price every just_buy_interval_ms for just_buy_timeout seconds
        - If any order succeeds, stops and moves on
        - If all orders fail after timeout, falls back to normal trigger logic

        Args:
            base_price: Starting price
            order_quantity: Number of units for final level
            fetch_clients: List of client instances for fetching LTP with rotation
            limit_price: Optional upper limit price for calculations
            skip_first: Skip the first ladder level
            skip_second_last: Skip the second-to-last ladder level
            no_ladder: Skip ALL ladder levels, only place final order at limit+10%
            fetch_security_id: Security ID for fetching LTP (defaults to security_id if not provided)
            base_quantity: Quantity for all ladder levels except final (defaults to order_quantity for all levels)
            ticker: Ticker symbol for resolving per-user fetch_id (optional)
            just_buy: Enable aggressive multi-threaded order placement when switch_threshold is met
            just_buy_interval_ms: Interval between order attempts in milliseconds (default: 100ms)
            just_buy_timeout: Total duration to keep trying in seconds (default: 5s, ignored if max_requests set)
            just_buy_pre_wait_ms: Wait time after switch threshold before starting just_buy (default: 0ms)
            just_buy_max_requests: Max number of order attempts (None = use timeout instead)
            just_buy_fade_interval_ms: Slower interval for fade phase after main phase fails (None = no fade)
            just_buy_fade_timeout: Additional timeout for fade phase in seconds (None = no fade)
            already_triggered: True if called from multi-queue with switch threshold already reached (default: False)

        Returns:
            Last API response dictionary
        """

        # Extract identifiers
        security_id = platform_params.get('security_id')
        symbol = platform_params.get('symbol')
        fetch_security_id = fetch_security_id or security_id or symbol

        # Calculate price ladder
        price_levels, actual_increments = self._calculate_price_levels(
            base_price, limit_price
        )

        # Log configuration
        second_last_index = len(price_levels) - 2 if len(price_levels) >= 2 else -1
        self._log_ipo_trigger_config(
            price_levels, security_id, order_quantity,
            skip_first, skip_second_last, no_ladder
        )
        self._log_ladder_levels(
            price_levels, actual_increments, second_last_index,
            skip_first, skip_second_last
        )

        # Setup price fetcher
        poll_interval_ms = self.client.user_config.trigger_mode_poll_interval_ms
        price_fetcher = self._setup_price_fetcher(
            fetch_clients, fetch_security_id, symbol, ticker, poll_interval_ms
        )

        # Setup token refresh
        token_manager = self._setup_token_manager()

        last_response = None

        try:
            # Validate configuration
            if just_buy and not no_ladder:
                raise ValueError("just_buy can only be used with no_ladder=True mode")

            if no_ladder:
                # No-ladder mode: wait for trigger, optionally use just_buy
                last_response = self._execute_no_ladder_mode(
                    price_fetcher=price_fetcher,
                    price_levels=price_levels,
                    order_quantity=order_quantity,
                    just_buy=just_buy,
                    just_buy_interval_ms=just_buy_interval_ms,
                    just_buy_timeout=just_buy_timeout,
                    just_buy_pre_wait_ms=just_buy_pre_wait_ms,
                    just_buy_max_requests=just_buy_max_requests,
                    just_buy_fade_interval_ms=just_buy_fade_interval_ms,
                    just_buy_fade_timeout=just_buy_fade_timeout,
                    just_buy_services=just_buy_services,
                    platform_params=platform_params,
                    already_triggered=already_triggered
                )
                orders_placed = 1 if last_response else 0

            else:
                # Ladder mode: place orders at each level
                orders_placed, last_response = self._execute_ladder_mode(
                    price_fetcher=price_fetcher,
                    price_levels=price_levels,
                    actual_increments=actual_increments,
                    order_quantity=order_quantity,
                    base_quantity=base_quantity,
                    skip_first=skip_first,
                    skip_second_last=skip_second_last,
                    second_last_index=second_last_index,
                    double_buy=double_buy,
                    double_buy_quantity=double_buy_quantity,
                    platform_params=platform_params
                )

        finally:
            if hasattr(price_fetcher, 'stop_market_details'):
                price_fetcher.stop_market_details()
            price_fetcher.stop()
            self._cleanup_token_manager(token_manager)

        self.logger.info(
            f"[{self.user_id}] IPO TRIGGER COMPLETE: {orders_placed} orders placed"
        )
        return last_response

    def _execute_ipo_trigger_low(
        self,
        base_price: float,
        order_quantity: int,
        fetch_clients: List[Any],
        limit_price: Optional[float] = None,
        fetch_security_id: Optional[int] = None,
        ticker: Optional[str] = None,
        timeout_ipo_trigger_low: Optional[int] = None,
        **platform_params
    ) -> Dict[str, Any]:
        """
        Execute IPO trigger low mode: Monitor LTP and place order at -10% when LTP <= -9%.

        Logic:
        - Calculate lower price levels using -9% and -10% of reference price
        - Reference price: price if price >= limit, otherwise limit
        - Monitor LTP until it reaches <= -9% level
        - Place order at -10% level
        - Exit if timeout is reached without trigger

        Args:
            base_price: Starting price
            order_quantity: Number of units to order
            fetch_clients: List of client instances for fetching LTP with rotation
            limit_price: Optional limit price for reference price calculation
            fetch_security_id: Security ID for fetching LTP
            ticker: Ticker symbol for resolving per-user fetch_id
            timeout_ipo_trigger_low: Optional timeout in seconds (None = no timeout)
            **platform_params: Platform-specific parameters

        Returns:
            API response dictionary or None if timeout reached
        """
        return execute_ipo_trigger_low(
            service=self,
            base_price=base_price,
            order_quantity=order_quantity,
            fetch_clients=fetch_clients,
            limit_price=limit_price,
            fetch_security_id=fetch_security_id,
            ticker=ticker,
            timeout_ipo_trigger_low=timeout_ipo_trigger_low,
            **platform_params,
        )


    def _execute_multi_queue_ipo_trigger(
        self,
        orders: List[Dict[str, Any]],
        fetch_clients: List[Any],
        on_order_complete: Any = None,
    ) -> List[Dict[str, Any]]:
        """
        Execute multi-queue IPO trigger mode for multiple orders.

        Monitors all orders concurrently (sequential symbol polling) until one reaches
        switch threshold, then executes that order as priority, followed by remaining orders.

        Args:
            orders: List of order dictionaries (all with same queue_id, multi_queue=true, no_ladder=true)
            fetch_clients: List of fetch clients (must be same for all orders)

        Returns:
            List of order responses
        """
        return execute_multi_queue_ipo_trigger(
            service=self,
            orders=orders,
            fetch_clients=fetch_clients,
            on_order_complete=on_order_complete,
        )

    def _execute_single_ipo_order(
        self,
        order: Dict[str, Any],
        fetch_clients: List[Any],
        already_triggered: bool = False
    ) -> Dict[str, Any]:
        """
        Execute a single IPO trigger order (helper for multi-queue).

        Args:
            order: Order dictionary
            fetch_clients: List of fetch clients
            already_triggered: True if switch threshold already reached in multi-queue monitoring (default: False)

        Returns:
            Order response
        """
        return execute_single_ipo_order(
            service=self,
            order=order,
            fetch_clients=fetch_clients,
            already_triggered=already_triggered,
        )

    def _execute_ipo_sell_buy_trigger(
        self,
        buyer_service: 'BaseOrderService',
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
        just_buy_timeout: int = 5
    ) -> Dict[str, Any]:
        """
        Execute IPO sell-buy-trigger mode.

        Args:
            buyer_service: Service instance for placing buy orders
            fetch_clients: List of fetch clients for LTP monitoring
            ticker: Ticker symbol
            security_id: Security ID (TMS)
            exchange_security_id: Exchange security ID (TMS)
            symbol: Symbol (ATRAD)
            base_price: Base/starting price
            buy_quantity: Quantity for buy orders
            sell_quantity: Quantity for sell order
            sell_pre_wait_ms: Wait time before sell sequence starts (ms)
            limit_price: Upper limit price
            just_buy_interval_ms: Buy thread spawn interval
            just_buy_timeout: Buy thread total duration

        Returns:
            Dictionary with sell and buy responses
        """
        return execute_ipo_sell_buy_trigger(
            service=self,
            buyer_service=buyer_service,
            fetch_clients=fetch_clients,
            ticker=ticker,
            security_id=security_id,
            exchange_security_id=exchange_security_id,
            symbol=symbol,
            base_price=base_price,
            buy_quantity=buy_quantity,
            sell_quantity=sell_quantity,
            sell_pre_wait_ms=sell_pre_wait_ms,
            limit_price=limit_price,
            just_buy_interval_ms=just_buy_interval_ms,
            just_buy_timeout=just_buy_timeout,
        )

    def _spawn_buy_threads(
        self,
        buyer_service: 'BaseOrderService',
        final_price: float,
        buy_quantity: int,
        interval_ms: int,
        timeout: int,
        success_flag: Any,  # threading.Event
        response_container: Dict,
        threads_lock: Any,  # threading.Lock
        active_threads: List,
        is_atrad: bool,
        security_id: Optional[int],
        exchange_security_id: Optional[int],
        symbol: Optional[str],
        market_price: Optional[float]
    ):
        """
        Spawn buy order threads at intervals (just-buy pattern).
        Runs in background thread.

        Args:
            buyer_service: Service instance for placing buy orders
            final_price: Price for buy orders
            buy_quantity: Quantity for buy orders
            interval_ms: Interval between thread spawns (ms)
            timeout: Total duration to spawn threads (seconds)
            success_flag: Threading event to signal success
            response_container: Dict to store successful response
            threads_lock: Lock for thread-safe access
            active_threads: List to track spawned threads
            is_atrad: True if ATRAD platform
            security_id: Security ID (TMS)
            exchange_security_id: Exchange security ID (TMS)
            symbol: Symbol (ATRAD)
            market_price: Current market price
        """
        spawn_buy_threads(
            service=self,
            buyer_service=buyer_service,
            final_price=final_price,
            buy_quantity=buy_quantity,
            interval_ms=interval_ms,
            timeout=timeout,
            success_flag=success_flag,
            response_container=response_container,
            threads_lock=threads_lock,
            active_threads=active_threads,
            is_atrad=is_atrad,
            security_id=security_id,
            exchange_security_id=exchange_security_id,
            symbol=symbol,
            market_price=market_price,
        )

    def _place_sell_order_with_retry(
        self,
        sell_price: float,
        sell_quantity: int,
        success_flag: Any,  # threading.Event
        response_container: Dict,
        is_atrad: bool,
        security_id: Optional[int],
        exchange_security_id: Optional[int],
        symbol: Optional[str],
        market_price: Optional[float],
        max_retries: int = 2
    ):
        """
        Place sell order with retry logic (3-5 attempts).
        Runs in separate thread.

        Args:
            sell_price: Price for sell order
            sell_quantity: Quantity for sell order
            success_flag: Threading event to signal success
            response_container: Dict to store successful response
            is_atrad: True if ATRAD platform
            security_id: Security ID (TMS)
            exchange_security_id: Exchange security ID (TMS)
            symbol: Symbol (ATRAD)
            market_price: Current market price
            max_retries: Maximum number of retry attempts (default: 5)
        """
        place_sell_order_with_retry(
            service=self,
            sell_price=sell_price,
            sell_quantity=sell_quantity,
            success_flag=success_flag,
            response_container=response_container,
            is_atrad=is_atrad,
            security_id=security_id,
            exchange_security_id=exchange_security_id,
            symbol=symbol,
            market_price=market_price,
            max_retries=max_retries,
        )
