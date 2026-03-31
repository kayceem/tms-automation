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

    # =========================================================================
    # Abstract Methods (Must be implemented by subclasses)
    # =========================================================================

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

    # =========================================================================
    # Helper Methods (Shared across all platforms)
    # =========================================================================

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

    # =========================================================================
    # Template Methods (Shared logic using abstract methods)
    # =========================================================================

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
        **platform_params
    ) -> Dict[str, Any]:
        """
        Execute trigger sell mode: Monitor LTP and place sell order when price rises to trigger level.

        Logic:
        - Calculate trigger_price from sell_price: trigger_price = sell_price / 1.02 (floored to 1 decimal)
        - Monitor LTP continuously with less aggressive polling (default 500ms)
        - When LTP >= trigger_price, place sell order at sell_price
        - Ensures no duplicate orders are placed

        This mode is used to sell stocks when the price rises enough. The trigger is set slightly
        below the sell price (about 2% lower) so the sell order is placed before the price drops.

        Args:
            sell_price: The price at which to place the sell order
            order_quantity: Number of units to sell
            fetch_client: Client instance for fetching LTP (TMSClient or ATRADClient)
            fetch_security_id: Security ID/symbol for fetching LTP (optional, defaults to order security)
            ticker: Ticker symbol for resolving per-user fetch_id (optional)

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

        # Calculate trigger price from sell price: trigger_price * 1.02 = sell_price
        # So: trigger_price = sell_price / 1.02
        trigger_price = sell_price / 1.02
        trigger_price = math.floor(trigger_price * 10) / 10

        self.logger.info(
            f"[{self.user_id}] TRIGGER SELL MODE: "
            f"{identifier}, Qty={order_quantity}, "
            f"Sell price: Rs. {sell_price:.1f}, Trigger price: Rs. {trigger_price:.1f}"
        )
        self.logger.info(
            f"[{self.user_id}] Will place sell order at Rs. {sell_price:.1f} when LTP >= Rs. {trigger_price:.1f}"
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

        # Start token/session refresh manager to keep main user ready for order placement
        token_manager = self._setup_token_manager([fetch_client])
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
                        f"[{self.user_id}] TRIGGER ACTIVATED: LTP Rs. {ltp:.1f} >= Trigger Rs. {trigger_price:.1f}"
                    )
                    self.logger.info(
                        f"[{self.user_id}] Placing sell order at Rs. {sell_price:.1f} x {order_quantity}"
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
                            price=sell_price,
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
                        f"[{self.user_id}] LTP Rs. {ltp:.1f} < Trigger Rs. {trigger_price:.1f} - waiting..."
                    )

                # Sleep before next check
                time.sleep(poll_interval_ms / 1000)

        finally:
            # Stop background services
            price_fetcher.stop()
            self._cleanup_token_manager(token_manager)

        self.logger.info(f"[{self.user_id}] TRIGGER SELL COMPLETE")
        return last_response

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

        Returns:
            Last API response dictionary
        """
        from services.price_fetcher import PriceFetcher, MultiUserPriceFetcher, FetchUser
        from utils import get_ticker_store

        # Get platform-specific identifiers
        security_id = platform_params.get('security_id')
        symbol = platform_params.get('symbol')
        
        # Use fetch_security_id if provided, otherwise fall back to security_id or symbol
        if fetch_security_id is None:
            fetch_security_id = security_id or symbol
        if fetch_security_id is None:
            fetch_security_id = security_id

        # Pre-calculate all price levels (same as ipo_mode)
        price_increments = [0, 2, 2, 2, 2, 2]
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

        # If limit_price is provided, calculate +10% of limit and adjust ladder
        if limit_price is not None:
            max_limit_price = limit_price * 1.10
            max_limit_price = math.floor(max_limit_price * 10) / 10

            self.logger.info(
                f"[{self.user_id}] Limit price provided: Rs. {limit_price:.1f}, "
                f"+10% = Rs. {max_limit_price:.1f}"
            )

            # Filter out price levels that exceed the limit
            filtered_levels: List[float] = []
            filtered_increments: List[int] = []

            for price, increment in zip(price_levels, actual_increments):
                if price <= max_limit_price:
                    filtered_levels.append(price)
                    filtered_increments.append(increment)
                else:
                    self.logger.debug(
                        f"[{self.user_id}] Removing level +{increment}% "
                        f"(Rs. {price:.1f}) - exceeds limit"
                    )

            # Check if max_limit_price should be added as final order
            if max_limit_price > price_levels[-1]:
                filtered_levels.append(max_limit_price)
                filtered_increments.append(-1)
                self.logger.info(
                    f"[{self.user_id}] Adding limit-based price Rs. {max_limit_price:.1f} "
                    f"as final order (11th level)"
                )
            elif filtered_levels and filtered_levels[-1] != max_limit_price:
                filtered_levels.append(max_limit_price)
                filtered_increments.append(-1)
                self.logger.info(
                    f"[{self.user_id}] Adding limit-based price Rs. {max_limit_price:.1f} "
                    f"as final order"
                )

            self.logger.info(
                f"[{self.user_id}] Final price levels after applying limit: {filtered_levels}"
            )
            price_levels = filtered_levels
            actual_increments = filtered_increments

        self.logger.info(
            f"[{self.user_id}] IPO TRIGGER MODE: {len(price_levels)} levels, "
            f"Security={security_id}, Qty={order_quantity}, "
            f"Price range: Rs. {price_levels[0]:.1f} - Rs. {price_levels[-1]:.1f}, "
            f"Skip first: {skip_first}, Skip second-last: {skip_second_last}, No ladder: {no_ladder}"
        )

        # Determine which level is second-to-last (index before final level)
        second_last_index = len(price_levels) - 2 if len(price_levels) >= 2 else -1

        for i, price in enumerate(price_levels):
            increment = actual_increments[i]
            skip_marker = ""
            if i == 0 and skip_first:
                skip_marker = " [SKIP]"
            elif i == second_last_index and skip_second_last:
                skip_marker = " [SKIP]"

            if increment == -1:
                self.logger.debug(
                    f"[{self.user_id}] Level {i+1}: Rs. {price:.1f} (Limit +10%){skip_marker}"
                )
            else:
                self.logger.debug(
                    f"[{self.user_id}] Level {i+1}: Rs. {price:.1f} (+{increment}%){skip_marker}"
                )

        # Start price fetcher for monitoring LTP
        poll_interval_ms = self.client.user_config.trigger_mode_poll_interval_ms

        # Detect if fetch clients are ATRAD or TMS
        from api import ATRADClient
        is_atrad_fetch = len(fetch_clients) > 0 and isinstance(fetch_clients[0], ATRADClient)

        if is_atrad_fetch:
            # Use ATRAD price fetcher
            from services.atrad_price_fetcher import ATRADPriceFetcher, ATRADMultiUserPriceFetcher, ATRADFetchUser

            # Use MultiUserPriceFetcher if multiple fetch clients, otherwise single PriceFetcher
            if len(fetch_clients) > 1:
                # Multi-user ATRAD fetch with rotation
                fetch_users = []

                for i, client in enumerate(fetch_clients):
                    # ATRAD uses symbol instead of security_id
                    fetch_users.append(
                        ATRADFetchUser(
                            name=f"ATRADFetchUser{i+1}",
                            client=client,
                            symbol=symbol
                        )
                    )
                    self.logger.info(
                        f"[{self.user_id}] ATRADFetchUser{i+1} ({client.user_id}) using symbol={symbol}"
                    )

                requests_per_user = self.client.user_config.trigger_mode_requests_per_fetch_user

                price_fetcher = ATRADMultiUserPriceFetcher(
                    fetch_users=fetch_users,
                    poll_interval_ms=poll_interval_ms,
                    requests_per_user=requests_per_user
                )
            else:
                # Single ATRAD fetch user
                self.logger.info(
                    f"[{self.user_id}] Using ATRAD fetch with symbol={symbol} for LTP monitoring"
                )
                price_fetcher = ATRADPriceFetcher(
                    fetch_client=fetch_clients[0],
                    symbol=symbol,
                    poll_interval_ms=poll_interval_ms
                )
        else:
            # Use TMS price fetcher
            # Use MultiUserPriceFetcher if multiple fetch clients, otherwise single PriceFetcher
            if len(fetch_clients) > 1:
                # Multi-user fetch with rotation
                # Resolve fetch_security_id for each fetch client based on their host
                fetch_users = []
                ticker_store = get_ticker_store() if ticker else None

                for i, client in enumerate(fetch_clients):
                    # Resolve fetch_id per user based on their host
                    if ticker and ticker_store:
                        try:
                            user_fetch_id = ticker_store.get_fetch_id(ticker, host=client.user_config.tms_host)
                            self.logger.info(
                                f"[{self.user_id}] FetchUser{i+1} ({client.user_id}) using "
                                f"fetch_security_id={user_fetch_id} (host={client.user_config.tms_host})"
                            )
                        except Exception as e:
                            # Fallback to provided fetch_security_id or security_id
                            user_fetch_id = fetch_security_id if fetch_security_id else security_id
                            self.logger.warning(
                                f"[{self.user_id}] Could not resolve fetch_id for FetchUser{i+1}, "
                                f"using fallback: {user_fetch_id}. Error: {e}"
                            )
                    else:
                        # Use provided fetch_security_id or security_id
                        user_fetch_id = fetch_security_id if fetch_security_id else security_id

                    fetch_users.append(
                        FetchUser(
                            name=f"FetchUser{i+1}",
                            client=client,
                            fetch_security_id=user_fetch_id
                        )
                    )

                requests_per_user = self.client.user_config.trigger_mode_requests_per_fetch_user

                price_fetcher = MultiUserPriceFetcher(
                    fetch_users=fetch_users,
                    poll_interval_ms=poll_interval_ms,
                    requests_per_user=requests_per_user
                )
            else:
                # Single fetch user - use provided fetch_security_id or security_id
                single_fetch_id = fetch_security_id if fetch_security_id else security_id
                self.logger.info(
                    f"[{self.user_id}] Using fetch_security_id={single_fetch_id} for LTP monitoring"
                )
                price_fetcher = PriceFetcher(
                    fetch_client=fetch_clients[0],
                    security_id=single_fetch_id,
                    poll_interval_ms=poll_interval_ms
                )

        price_fetcher.start()

        # Start token refresh manager to keep main user ready
        token_manager = self._setup_token_manager()

        last_response = None

        try:
            # Determine starting index based on skip_first and no_ladder
            current_level_index = 0

            # Handle no_ladder mode: Skip all levels except final
            if no_ladder:
                # Calculate second-to-last level index for trigger
                second_last_index = len(price_levels) - 2 if len(price_levels) >= 2 else -1

                if second_last_index >= 0:
                    trigger_price = price_levels[second_last_index]
                    final_price = price_levels[-1]

                    # Calculate third-last level for slow/fast polling switch
                    third_last_index = len(price_levels) - 3 if len(price_levels) >= 3 else -1
                    switch_threshold = price_levels[third_last_index] if third_last_index >= 0 else price_levels[0]

                    # Get polling intervals from user config
                    fast_poll_ms = self.client.user_config.trigger_mode_poll_interval_ms
                    slow_poll_ms = self.client.user_config.trigger_mode_slow_poll_interval_ms

                    # Dynamic polling state
                    using_fast_poll = True  # Start with fast polling
                    permanently_fast = False  # Once we switch back to fast, stay fast forever

                    self.logger.info(
                        f"[{self.user_id}] NO LADDER MODE: Waiting for LTP >= Rs. {trigger_price:.1f} "
                        f"to place FINAL order at Rs. {final_price:.1f}"
                    )
                    self.logger.info(
                        f"[{self.user_id}] Dynamic polling: Fast={fast_poll_ms}ms, Slow={slow_poll_ms}ms, "
                        f"Switch threshold=Rs. {switch_threshold:.1f}"
                    )

                    triggered = False
                    slow_sleep_duration = slow_poll_ms / 5000.0
                    fast_sleep_duration = fast_poll_ms / 5000.0
                    while not triggered:
                        ltp = price_fetcher.get_latest_ltp()

                        if ltp is not None:
                            # Check trigger condition
                            if ltp >= trigger_price:
                                self.logger.info(
                                    f"[{self.user_id}] TRIGGERED! LTP={ltp:.1f} >= Rs. {trigger_price:.1f}. "
                                    f"Placing final order at Rs. {final_price:.1f}"
                                )
                                triggered = True
                                continue

                            # Dynamic polling optimization (only if not permanently fast)
                            if not permanently_fast:
                                if using_fast_poll and ltp < switch_threshold:
                                    # Switch to slow polling (disable cooldown)
                                    using_fast_poll = False
                                    self.logger.info(
                                        f"[{self.user_id}] LTP Rs. {ltp:.1f} < Rs. {switch_threshold:.1f} - "
                                        f"switching to SLOW polling ({slow_poll_ms}ms, cooldown OFF)"
                                    )
                                    # Update price fetcher settings if using MultiUserPriceFetcher (TMS or ATRAD)
                                    if hasattr(price_fetcher, 'update_poll_settings'):
                                        price_fetcher.update_poll_settings(slow_poll_ms, enable_cooldown=False)
                                elif not using_fast_poll and ltp >= switch_threshold:
                                    # Switch back to fast polling permanently (enable cooldown)
                                    using_fast_poll = True
                                    permanently_fast = True
                                    self.logger.info(
                                        f"[{self.user_id}] LTP Rs. {ltp:.1f} >= Rs. {switch_threshold:.1f} - "
                                        f"switching to FAST polling ({fast_poll_ms}ms, cooldown ON) PERMANENTLY"
                                    )
                                    # Update price fetcher settings if using MultiUserPriceFetcher (TMS or ATRAD)
                                    if hasattr(price_fetcher, 'update_poll_settings'):
                                        price_fetcher.update_poll_settings(fast_poll_ms, enable_cooldown=True)

                        # Sleep based on current polling mode
                        try:
                            sleep_duration = (slow_sleep_duration if not using_fast_poll else fast_sleep_duration)
                            time.sleep(sleep_duration)
                        except KeyboardInterrupt:
                            self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                            raise

                    # Place only the final order
                    current_level_index = len(price_levels) - 1
                else:
                    # Edge case: Less than 2 levels, just place the only order
                    self.logger.warning(f"[{self.user_id}] Only one level available, placing immediately")
                    current_level_index = 0

            # Wait for initial trigger if skip_first (and not no_ladder)
            elif skip_first:
                self.logger.info(
                    f"[{self.user_id}] Skip-first enabled: waiting for LTP >= Rs. {price_levels[0]:.1f}"
                )
                sleep_duration = self.client.user_config.trigger_mode_slow_poll_interval_ms / 5000.0
                triggered = False
                while not triggered:
                    ltp = price_fetcher.get_latest_ltp()

                    if ltp is not None and ltp >= price_levels[0]:
                        self.logger.info(
                            f"[{self.user_id}] Initial trigger reached! LTP={ltp:.1f} >= "
                            f"Rs. {price_levels[0]:.1f}. Starting from level 2."
                        )
                        triggered = True
                        current_level_index = 1  # Start placing from ladder[1]
                    else:
                        try:
                            time.sleep(sleep_duration)
                        except KeyboardInterrupt:
                            self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                            raise

            # Execute orders based on LTP triggers
            # We place orders starting from current_level_index
            # For each level, we wait until LTP >= price_levels[level_index - 1]

            # Determine which level is second-to-last
            second_last_level_index = len(price_levels) - 2 if len(price_levels) >= 2 else -1

            while current_level_index < len(price_levels):
                # Check if we should skip this level
                if current_level_index == second_last_level_index and skip_second_last:
                    self.logger.info(
                        f"[{self.user_id}] Skipping second-to-last level {current_level_index + 1} "
                        f"(Rs. {price_levels[current_level_index]:.1f}) as requested"
                    )
                    current_level_index += 1
                    continue

                target_price = price_levels[current_level_index]
                increment_pct = actual_increments[current_level_index]

                # Determine trigger price (the ladder level before this one)
                if current_level_index == 0:
                    # First order - place immediately without waiting
                    trigger_price = 0
                    self.logger.info(
                        f"[{self.user_id}] Placing first order at Rs. {target_price:.1f}"
                    )
                else:
                    # Wait for LTP >= previous ladder price
                    trigger_price = price_levels[current_level_index - 1]

                    if increment_pct == -1:
                        self.logger.info(
                            f"[{self.user_id}] Waiting for LTP >= Rs. {trigger_price:.1f} "
                            f"to place order at Rs. {target_price:.1f} (Limit +10%)"
                        )
                    else:
                        self.logger.info(
                            f"[{self.user_id}] Waiting for LTP >= Rs. {trigger_price:.1f} "
                            f"to place order at Rs. {target_price:.1f} (+{increment_pct}%)"
                        )

                    # Wait for trigger
                    triggered = False
                    while not triggered:
                        ltp = price_fetcher.get_latest_ltp()

                        if ltp is not None and ltp >= trigger_price:
                            # Check for edge case: LTP jumped past multiple levels
                            # Find the next level to place based on current LTP
                            while current_level_index < len(price_levels) - 1 and ltp >= price_levels[current_level_index]:
                                self.logger.warning(
                                    f"[{self.user_id}] LTP={ltp:.1f} >= Rs. {price_levels[current_level_index]:.1f}, "
                                    f"skipping missed level {current_level_index + 1}"
                                )
                                current_level_index += 1

                            # If we ended up at second-to-last level and should skip it, move to final level
                            if current_level_index == second_last_level_index and skip_second_last:
                                self.logger.info(
                                    f"[{self.user_id}] Skipping second-to-last level {current_level_index + 1} "
                                    f"(Rs. {price_levels[current_level_index]:.1f}) as requested"
                                )
                                current_level_index += 1

                            # Update target price after potential skips
                            target_price = price_levels[current_level_index]
                            increment_pct = actual_increments[current_level_index]

                            self.logger.info(
                                f"[{self.user_id}] TRIGGERED! LTP={ltp:.1f} >= "
                                f"Rs. {trigger_price:.1f}. Placing order at Rs. {target_price:.1f}"
                            )
                            triggered = True
                        else:
                            # Small sleep to avoid busy waiting
                            try:
                                time.sleep(0.05)
                            except KeyboardInterrupt:
                                self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                                raise

                # Place order at target price, retry up to 3 times then skip
                level_display = current_level_index + 1

                # Determine quantity for this level
                # Use base_quantity for all levels except final level
                is_final_level = (current_level_index == len(price_levels) - 1)
                if is_final_level:
                    qty_for_level = order_quantity
                elif base_quantity is not None:
                    qty_for_level = base_quantity
                else:
                    qty_for_level = order_quantity

                self.logger.info(
                    f"[{self.user_id}] Placing order level {level_display}/{len(price_levels)} "
                    f"at Rs. {target_price:.1f}, Qty={qty_for_level}"
                )

                order_placed = False
                attempt = 0
                max_attempts = 3

                while not order_placed and attempt < max_attempts:
                    attempt += 1
                    if attempt > 1:
                        self.logger.debug(f"[{self.user_id}] Attempt #{attempt}/{max_attempts}")

                    try:
                        # Pause price fetcher during order placement
                        # price_fetcher.pause()

                        # Pass current LTP as market_price for ATRAD orders
                        order_params = {**platform_params, 'market_price': ltp}

                        response = self._place_single_order(
                            price=target_price,
                            quantity=qty_for_level,
                            **order_params
                        )

                        if response:
                            self.logger.info(
                                f"[{self.user_id}] Order level {level_display} placed successfully"
                            )
                            order_placed = True
                            last_response = response

                            # Handle double buy for final level only
                            if double_buy and is_final_level:
                                self._execute_double_buy(
                                    price=target_price,
                                    quantity=qty_for_level,
                                    double_buy_quantity=double_buy_quantity,
                                    **order_params
                                )

                            # Move to next level
                            current_level_index += 1

                            # Small delay between orders
                            if current_level_index < len(price_levels):
                                try:
                                    time.sleep(0.01)
                                except KeyboardInterrupt:
                                    self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                                    raise
                        # Resume price fetcher after order placement
                        # price_fetcher.resume()

                    except KeyboardInterrupt:
                        # Resume price fetcher before raising
                        # price_fetcher.resume()
                        self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                        raise
                    except Exception as e:
                        # Resume price fetcher on error
                        # price_fetcher.resume()
                        error_msg = str(e)
                        # Handle different error types with appropriate delays
                        if "401" in error_msg or "Unauthorized" in error_msg:
                            self.logger.debug(f"[{self.user_id}] Token issue, retrying")
                            try:
                                time.sleep(1)
                            except KeyboardInterrupt:
                                self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                                raise
                        elif "400" in error_msg or "Bad Request" in error_msg:
                            self.logger.warning(
                                f"[{self.user_id}] Error placing order level {level_display}: {error_msg}"
                            )
                            try:
                                time.sleep(1)
                            except KeyboardInterrupt:
                                self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                                raise
                        else:
                            self.logger.error(
                                f"[{self.user_id}] Error placing order level {level_display}: {error_msg}"
                            )
                            try:
                                time.sleep(1)
                            except KeyboardInterrupt:
                                self.logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                                raise

                # If order failed after max attempts, skip to next level
                if not order_placed:
                    self.logger.warning(
                        f"[{self.user_id}] Failed to place order at Rs. {target_price:.1f} "
                        f"after {max_attempts} attempts. Skipping to next level."
                    )
                    current_level_index += 1

        finally:
            # Stop background services
            price_fetcher.stop()
            self._cleanup_token_manager(token_manager)

        total_placed = current_level_index
        self.logger.info(
            f"[{self.user_id}] IPO TRIGGER COMPLETE: {total_placed} orders placed"
        )
        return last_response
