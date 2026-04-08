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
        Calculate price ladder: [0%, +2%, +4%, +6%, +8%, +10%].

        This method calculates a ladder of prices starting from base_price,
        with each level being approximately 2% higher than the previous one.
        All prices are floored to 1 decimal place.

        Used by IPO Trigger mode to determine order prices at different levels.

        Args:
            base_price: Starting price (level 0)
            limit_price: Optional upper limit. Orders above +10% of this limit
                        will be removed, and +10% of limit becomes the final order.
            no_ladder: If True, returns only the base_price (single level)

        Returns:
            Tuple of (price_levels, actual_increments):
                - price_levels: List of prices (floored to 1 decimal)
                - actual_increments: List of percentage increments used

        Example:
            base_price=1000, limit_price=None
            Returns: ([1000.0, 1020.0, 1040.8, 1061.6, 1082.8, 1104.4], [0, 2, 2, 2, 2, 2])
        """
        if no_ladder:
            return [base_price], [0]

        price_increments = [0, 2, 2, 2, 2, 2]  # [0%, +2%, +4%, +6%, +8%, +10%]
        price_levels: List[float] = []
        actual_increments: List[int] = []

        # Calculate standard ladder prices
        current_price = base_price
        for increment in price_increments:
            new_price = current_price * (1 + increment / 100)
            floored_price = math.floor(new_price * 10) / 10
            current_price = floored_price
            price_levels.append(floored_price)
            actual_increments.append(increment)

        # Handle limit_price filtering
        if limit_price is not None:
            # Calculate the maximum allowed price: limit_price * 1.10 (floored)
            max_price_raw = limit_price * 1.10
            max_price = math.floor(max_price_raw * 10) / 10

            # Remove prices that exceed max_price
            filtered_levels = []
            filtered_increments = []
            for price, increment in zip(price_levels, actual_increments):
                if price <= max_price:
                    filtered_levels.append(price)
                    filtered_increments.append(increment)

            # Always ensure the final price is exactly max_price
            if not filtered_levels or filtered_levels[-1] != max_price:
                filtered_levels.append(max_price)
                filtered_increments.append(10)  # This represents +10% of limit

            price_levels = filtered_levels
            actual_increments = filtered_increments

            self.logger.info(
                f"Price ladder with limit {limit_price}: "
                f"{len(price_levels)} levels up to {max_price}"
            )

        return price_levels, actual_increments

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
        is_final_level = (level_num == total_levels)

        if is_final_level:
            return order_quantity
        elif base_quantity is not None:
            return base_quantity
        else:
            return order_quantity


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
        from services.price_fetcher import PriceFetcher
        import time

        # Get identifier for logging
        identifier = self._get_identifier_for_logging(**platform_params)

        # Use fetch_security_id if provided, otherwise extract from platform_params
        if fetch_security_id is None:
            # Try to extract security_id or symbol from platform_params
            fetch_security_id = platform_params.get('security_id') or platform_params.get('symbol')

        # Calculate trigger and final sell price based on limit
        if limit_price:
            # Limit mode: Calculate ladder levels like IPO buy mode
            self.logger.info(
                f"[{self.user_id}] TRIGGER SELL MODE (with limit): "
                f"{identifier}, Qty={order_quantity}, "
                f"Base price: Rs. {sell_price}, Limit: Rs. {limit_price}"
            )

            # Calculate ladder levels from sell_price down to limit
            price_levels, actual_increments = self._calculate_price_levels(
                sell_price, limit_price
            )

            # Log ladder levels
            self.logger.info(f"[{self.user_id}] Calculated {len(price_levels)} ladder levels:")
            for i, price in enumerate(price_levels):
                increment = actual_increments[i] if i < len(actual_increments) else -1
                if increment == -1:
                    self.logger.debug(f"[{self.user_id}] Level {i+1}: Rs. {price} (Limit +10%)")
                else:
                    self.logger.debug(f"[{self.user_id}] Level {i+1}: Rs. {price} (+{increment}%)")

            # Get second-to-last level as trigger (like buy IPO mode)
            second_last_index = len(price_levels) - 2 if len(price_levels) >= 2 else -1
            if second_last_index >= 0:
                trigger_price = price_levels[second_last_index]
            else:
                # Edge case: only one level, use it as trigger
                trigger_price = price_levels[0]

            # Final sell price is limit + 10%
            final_sell_price = price_levels[-1]

            self.logger.info(
                f"[{self.user_id}] Will monitor for LTP >= Rs. {trigger_price} (level {second_last_index + 1})"
            )
            self.logger.info(
                f"[{self.user_id}] Will place sell order at Rs. {final_sell_price} when triggered"
            )

        else:
            # Legacy mode: Simple 2% trigger (no limit)
            # Calculate trigger price from sell price: trigger_price * 1.02 = sell_price
            # So: trigger_price = sell_price / 1.02
            # Use ceil to ensure trigger_price * 1.02 >= sell_price (within 2% limit)
            trigger_price = sell_price / 1.02
            trigger_price = math.ceil(trigger_price * 10) / 10
            final_sell_price = sell_price

            self.logger.info(
                f"[{self.user_id}] TRIGGER SELL MODE (legacy): "
                f"{identifier}, Qty={order_quantity}, "
                f"Sell price: Rs. {sell_price}, Trigger price: Rs. {trigger_price}"
            )
            self.logger.info(
                f"[{self.user_id}] Will place sell order at Rs. {final_sell_price} when LTP >= Rs. {trigger_price}"
            )

        # Get poll interval from user config (default to 500ms)
        poll_interval_ms = getattr(self.client.user_config, 'trigger_sell_poll_interval_ms', 500)

        # Detect if fetch client is ATRAD or TMS
        from api import ATRADClient
        is_atrad_fetch = isinstance(fetch_client, ATRADClient)

        if is_atrad_fetch:
            # Use ATRAD price fetcher
            from services.atrad_price_fetcher import ATRADPriceFetcher

            # ATRAD uses symbol instead of security_id
            symbol = platform_params.get('symbol')
            self.logger.info(
                f"[{self.user_id}] Using ATRAD fetch with symbol={symbol} for trigger sell LTP monitoring"
            )

            # Create ATRAD price fetcher for monitoring
            price_fetcher = ATRADPriceFetcher(
                fetch_client=fetch_client,
                symbol=symbol,
                poll_interval_ms=poll_interval_ms
            )
        else:
            # Use TMS price fetcher
            # Resolve fetch_security_id for this specific fetch client if ticker provided
            if ticker:
                try:
                    from utils import get_ticker_store
                    ticker_store = get_ticker_store()
                    user_fetch_id = ticker_store.get_fetch_id(ticker, host=fetch_client.user_config.tms_host)
                    if user_fetch_id:
                        fetch_security_id = user_fetch_id
                        self.logger.info(
                            f"[{self.user_id}] Using host-specific fetch_id={fetch_security_id} for ticker {ticker}"
                        )
                except Exception as e:
                    self.logger.debug(f"[{self.user_id}] Could not resolve host-specific fetch_id: {e}")

            # Create TMS price fetcher for monitoring
            price_fetcher = PriceFetcher(
                fetch_client=fetch_client,
                security_id=fetch_security_id,
                poll_interval_ms=poll_interval_ms
            )

        token_manager = self._setup_token_manager()
        if token_manager:
            refresh_interval = self.client.user_config.trigger_mode_refresh_interval_seconds
            self.logger.info(
                f"[{self.user_id}] Token refresh started (interval: {refresh_interval}s)"
            )

        # Start monitoring
        price_fetcher.start()
        order_placed = False
        last_response = None

        try:
            self.logger.info(
                f"[{self.user_id}] Starting LTP monitoring (poll interval: {poll_interval_ms}ms)"
            )

            while not order_placed:
                # Get current LTP
                ltp = price_fetcher.get_latest_ltp()

                if ltp is None:
                    self.logger.debug(f"[{self.user_id}] Waiting for first LTP...")
                    time.sleep(poll_interval_ms / 1000)
                    continue

                # Check if trigger condition is met (sell when price rises)
                if ltp >= trigger_price:
                    self.logger.info(
                        f"[{self.user_id}] TRIGGER ACTIVATED: LTP Rs. {ltp} >= Trigger Rs. {trigger_price}"
                    )
                    self.logger.info(
                        f"[{self.user_id}] Placing sell order at Rs. {final_sell_price} x {order_quantity}"
                    )

                    try:
                        # Place sell order
                        # Override buy_or_sell to 2 (SELL) or side to 'SELL' depending on platform
                        sell_params = platform_params.copy()
                        if 'buy_or_sell' in sell_params:
                            sell_params['buy_or_sell'] = 2  # TMS: 2 = SELL
                        if 'side' in sell_params:
                            sell_params['side'] = 'SELL'  # ATRAD: 'SELL'

                        # Pause price fetcher during order placement
                        price_fetcher.pause()

                        # Pass current LTP as market_price for ATRAD orders
                        sell_params['market_price'] = ltp

                        # No retry - validation errors (400) won't resolve on retry
                        response = self._place_single_order(
                            price=final_sell_price,
                            quantity=order_quantity,
                            **sell_params
                        )

                        # Resume price fetcher after order placement
                        price_fetcher.resume()

                        self.logger.info(f"[{self.user_id}] Sell order placed successfully")
                        order_placed = True
                        last_response = response

                    except Exception as e:
                        # Resume price fetcher on error
                        price_fetcher.resume()
                        self.logger.error(f"[{self.user_id}] Failed to place sell order: {str(e)}")
                        # Don't retry - raise immediately (400 errors are validation issues)
                        raise

                else:
                    # Not triggered yet
                    self.logger.debug(
                        f"[{self.user_id}] LTP Rs. {ltp} < Trigger Rs. {trigger_price} - waiting..."
                    )

                # Sleep before next check
                time.sleep(poll_interval_ms / 1000)

        finally:
            # Stop background services
            price_fetcher.stop()
            self._cleanup_token_manager(token_manager)

        self.logger.info(f"[{self.user_id}] TRIGGER SELL COMPLETE")
        return last_response


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
        from api import ATRADClient

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
        from services.atrad_price_fetcher import ATRADPriceFetcher, ATRADMultiUserPriceFetcher, ATRADFetchUser

        if len(fetch_clients) > 1:
            # Multi-user ATRAD
            fetch_users = [
                ATRADFetchUser(
                    name=f"ATRADFetchUser{i+1}",
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
                requests_per_user=requests_per_user
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
        from services.price_fetcher import PriceFetcher, MultiUserPriceFetcher, FetchUser
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
                        name=f"FetchUser{i+1}",
                        client=client,
                        fetch_security_id=user_fetch_id
                    )
                )

            requests_per_user = self.client.user_config.trigger_mode_requests_per_fetch_user
            return MultiUserPriceFetcher(
                fetch_users=fetch_users,
                poll_interval_ms=poll_interval_ms,
                requests_per_user=requests_per_user
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

            if increment == -1:
                self.logger.debug(
                    f"[{self.user_id}] Level {i+1}: Rs. {price} (Limit +10%){skip_marker}"
                )
            else:
                self.logger.debug(
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

        # Start market details monitoring if ATRAD
        if hasattr(price_fetcher, 'start_market_details'):
            price_fetcher.start_market_details()

        try:
            # Pre-wait if configured
            if just_buy_pre_wait_ms > 0:
                self.logger.info(f"[{self.user_id}] Just Buy pre-wait: {just_buy_pre_wait_ms}ms")
                time.sleep(just_buy_pre_wait_ms / 1000.0)

            # Thread coordination
            success_flag = threading.Event()
            success_response = {'response': None}
            threads_lock = threading.Lock()
            active_threads = []

            def place_just_buy_order(thread_id: int):
                """Place a single order in a separate thread"""
                try:
                    if success_flag.is_set():
                        return

                    self.logger.debug(
                        f"[{self.user_id}] Just Buy Thread #{thread_id}: Placing order at Rs. {final_price}"
                    )

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
            # Stop market details monitoring if ATRAD
            if hasattr(price_fetcher, 'stop_market_details'):
                price_fetcher.stop_market_details()

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
    ) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        Wait for no_ladder trigger with dynamic polling and optional just_buy.

        Returns:
            Tuple of (triggered: bool, response: Optional[Dict])
        """
        # If already triggered (from multi-queue), execute just_buy immediately if enabled
        if already_triggered and just_buy:
            self.logger.info(
                f"[{self.user_id}] Already triggered from multi-queue priority. "
                f"Executing JUST BUY immediately at Rs. {final_price}"
            )
            success, response = self._execute_just_buy(
                final_price=final_price,
                trigger_price=trigger_price,
                order_quantity=just_buy_params['order_quantity'],
                just_buy_interval_ms=just_buy_params['interval_ms'],
                just_buy_timeout=just_buy_params['timeout'],
                just_buy_pre_wait_ms=just_buy_params['pre_wait_ms'],
                price_fetcher=price_fetcher,
                platform_params=platform_params,
                just_buy_max_requests=just_buy_params['max_requests'],
                just_buy_fade_interval_ms=just_buy_params.get('fade_interval_ms'),
                just_buy_fade_timeout=just_buy_params.get('fade_timeout')
            )
            if success:
                return True, response
            else:
                # Just buy failed during multi-queue trigger return and move to next order
                self.logger.warning(f"[{self.user_id}] Just buy failed.")
                return False, None

        self.logger.info(
            f"[{self.user_id}] NO LADDER MODE: Waiting for LTP >= Rs. {trigger_price} "
            f"to place FINAL order at Rs. {final_price}"
        )
        self.logger.info(
            f"[{self.user_id}] Dynamic polling: Fast={fast_poll_ms}ms, Slow={slow_poll_ms}ms, "
            f"Switch threshold=Rs. {switch_threshold}"
        )
        if just_buy:
            self.logger.info(
                f"[{self.user_id}] JUST BUY MODE enabled: Will aggressively place orders "
                f"when switch threshold is reached"
            )

        # Polling state
        using_fast_poll = True
        permanently_fast = False
        slow_sleep = slow_poll_ms / 5000.0
        fast_sleep = fast_poll_ms / 5000.0

        while True:
            ltp = price_fetcher.get_latest_ltp()

            if ltp is not None:
                # Check if triggered
                if ltp >= trigger_price:
                    self.logger.info(
                        f"[{self.user_id}] TRIGGERED! LTP={ltp} >= Rs. {trigger_price}. "
                        f"Placing final order at Rs. {final_price}"
                    )
                    return True, None

                # Dynamic polling optimization
                if not permanently_fast:
                    if using_fast_poll and ltp < switch_threshold:
                        # Switch to slow polling
                        using_fast_poll = False
                        self.logger.info(
                            f"[{self.user_id}] LTP Rs. {ltp} < Rs. {switch_threshold} - "
                            f"switching to SLOW polling ({slow_poll_ms}ms, cooldown OFF)"
                        )
                        if hasattr(price_fetcher, 'update_poll_settings'):
                            price_fetcher.update_poll_settings(slow_poll_ms, enable_cooldown=False)

                    elif not using_fast_poll and ltp >= switch_threshold:
                        # Switch to fast polling permanently
                        using_fast_poll = True
                        permanently_fast = True
                        self.logger.info(
                            f"[{self.user_id}] LTP Rs. {ltp} >= Rs. {switch_threshold} - "
                            f"switch threshold reached!"
                        )

                        # Execute just_buy if enabled
                        if just_buy:
                            success, response = self._execute_just_buy(
                                final_price=final_price,
                                trigger_price=trigger_price,
                                order_quantity=just_buy_params['order_quantity'],
                                just_buy_interval_ms=just_buy_params['interval_ms'],
                                just_buy_timeout=just_buy_params['timeout'],
                                just_buy_pre_wait_ms=just_buy_params['pre_wait_ms'],
                                price_fetcher=price_fetcher,
                                platform_params=platform_params,
                                just_buy_max_requests=just_buy_params['max_requests'],
                                just_buy_fade_interval_ms=just_buy_params.get('fade_interval_ms'),
                                just_buy_fade_timeout=just_buy_params.get('fade_timeout')
                            )

                            if success:
                                return True, response

                        # Update to fast polling
                        self.logger.info(
                            f"[{self.user_id}] Switching to FAST polling ({fast_poll_ms}ms, cooldown ON) PERMANENTLY"
                        )
                        if hasattr(price_fetcher, 'update_poll_settings'):
                            price_fetcher.update_poll_settings(fast_poll_ms, enable_cooldown=True)

            # Sleep based on current polling mode
            try:
                sleep_duration = slow_sleep if not using_fast_poll else fast_sleep
                time.sleep(sleep_duration)
            except KeyboardInterrupt:
                self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                raise

    def _wait_for_skip_first_trigger(
        self,
        price_fetcher: Any,
        first_price: float,
        slow_poll_ms: int
    ) -> None:
        """Wait for initial trigger when skip_first is enabled."""
        self.logger.info(
            f"[{self.user_id}] Skip-first enabled: waiting for LTP >= Rs. {first_price}"
        )

        sleep_duration = slow_poll_ms / 5000.0

        while True:
            ltp = price_fetcher.get_latest_ltp()

            if ltp is not None and ltp >= first_price:
                self.logger.info(
                    f"[{self.user_id}] Initial trigger reached! LTP={ltp} >= "
                    f"Rs. {first_price}. Starting from level 2."
                )
                return

            try:
                time.sleep(sleep_duration)
            except KeyboardInterrupt:
                self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                raise

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
        target_price = price_levels[current_level_index]

        if increment_pct == -1:
            self.logger.info(
                f"[{self.user_id}] Waiting for LTP >= Rs. {trigger_price} "
                f"to place order at Rs. {target_price} (Limit +10%)"
            )
        else:
            self.logger.info(
                f"[{self.user_id}] Waiting for LTP >= Rs. {trigger_price} "
                f"to place order at Rs. {target_price} (+{increment_pct}%)"
            )

        while True:
            ltp = price_fetcher.get_latest_ltp()

            if ltp is not None and ltp >= trigger_price:
                # Check for level skips (LTP jumped ahead)
                while current_level_index < len(price_levels) - 1 and ltp >= price_levels[current_level_index]:
                    self.logger.warning(
                        f"[{self.user_id}] LTP={ltp} >= Rs. {price_levels[current_level_index]}, "
                        f"skipping missed level {current_level_index + 1}"
                    )
                    current_level_index += 1

                # Skip second-to-last if needed
                if current_level_index == second_last_index and skip_second_last:
                    self.logger.info(
                        f"[{self.user_id}] Skipping second-to-last level {current_level_index + 1} "
                        f"(Rs. {price_levels[current_level_index]}) as requested"
                    )
                    current_level_index += 1

                self.logger.info(
                    f"[{self.user_id}] TRIGGERED! LTP={ltp} >= "
                    f"Rs. {trigger_price}. Placing order at Rs. {price_levels[current_level_index]}"
                )

                # Start market details for normal trigger
                if hasattr(price_fetcher, 'start_market_details'):
                    self.logger.info(f"[{self.user_id}] Starting market details monitoring for order placement")
                    price_fetcher.start_market_details()

                return ltp, current_level_index

            try:
                time.sleep(0.05)
            except KeyboardInterrupt:
                self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                raise

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
        self.logger.info(
            f"[{self.user_id}] Placing order level {level_display}/{total_levels} "
            f"at Rs. {target_price}, Qty={quantity}"
        )

        for attempt in range(1, 4):
            if attempt > 1:
                self.logger.debug(f"[{self.user_id}] Attempt #{attempt}/3")

            try:
                order_params = {**platform_params, 'market_price': ltp}
                response = self._place_single_order(
                    price=target_price,
                    quantity=quantity,
                    **order_params
                )

                if response:
                    self.logger.info(
                        f"[{self.user_id}] Order level {level_display} placed successfully"
                    )

                    # Stop market details after successful placement
                    if hasattr(price_fetcher, 'stop_market_details'):
                        price_fetcher.stop_market_details()

                    return response

            except KeyboardInterrupt:
                self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                raise
            except Exception as e:
                error_msg = str(e)

                # Log based on error type
                if "401" in error_msg or "Unauthorized" in error_msg:
                    self.logger.debug(f"[{self.user_id}] Token issue, retrying")
                elif "400" in error_msg or "Bad Request" in error_msg:
                    self.logger.warning(
                        f"[{self.user_id}] Error placing order level {level_display}: {error_msg}"
                    )
                else:
                    self.logger.error(
                        f"[{self.user_id}] Error placing order level {level_display}: {error_msg}"
                    )

                # Retry delay
                try:
                    time.sleep(1)
                except KeyboardInterrupt:
                    self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                    raise

        return None

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
        # Check if should skip this level
        if current_level_index == second_last_index and skip_second_last:
            self.logger.info(
                f"[{self.user_id}] Skipping second-to-last level {current_level_index + 1} "
                f"(Rs. {price_levels[current_level_index]}) as requested"
            )
            return True, None, current_level_index + 1

        target_price = price_levels[current_level_index]
        increment_pct = actual_increments[current_level_index]

        # Wait for trigger if not first order
        if current_level_index > 0:
            trigger_price = price_levels[current_level_index - 1]
            ltp, current_level_index = self._wait_for_ladder_trigger(
                price_fetcher, trigger_price, increment_pct,
                current_level_index, price_levels, actual_increments,
                second_last_index, skip_second_last
            )

            # Update target after potential level skips
            target_price = price_levels[current_level_index]
            increment_pct = actual_increments[current_level_index]
        else:
            # First order - place immediately
            self.logger.info(
                f"[{self.user_id}] Placing first order at Rs. {target_price}"
            )
            ltp = None

        # Determine quantity
        is_final = (current_level_index == len(price_levels) - 1)
        qty = order_quantity if is_final else (base_quantity or order_quantity)

        # Place order with retries
        response = self._place_order_with_retries(
            price_fetcher, target_price, qty, current_level_index + 1,
            len(price_levels), ltp, platform_params
        )

        if response:
            # Handle double buy for final level
            if double_buy and is_final:
                order_params = {**platform_params, 'market_price': ltp}
                self._execute_double_buy(
                    price=target_price,
                    quantity=qty,
                    double_buy_quantity=double_buy_quantity,
                    **order_params
                )

            # Small delay between orders
            if current_level_index + 1 < len(price_levels):
                try:
                    time.sleep(0.01)
                except KeyboardInterrupt:
                    self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                    raise

            return True, response, current_level_index + 1
        else:
            # Failed after retries
            self.logger.warning(
                f"[{self.user_id}] Failed to place order at Rs. {target_price} "
                f"after 3 attempts. Skipping to next level."
            )
            return False, None, current_level_index + 1

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
        already_triggered: bool = False
    ) -> Optional[Dict[str, Any]]:
        """
        Execute no-ladder mode: wait for trigger, optionally use just_buy, then place final order.

        Returns:
            Order response if successful, None otherwise
        """
        second_last_index = len(price_levels) - 2 if len(price_levels) >= 2 else -1

        if second_last_index < 0:
            # Edge case: only one level
            self.logger.warning(f"[{self.user_id}] Only one level available, placing immediately")
            try:
                return self._place_single_order(
                    price=price_levels[0],
                    quantity=order_quantity,
                    **platform_params
                )
            except Exception as e:
                self.logger.error(f"[{self.user_id}] Failed to place immediate order: {e}")
                return None

        trigger_price = price_levels[second_last_index]
        final_price = price_levels[-1]
        
        # Calculate switch threshold (third-last level or first level)
        third_last_index = len(price_levels) - 3 if len(price_levels) >= 3 else -1
        switch_threshold = price_levels[third_last_index] if third_last_index >= 0 else price_levels[0]

        # Get polling intervals
        fast_poll_ms = self.client.user_config.trigger_mode_poll_interval_ms
        slow_poll_ms = self.client.user_config.trigger_mode_slow_poll_interval_ms

        # Package just_buy parameters
        just_buy_params = {
            'order_quantity': order_quantity,
            'interval_ms': just_buy_interval_ms,
            'timeout': just_buy_timeout,
            'pre_wait_ms': just_buy_pre_wait_ms,
            'max_requests': just_buy_max_requests,
            'fade_interval_ms': just_buy_fade_interval_ms,
            'fade_timeout': just_buy_fade_timeout
        }

        # Wait for trigger (handles just_buy internally)
        triggered, just_buy_response = self._wait_for_no_ladder_trigger(
            price_fetcher=price_fetcher,
            trigger_price=trigger_price,
            final_price=final_price,
            switch_threshold=switch_threshold,
            fast_poll_ms=fast_poll_ms,
            slow_poll_ms=slow_poll_ms,
            just_buy=just_buy,
            just_buy_params=just_buy_params,
            platform_params=platform_params,
            already_triggered=already_triggered
        )

        # If just_buy succeeded, we're done
        if just_buy_response:
            self.logger.info(f"[{self.user_id}] Just buy succeeded, skipping normal ladder placement")
            return just_buy_response

        if not triggered:
            self.logger.warning(f"[{self.user_id}] Skipping for already triggered order in multi-queue priority")
            return None
        
        # Place final order normally
        ltp = price_fetcher.get_latest_ltp()
        order_params = {**platform_params, 'market_price': ltp}

        # Start market details for normal trigger
        if hasattr(price_fetcher, 'start_market_details'):
            self.logger.info(f"[{self.user_id}] Starting market details monitoring for order placement")
            price_fetcher.start_market_details()

        response = self._place_order_with_retries(
            price_fetcher=price_fetcher,
            target_price=final_price,
            quantity=order_quantity,
            level_display=len(price_levels),
            total_levels=len(price_levels),
            ltp=ltp,
            platform_params=order_params
        )

        return response

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
        # Wait for initial trigger if skip_first
        if skip_first:
            self._wait_for_skip_first_trigger(
                price_fetcher,
                price_levels[0],
                self.client.user_config.trigger_mode_slow_poll_interval_ms
            )
            current_level_index = 1
        else:
            current_level_index = 0

        # Place orders level by level
        last_response = None

        while current_level_index < len(price_levels):
            success, response, next_index = self._place_ladder_order(
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
                platform_params=platform_params
            )

            if response:
                last_response = response

            current_level_index = next_index

        return current_level_index, last_response


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


    def _execute_multi_queue_ipo_trigger(
        self,
        orders: List[Dict[str, Any]],
        fetch_clients: List[Any]
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
        from services.multi_symbol_price_fetcher import MultiSymbolSequentialPriceFetcher, SymbolConfig
        from api import ATRADClient

        self.logger.info(
            f"[{self.user_id}] MULTI-QUEUE MODE: Monitoring {len(orders)} orders concurrently"
        )

        # Validate all orders
        for order in orders:
            if not order.get('multi_queue'):
                raise ValueError(f"Order {order.get('id')} missing multi_queue=true")
            if not order.get('no_ladder'):
                raise ValueError(f"Order {order.get('id')} missing no_ladder=true")

        # Detect platform type
        is_atrad = len(fetch_clients) > 0 and isinstance(fetch_clients[0], ATRADClient)

        # Build symbol configurations
        symbols_config = []
        for order in orders:
            # Calculate price levels to get switch threshold
            base_price = order['price']
            limit_price = order.get('limit')
            price_levels, _ = self._calculate_price_levels(base_price, limit_price)

            # Calculate switch threshold (third-last level)
            third_last_index = len(price_levels) - 3 if len(price_levels) >= 3 else -1
            switch_threshold = price_levels[third_last_index] if third_last_index >= 0 else price_levels[0]

            symbol_config = SymbolConfig(
                symbol=order.get('symbol') if is_atrad else order['ticker'],
                switch_threshold=switch_threshold,
                order_id=order['id'],
                security_id=order.get('security_id'),
                fetch_security_id=order.get('fetch_id')
            )
            symbols_config.append(symbol_config)

            self.logger.info(
                f"[{self.user_id}] Multi-queue order: {order['id']} ({symbol_config.symbol}) "
                f"switch_threshold=Rs. {switch_threshold}"
            )

        # Create multi-symbol price fetcher
        poll_interval_ms = self.client.user_config.multi_fetch_poll_interval_ms
        sleep_duration = max(poll_interval_ms / 10000.0, 0.001)
        multi_fetcher = MultiSymbolSequentialPriceFetcher(
            symbols_config=symbols_config,
            fetch_clients=fetch_clients,
            poll_interval_ms=poll_interval_ms,
            user_id=self.user_id,
            is_atrad=is_atrad
        )

        # Start monitoring
        multi_fetcher.start()

        try:
            # Wait for priority symbol to be determined
            self.logger.info(f"[{self.user_id}] Waiting for first order to reach switch threshold...")

            while multi_fetcher.get_priority_symbol() is None:
                time.sleep(sleep_duration)

            priority_symbol = multi_fetcher.get_priority_symbol()
            all_ltps = multi_fetcher.get_all_ltps()

        finally:
            # Stop monitoring
            multi_fetcher.stop()

        # Log final LTPs
        ltps_str = ", ".join([f"{sym}={ltp if ltp else 'N/A'}" for sym, ltp in all_ltps.items()])
        self.logger.info(f"[{self.user_id}] Multi-queue final LTPs: {ltps_str}")

        # Find priority order and remaining orders
        priority_order = None
        remaining_orders = []

        for order in orders:
            symbol = order.get('symbol') if is_atrad else order['ticker']
            if symbol == priority_symbol:
                priority_order = order
            else:
                remaining_orders.append(order)

        if priority_order is None:
            raise ValueError(f"Priority symbol {priority_symbol} not found in orders")

        self.logger.info(
            f"[{self.user_id}] PRIORITY ORDER: {priority_order['id']} ({priority_symbol})"
        )

        # Execute priority order
        responses = []

        self.logger.info(f"[{self.user_id}] Executing priority order: {priority_order['id']}")
        response = self._execute_single_ipo_order(priority_order, fetch_clients, True)
        responses.append(response)

        # Execute remaining orders in order_store.json order
        for remaining_order in remaining_orders:
            remaining_symbol = remaining_order.get('symbol') if is_atrad else remaining_order['ticker']
            self.logger.info(
                f"[{self.user_id}] Executing remaining order: {remaining_order['id']} ({remaining_symbol})"
            )
            response = self._execute_single_ipo_order(remaining_order, fetch_clients, False)
            responses.append(response)

        self.logger.info(
            f"[{self.user_id}] MULTI-QUEUE COMPLETE: {len(responses)} orders executed"
        )

        return responses

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
        from api import ATRADClient

        # Detect platform
        is_atrad = len(fetch_clients) > 0 and isinstance(fetch_clients[0], ATRADClient)

        # Build platform params
        if is_atrad:
            platform_params = {
                'symbol': order['symbol'],
                'side': 'SELL' if order.get('sell') else 'BUY'
            }
        else:
            platform_params = {
                'security_id': order['security_id'],
                'exchange_security_id': order['exchange_security_id'],
                'buy_or_sell': 2 if order.get('sell') else 1,
                'order_type': 'LMT',
                'order_validity': 'DAY'
            }

        # Execute IPO trigger
        return self._execute_ipo_trigger(
            base_price=order['price'],
            order_quantity=order['quantity'],
            fetch_clients=fetch_clients,
            limit_price=order.get('limit'),
            skip_first=order.get('skip_first', False),
            skip_second_last=order.get('skip_second_last', False),
            no_ladder=order.get('no_ladder', False),
            fetch_security_id=order.get('fetch_id'),
            base_quantity=order.get('base_quantity'),
            ticker=order.get('ticker'),
            double_buy=order.get('double_buy', False),
            double_buy_quantity=order.get('double_buy_quantity'),
            just_buy=order.get('just_buy', False),
            just_buy_interval_ms=order.get('just_buy_interval_ms', 100),
            just_buy_timeout=order.get('just_buy_timeout', 5),
            just_buy_pre_wait_ms=order.get('just_buy_pre_wait_ms', 0),
            just_buy_max_requests=order.get('just_buy_max_requests'),
            just_buy_fade_interval_ms=order.get('just_buy_fade_interval_ms'),
            just_buy_fade_timeout=order.get('just_buy_fade_timeout'),
            already_triggered=already_triggered,
            **platform_params
        )

    def _execute_ipo_sell_buy_trigger(
        self,
        buyer_service: 'BaseOrderService',
        fetch_clients: List[Any],
        is_atrad_fetch: bool,
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
            is_atrad_fetch: True if fetch clients are ATRAD
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
        import threading
        import time

        # Calculate ladder
        price_levels, actual_increments = self._calculate_price_levels(base_price, limit_price)

        if len(price_levels) < 3:
            raise ValueError(
                f"Ladder must have at least 3 levels for ipo-sell-buy-trigger mode. "
                f"Current ladder has {len(price_levels)} levels. "
                f"Try increasing limit_price or adjusting base_price."
            )

        # Identify key levels
        third_last_index = len(price_levels) - 3
        second_last_index = len(price_levels) - 2
        final_index = len(price_levels) - 1

        third_last_price = price_levels[third_last_index]
        second_last_price = price_levels[second_last_index]
        final_price = price_levels[final_index]

        self.logger.info(
            f"[{self.user_id}] IPO SELL-BUY-TRIGGER: Ladder calculated with {len(price_levels)} levels"
        )
        for i, (price, inc) in enumerate(zip(price_levels, actual_increments)):
            marker = ""
            if i == third_last_index:
                marker = " [TRIGGER LEVEL]"
            elif i == second_last_index:
                marker = " [SELL LEVEL]"
            elif i == final_index:
                marker = " [BUY LEVEL]"
            self.logger.debug(f"  Level {i+1}: Rs. {price} (+{inc}%){marker}")

        self.logger.info(
            f"[{self.user_id}] Third Last: Rs. {third_last_price}, "
            f"Sell at: Rs. {second_last_price}, Buy at: Rs. {final_price}"
        )
        self.logger.info(
            f"[{self.user_id}] Sell quantity: {sell_quantity}, Buy quantity: {buy_quantity}"
        )

        # Setup price fetcher
        poll_interval_ms = self.client.user_config.trigger_mode_poll_interval_ms
        fetch_security_id = security_id or symbol

        price_fetcher = self._setup_price_fetcher(
            fetch_clients, fetch_security_id, symbol, ticker, poll_interval_ms
        )

        # Setup token managers for both seller and buyer
        seller_token_manager = self._setup_token_manager()
        buyer_token_manager = buyer_service._setup_token_manager()

        # Shared state for threading coordination
        buy_success_flag = threading.Event()
        sell_success_flag = threading.Event()
        buy_response_container = {'response': None}
        sell_response_container = {'response': None}
        threads_lock = threading.Lock()
        active_threads = []
        sleep_duration = 0.005
        try:
            self.logger.info(
                f"[{self.user_id}] Waiting for LTP >= Rs. {third_last_price} (third last level)..."
            )

            # Phase 1: Wait for third last level trigger
            while True:
                ltp = price_fetcher.get_latest_ltp()

                if ltp is not None and ltp >= third_last_price:
                    self.logger.info(
                        f"[{self.user_id}] TRIGGER REACHED! LTP={ltp} >= Rs. {third_last_price}"
                    )
                    break

                time.sleep(sleep_duration)

            price_fetcher.start_market_details()
            
            # Phase 2: Start sell_pre_wait_ms timer
            self.logger.info(
                f"[{self.user_id}] Starting sell pre-wait timer: {sell_pre_wait_ms}ms"
            )
            timer_start = time.time()
            timer_duration = sell_pre_wait_ms / 1000.0
            buy_start_offset = (sell_pre_wait_ms - 100) / 1000.0

            buy_threads_started = False
            sell_thread_started = False

            # Get current LTP for market price
            current_ltp = price_fetcher.get_latest_ltp()

            # Phase 3: Monitor timer and start buy/sell at precise times
            while time.time() - timer_start < timer_duration:
                elapsed = time.time() - timer_start

                # Start buy threads at timer-100ms
                if not buy_threads_started and elapsed >= buy_start_offset:
                    buy_threads_started = True
                    self.logger.info(
                        f"[{self.user_id}] Starting BUY threads (100ms before sell)..."
                    )

                    # Start buy thread spawner in background
                    buy_spawner_thread = threading.Thread(
                        target=self._spawn_buy_threads,
                        args=(
                            buyer_service, final_price, buy_quantity,
                            just_buy_interval_ms, just_buy_timeout,
                            buy_success_flag, buy_response_container,
                            threads_lock, active_threads,
                            is_atrad_fetch, security_id, exchange_security_id, symbol, second_last_price
                        ),
                        daemon=True
                    )
                    buy_spawner_thread.start()

                time.sleep(sleep_duration)

            # Phase 4: Timer expired - place sell order
            self.logger.info(
                f"[{self.user_id}] Timer expired! Placing SELL order at Rs. {second_last_price}..."
            )

            # Place sell order in separate thread with retry
            sell_thread = threading.Thread(
                target=self._place_sell_order_with_retry,
                args=(
                    second_last_price, sell_quantity,
                    sell_success_flag, sell_response_container,
                    is_atrad_fetch, security_id, exchange_security_id, symbol, current_ltp
                ),
                daemon=True
            )
            sell_thread.start()
            sell_thread_started = True

            # Phase 5: Wait for buy success or just_buy_timeout
            self.logger.info(
                f"[{self.user_id}] Waiting for buy order to succeed or timeout..."
            )

            buy_success_flag.wait(timeout=just_buy_timeout + 1)

            # Phase 6: Check results
            if buy_success_flag.is_set():
                self.logger.info(f"[{self.user_id}] BUY ORDER SUCCEEDED!")
            else:
                self.logger.warning(
                    f"[{self.user_id}] Buy orders did not succeed within timeout"
                )

            # Wait for sell thread to complete
            if sell_thread_started:
                sell_thread.join(timeout=2)

            if sell_success_flag.is_set():
                self.logger.info(f"[{self.user_id}] SELL ORDER SUCCEEDED!")
            else:
                self.logger.warning(f"[{self.user_id}] Sell order did not succeed")

            # Return results
            return {
                'buy_response': buy_response_container['response'],
                'sell_response': sell_response_container['response'],
                'buy_success': buy_success_flag.is_set(),
                'sell_success': sell_success_flag.is_set()
            }

        finally:
            # Cleanup
            price_fetcher.stop_market_details()
            price_fetcher.stop()
            self._cleanup_token_manager(seller_token_manager)
            buyer_service._cleanup_token_manager(buyer_token_manager)

            # Wait for all threads
            for thread in active_threads:
                if thread.is_alive():
                    thread.join(timeout=1)

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
        import time
        import threading

        thread_counter = 0
        start_time = time.time()
        interval_seconds = interval_ms / 1000.0

        def place_buy_order(thread_id: int):
            """Place single buy order in thread"""
            try:
                if success_flag.is_set():
                    return

                self.logger.debug(
                    f"[{buyer_service.user_id}] Buy Thread #{thread_id}: "
                    f"Placing order at Rs. {final_price}"
                )

                # Build platform params
                if is_atrad:
                    platform_params = {
                        'symbol': symbol,
                        'side': 'BUY',
                        'market_price': market_price
                    }
                else:
                    platform_params = {
                        'security_id': security_id,
                        'exchange_security_id': exchange_security_id,
                        'buy_or_sell': 1,  # BUY
                        'order_type': 'LMT',
                        'order_validity': 'DAY',
                        'market_price': market_price
                    }

                response = buyer_service._place_single_order(
                    price=final_price,
                    quantity=buy_quantity,
                    **platform_params
                )

                if response and not success_flag.is_set():
                    success_flag.set()
                    with threads_lock:
                        response_container['response'] = response
                    self.logger.info(
                        f"[{buyer_service.user_id}] Buy Thread #{thread_id}: SUCCESS!"
                    )

            except Exception as e:
                self.logger.debug(
                    f"[{buyer_service.user_id}] Buy Thread #{thread_id} failed: {str(e)}"
                )

        # Spawn threads at intervals
        while (time.time() - start_time) < timeout:
            if success_flag.is_set():
                self.logger.info(
                    f"[{buyer_service.user_id}] Buy success detected, stopping thread spawner"
                )
                break

            thread_counter += 1
            thread = threading.Thread(
                target=place_buy_order,
                args=(thread_counter,),
                daemon=True
            )

            with threads_lock:
                active_threads.append(thread)

            thread.start()
            time.sleep(interval_seconds)

        self.logger.info(
            f"[{buyer_service.user_id}] Buy thread spawner finished: {thread_counter} threads spawned"
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
        import time

        self.logger.info(
            f"[{self.user_id}] Placing SELL order at Rs. {sell_price} x {sell_quantity}"
        )

        # Build platform params
        if is_atrad:
            platform_params = {
                'symbol': symbol,
                'side': 'SELL',
                'market_price': market_price
            }
        else:
            platform_params = {
                'security_id': security_id,
                'exchange_security_id': exchange_security_id,
                'buy_or_sell': 2,  # SELL
                'order_type': 'LMT',
                'order_validity': 'DAY',
                'market_price': market_price
            }

        for attempt in range(1, max_retries + 1):
            try:
                self.logger.debug(
                    f"[{self.user_id}] Sell order attempt #{attempt}/{max_retries}"
                )

                response = self._place_single_order(
                    price=sell_price,
                    quantity=sell_quantity,
                    **platform_params
                )

                if response:
                    success_flag.set()
                    response_container['response'] = response
                    self.logger.info(
                        f"[{self.user_id}] SELL order SUCCESS on attempt #{attempt}!"
                    )
                    return

            except Exception as e:
                self.logger.warning(
                    f"[{self.user_id}] Sell order attempt #{attempt} failed: {str(e)}"
                )

                if attempt < max_retries:
                    time.sleep(0.5)  # Brief delay between retries

        self.logger.error(
            f"[{self.user_id}] SELL order FAILED after {max_retries} attempts"
        )
