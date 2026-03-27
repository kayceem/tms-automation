"""ATRAD Order service for placing and managing orders."""

import json
import math
import time
from typing import Dict, Any, Optional, List
from api import ATRADClient
from utils.logger import get_logger

logger = get_logger(__name__)


class ATRADOrderService:
    """Service for placing orders on NEPSE ATRAD."""

    def __init__(self, atrad_client: ATRADClient):
        """
        Initialize order service with an ATRAD client.

        Args:
            atrad_client: ATRADClient instance configured for a specific user
        """
        self.client = atrad_client
        self.user_id = atrad_client.user_id

        logger.info(f"[{self.user_id}] ATRADOrderService initialized")

    def execute_order(
        self,
        symbol: str,
        order_price: float,
        order_quantity: int,
        buy_or_sell: int = 1,
        asset_select: str = None,
        board: str = None,
        order_type: str = None,
        ipo_mode: bool = False,
        ipo_sniper_mode: bool = False,
        ipo_trigger_mode: bool = False,
        trigger_sell_mode: bool = False,
        limit_price: Optional[float] = None,
        base_quantity: Optional[int] = None,
        double_buy: bool = False,
        double_buy_quantity: Optional[int] = None,
        fetch_client: Optional[Any] = None,
        fetch_clients: Optional[List[Any]] = None,
        skip_first: bool = False,
        skip_second_last: bool = False,
        no_ladder: bool = False,
        fetch_id: Optional[int] = None,
        ticker: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute an order immediately on ATRAD.

        Args:
            symbol: Stock symbol/ticker
            order_price: Price per unit
            order_quantity: Number of units
            buy_or_sell: 1 for buy, 2 for sell
            asset_select: Asset type (default: '1' for EQUITY)
            board: Board type (default: '1' for Regular)
            order_type: Order type (default: '16' for Day order)
            ipo_mode: Enable IPO sniping mode (auto-place at +2%, +4%, +6%, +8%, +10%)
            ipo_sniper_mode: Enable IPO sniper mode (aggressive +10% placement)
            ipo_trigger_mode: Enable IPO trigger mode (price-based ladder triggering)
            trigger_sell_mode: Enable trigger sell mode (sell when LTP reaches trigger price)
            limit_price: Optional upper limit price for IPO sniping mode
            base_quantity: Quantity for all ladder levels except final
            double_buy: Place a second order 0.5s after first order succeeds
            double_buy_quantity: Quantity for the second order
            fetch_client: TMSClient instance for fetching prices (deprecated, use fetch_clients)
            fetch_clients: List of TMSClient instances for fetching prices (required for trigger modes)
            skip_first: Skip the first ladder level (trigger mode only)
            skip_second_last: Skip the second-to-last ladder level (trigger mode only)
            no_ladder: Skip ALL ladder levels, only place final order when LTP reaches second-to-last (trigger mode only)
            fetch_id: Security ID for fetching LTP (defaults to symbol lookup)
            ticker: Ticker symbol for resolving per-user fetch_id (optional)
            **kwargs: Additional ATRAD-specific parameters

        Returns:
            API response dictionary
        """
        # Ensure authenticated
        self.client.ensure_authenticated()

        # Convert side
        side = 'SELL' if buy_or_sell == 2 else 'BUY'

        # IPO Trigger Mode: Price-based ladder triggering
        if ipo_trigger_mode:
            # Support both fetch_client and fetch_clients for backward compatibility
            if fetch_clients:
                actual_fetch_clients = fetch_clients
            elif fetch_client:
                actual_fetch_clients = [fetch_client]
            else:
                raise ValueError("fetch_client or fetch_clients is required for IPO trigger mode")

            return self._execute_ipo_trigger(
                symbol=symbol,
                base_price=order_price,
                order_quantity=order_quantity,
                side=side,
                asset_select=asset_select,
                board=board,
                order_type=order_type,
                limit_price=limit_price,
                fetch_clients=actual_fetch_clients,
                skip_first=skip_first,
                skip_second_last=skip_second_last,
                no_ladder=no_ladder,
                fetch_security_id=fetch_id,
                base_quantity=base_quantity,
                ticker=ticker,
                double_buy=double_buy,
                double_buy_quantity=double_buy_quantity,
                **kwargs
            )

        # Trigger Sell Mode: Monitor LTP and sell when price drops to trigger level
        if trigger_sell_mode:
            # Require fetch_client for monitoring LTP
            if not fetch_client and not fetch_clients:
                raise ValueError("fetch_client or fetch_clients is required for trigger sell mode")

            # Use single fetch_client (convert to list if needed for consistency)
            if fetch_clients:
                actual_fetch_client = fetch_clients[0]
            elif fetch_client:
                actual_fetch_client = fetch_client
            else:
                raise ValueError("fetch_client or fetch_clients is required for trigger sell mode")

            return self._execute_trigger_sell(
                symbol=symbol,
                sell_price=order_price,
                order_quantity=order_quantity,
                side=side,
                asset_select=asset_select,
                board=board,
                order_type=order_type,
                fetch_client=actual_fetch_client,
                fetch_security_id=fetch_id,
                ticker=ticker,
                **kwargs
            )

        # IPO Sniper Mode: Aggressive placement at +10%
        if ipo_sniper_mode:
            return self._execute_ipo_sniper(
                symbol=symbol,
                base_price=order_price,
                order_quantity=order_quantity,
                side=side,
                asset_select=asset_select,
                board=board,
                order_type=order_type,
                double_buy=double_buy,
                double_buy_quantity=double_buy_quantity,
                **kwargs
            )

        # IPO Mode: Sequential placement at multiple price levels
        if ipo_mode:
            return self._execute_ipo_snipe(
                symbol=symbol,
                base_price=order_price,
                order_quantity=order_quantity,
                side=side,
                asset_select=asset_select,
                board=board,
                order_type=order_type,
                limit_price=limit_price,
                base_quantity=base_quantity,
                double_buy=double_buy,
                double_buy_quantity=double_buy_quantity,
                **kwargs
            )

        # Normal single order execution
        logger.info(
            f"[{self.user_id}] Executing {side} order: "
            f"Symbol={symbol}, Price={order_price}, Qty={order_quantity}"
        )

        try:
            response = self.client.place_order(
                symbol=symbol,
                quantity=order_quantity,
                price=order_price,
                side=side,
                asset_select=asset_select,
                board=board,
                order_type=order_type,
                **kwargs
            )

            logger.info(f"[{self.user_id}] Order placed successfully")
            logger.debug(f"[{self.user_id}] Response: {json.dumps(response, indent=2)}")

            # Handle double buy if enabled
            if double_buy:
                self._execute_double_buy(
                    symbol=symbol,
                    order_price=order_price,
                    order_quantity=order_quantity,
                    double_buy_quantity=double_buy_quantity,
                    side=side,
                    asset_select=asset_select,
                    board=board,
                    order_type=order_type,
                    **kwargs
                )

            return response

        except Exception as e:
            logger.error(f"[{self.user_id}] Error placing order: {str(e)}", exc_info=True)
            raise

    def _execute_double_buy(
        self,
        symbol: str,
        order_price: float,
        order_quantity: int,
        double_buy_quantity: Optional[int],
        side: str,
        asset_select: str,
        board: str,
        order_type: str,
        **kwargs
    ):
        """Execute double buy: place a second order 0.5s after first order succeeds."""
        qty = double_buy_quantity if double_buy_quantity is not None else order_quantity

        logger.info(
            f"[{self.user_id}] Double buy enabled: waiting 0.5s before placing second order "
            f"(Price={order_price}, Qty={qty})"
        )

        time.sleep(0.5)

        try:
            logger.info(
                f"[{self.user_id}] Placing double buy {side} order: "
                f"Symbol={symbol}, Price={order_price}, Qty={qty}"
            )

            response = self.client.place_order(
                symbol=symbol,
                quantity=qty,
                price=order_price,
                side=side,
                asset_select=asset_select,
                board=board,
                order_type=order_type,
                **kwargs
            )

            logger.info(f"[{self.user_id}] Double buy order placed successfully")
            logger.debug(f"[{self.user_id}] Double buy response: {json.dumps(response, indent=2)}")

        except Exception as e:
            logger.warning(
                f"[{self.user_id}] Double buy order failed (continuing anyway): {str(e)}"
            )

    def _execute_ipo_snipe(
        self,
        symbol: str,
        base_price: float,
        order_quantity: int,
        side: str,
        asset_select: str,
        board: str,
        order_type: str,
        limit_price: Optional[float] = None,
        base_quantity: Optional[int] = None,
        double_buy: bool = False,
        double_buy_quantity: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute IPO sniping: place orders at base price, then +2%, +4%, +6%, +8%, +10%.
        If limit_price is provided, calculates +10% of limit and adjusts the ladder.
        Double buy applies only to the final order at +10%.
        Uses base_quantity for all levels except final, which uses order_quantity.

        Args:
            symbol: Stock symbol/ticker
            base_price: Starting price
            order_quantity: Number of units for final order
            side: 'BUY' or 'SELL'
            asset_select: Asset type
            board: Board type
            order_type: Order type
            limit_price: Optional upper limit price for calculations
            base_quantity: Quantity for all levels except final
            double_buy: Place second order at final level
            double_buy_quantity: Quantity for second order
            **kwargs: Additional ATRAD parameters

        Returns:
            Last API response dictionary
        """
        from typing import List

        # Pre-calculate all price levels
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

            logger.info(
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
                    logger.debug(
                        f"[{self.user_id}] Removing level +{increment}% "
                        f"(Rs. {price:.1f}) - exceeds limit"
                    )

            # Check if max_limit_price should be added as final order
            if max_limit_price > price_levels[-1]:
                # max_limit_price is greater than all standard levels, add as 11th order
                filtered_levels.append(max_limit_price)
                filtered_increments.append(-1)  # Special marker for limit-based price
                logger.info(
                    f"[{self.user_id}] Adding limit-based price Rs. {max_limit_price:.1f} "
                    f"as final order (11th level)"
                )
            elif filtered_levels and filtered_levels[-1] != max_limit_price:
                # max_limit_price is less than +10%, replace last level with it
                filtered_levels.append(max_limit_price)
                filtered_increments.append(-1)
                logger.info(
                    f"[{self.user_id}] Adding limit-based price Rs. {max_limit_price:.1f} "
                    f"as final order"
                )

            logger.info(
                f"[{self.user_id}] Final price levels after applying limit: {filtered_levels}"
            )
            price_levels = filtered_levels
            actual_increments = filtered_increments

        logger.info(
            f"[{self.user_id}] IPO SNIPING MODE: {len(price_levels)} levels, "
            f"Symbol={symbol}, Qty={order_quantity}, "
            f"Price range: Rs. {price_levels[0]:.1f} - Rs. {price_levels[-1]:.1f}"
        )

        for i, price in enumerate(price_levels):
            increment = actual_increments[i]
            if increment == -1:
                logger.debug(
                    f"[{self.user_id}] Level {i+1}: Rs. {price:.1f} (Limit +10%)"
                )
            else:
                logger.debug(
                    f"[{self.user_id}] Level {i+1}: Rs. {price:.1f} (+{increment}%)"
                )

        last_response = None

        # Execute orders at each price level
        for level_num, price in enumerate(price_levels, 1):
            increment_pct = actual_increments[level_num - 1]

            # Determine quantity for this level
            # Use base_quantity for all levels except final level
            is_final_level = (level_num == len(price_levels))
            if is_final_level:
                qty_for_level = order_quantity
            elif base_quantity is not None:
                qty_for_level = base_quantity
            else:
                qty_for_level = order_quantity

            if increment_pct == -1:
                logger.info(
                    f"[{self.user_id}] Placing order level {level_num}/{len(price_levels)} "
                    f"(Limit +10%) at Rs. {price:.1f}, Qty={qty_for_level}"
                )
            else:
                logger.info(
                    f"[{self.user_id}] Placing order level {level_num}/{len(price_levels)} "
                    f"(+{increment_pct}%) at Rs. {price:.1f}, Qty={qty_for_level}"
                )

            # Keep trying until order is placed successfully
            order_placed = False
            attempt = 0

            while not order_placed:
                attempt += 1
                if attempt > 1:
                    logger.debug(f"[{self.user_id}] Attempt #{attempt}")

                try:
                    response = self.client.place_order(
                        symbol=symbol,
                        quantity=qty_for_level,
                        price=price,
                        side=side,
                        asset_select=asset_select,
                        board=board,
                        order_type=order_type,
                        **kwargs
                    )

                    if response:
                        logger.info(
                            f"[{self.user_id}] Order level {level_num} placed successfully"
                        )
                        order_placed = True
                        last_response = response

                        # Handle double buy for final level only
                        if double_buy and is_final_level:
                            self._execute_double_buy(
                                symbol=symbol,
                                order_price=price,
                                order_quantity=qty_for_level,
                                double_buy_quantity=double_buy_quantity,
                                side=side,
                                asset_select=asset_select,
                                board=board,
                                order_type=order_type,
                                **kwargs
                            )

                        # Small delay between orders
                        if level_num < len(price_levels):
                            try:
                                time.sleep(0.1)
                            except KeyboardInterrupt:
                                logger.info(f"[{self.user_id}] IPO sniping interrupted by user")
                                raise

                except KeyboardInterrupt:
                    logger.info(f"[{self.user_id}] IPO sniping interrupted by user")
                    raise
                except Exception as e:
                    error_msg = str(e)
                    # Handle different error types with appropriate delays
                    if "session" in error_msg.lower() or "401" in error_msg:
                        logger.debug(f"[{self.user_id}] Session issue, retrying")
                        try:
                            time.sleep(1)
                        except KeyboardInterrupt:
                            logger.info(f"[{self.user_id}] IPO sniping interrupted by user")
                            raise
                    elif "400" in error_msg or "Bad Request" in error_msg:
                        logger.warning(
                            f"[{self.user_id}] Error placing order level {level_num}: {error_msg}"
                        )
                        try:
                            time.sleep(3)
                        except KeyboardInterrupt:
                            logger.info(f"[{self.user_id}] IPO sniping interrupted by user")
                            raise
                    else:
                        logger.error(
                            f"[{self.user_id}] Error placing order level {level_num}: {error_msg}"
                        )
                        try:
                            time.sleep(1)
                        except KeyboardInterrupt:
                            logger.info(f"[{self.user_id}] IPO sniping interrupted by user")
                            raise

        logger.info(
            f"[{self.user_id}] IPO SNIPING COMPLETE: All {len(price_levels)} orders placed"
        )
        return last_response

    def _execute_ipo_sniper(
        self,
        symbol: str,
        base_price: float,
        order_quantity: int,
        side: str,
        asset_select: str,
        board: str,
        order_type: str,
        double_buy: bool = False,
        double_buy_quantity: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute IPO sniper: aggressively place orders at +10% for configured duration.
        Double buy applies to each successfully placed order.

        Args:
            symbol: Stock symbol/ticker
            base_price: Starting price
            order_quantity: Number of units
            side: 'BUY' or 'SELL'
            asset_select: Asset type
            board: Board type
            order_type: Order type
            double_buy: Place a second order 0.5s after each order succeeds
            double_buy_quantity: Quantity for the second order
            **kwargs: Additional ATRAD parameters

        Returns:
            API response dictionary
        """
        from datetime import datetime, timedelta

        # Calculate +10% price and floor to 1 decimal
        target_price = base_price * 1.10
        target_price = math.floor(target_price * 10) / 10

        # Get duration from user config (defaults to 2 minutes)
        duration_minutes = self.client.user_config.ipo_sniper_duration_minutes
        end_time = datetime.now() + timedelta(minutes=duration_minutes)

        logger.info(
            f"[{self.user_id}] IPO SNIPER MODE: Symbol={symbol}, "
            f"Target price=Rs. {target_price:.1f} (+10%), Qty={order_quantity}, "
            f"Duration={duration_minutes}min (until {end_time.strftime('%H:%M:%S')})"
        )

        attempt = 0

        while datetime.now() < end_time:
            attempt += 1
            current_time = datetime.now().strftime('%H:%M:%S.%f')[:-3]

            logger.debug(f"[{self.user_id}] Attempt #{attempt} at {current_time}")

            try:
                response = self.client.place_order(
                    symbol=symbol,
                    quantity=order_quantity,
                    price=target_price,
                    side=side,
                    asset_select=asset_select,
                    board=board,
                    order_type=order_type,
                    **kwargs
                )

                if response:
                    logger.info(
                        f"[{self.user_id}] IPO SNIPER SUCCESS on attempt #{attempt} "
                        f"at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}"
                    )

                    # Handle double buy if enabled
                    if double_buy:
                        self._execute_double_buy(
                            symbol=symbol,
                            order_price=target_price,
                            order_quantity=order_quantity,
                            double_buy_quantity=double_buy_quantity,
                            side=side,
                            asset_select=asset_select,
                            board=board,
                            order_type=order_type,
                            **kwargs
                        )

                    return response

            except KeyboardInterrupt:
                logger.info(f"[{self.user_id}] IPO sniper interrupted by user")
                raise
            except Exception as e:
                error_msg = str(e)
                logger.debug(f"[{self.user_id}] Attempt #{attempt} failed: {error_msg}")

                # Handle different error types with appropriate delays
                try:
                    if "session" in error_msg.lower() or "401" in error_msg or "SESSION NOT ACTIVE" in error_msg:
                        time.sleep(1.5)
                    elif "502" in error_msg or "Bad Gateway" in error_msg or "Connection aborted" in error_msg:
                        logger.warning(f"[{self.user_id}] Server overload detected")
                        time.sleep(2.0)
                    else:
                        time.sleep(1.5)
                except KeyboardInterrupt:
                    logger.info(f"[{self.user_id}] IPO sniper interrupted by user")
                    raise

        # Timeout
        logger.error(
            f"[{self.user_id}] IPO SNIPER TIMEOUT after {attempt} attempts "
            f"({duration_minutes} minutes elapsed)"
        )
        raise Exception(f"IPO Sniper timeout: Could not place order within {duration_minutes} minutes")

    def _execute_ipo_trigger(
        self,
        symbol: str,
        base_price: float,
        order_quantity: int,
        side: str,
        asset_select: str,
        board: str,
        order_type: str,
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
        **kwargs
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
            symbol: Stock symbol/ticker
            base_price: Starting price
            order_quantity: Number of units for final level
            side: 'BUY' or 'SELL'
            asset_select: Asset type
            board: Board type
            order_type: Order type
            fetch_clients: List of TMSClient instances for fetching LTP with rotation
            limit_price: Optional upper limit price for calculations
            skip_first: Skip the first ladder level
            skip_second_last: Skip the second-to-last ladder level
            no_ladder: Skip ALL ladder levels, only place final order at limit+10%
            fetch_security_id: Security ID for fetching LTP
            base_quantity: Quantity for all ladder levels except final
            ticker: Ticker symbol for resolving per-user fetch_id
            double_buy: Place second order at final level
            double_buy_quantity: Quantity for second order
            **kwargs: Additional ATRAD parameters

        Returns:
            Last API response dictionary
        """
        from services.price_fetcher import PriceFetcher, MultiUserPriceFetcher, TokenRefreshManager, FetchUser
        from utils import get_ticker_store

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

            logger.info(
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
                    logger.debug(
                        f"[{self.user_id}] Removing level +{increment}% "
                        f"(Rs. {price:.1f}) - exceeds limit"
                    )

            # Check if max_limit_price should be added as final order
            if max_limit_price > price_levels[-1]:
                filtered_levels.append(max_limit_price)
                filtered_increments.append(-1)
                logger.info(
                    f"[{self.user_id}] Adding limit-based price Rs. {max_limit_price:.1f} "
                    f"as final order (11th level)"
                )
            elif filtered_levels and filtered_levels[-1] != max_limit_price:
                filtered_levels.append(max_limit_price)
                filtered_increments.append(-1)
                logger.info(
                    f"[{self.user_id}] Adding limit-based price Rs. {max_limit_price:.1f} "
                    f"as final order"
                )

            logger.info(
                f"[{self.user_id}] Final price levels after applying limit: {filtered_levels}"
            )
            price_levels = filtered_levels
            actual_increments = filtered_increments

        logger.info(
            f"[{self.user_id}] IPO TRIGGER MODE: {len(price_levels)} levels, "
            f"Symbol={symbol}, Qty={order_quantity}, "
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
                logger.debug(
                    f"[{self.user_id}] Level {i+1}: Rs. {price:.1f} (Limit +10%){skip_marker}"
                )
            else:
                logger.debug(
                    f"[{self.user_id}] Level {i+1}: Rs. {price:.1f} (+{increment}%){skip_marker}"
                )

        # Start price fetcher for monitoring LTP
        # Note: For ATRAD, we still use TMS fetch clients for price monitoring
        poll_interval_ms = self.client.user_config.trigger_mode_poll_interval_ms


        # Use MultiUserPriceFetcher if multiple fetch clients, otherwise single PriceFetcher
        if len(fetch_clients) > 1:
            # Multi-user fetch with rotation
            fetch_users = []
            ticker_store = get_ticker_store() if ticker else None

            for i, client in enumerate(fetch_clients):
                # Resolve fetch_id per user based on their host
                if ticker and ticker_store:
                    try:
                        user_fetch_id = ticker_store.get_fetch_id(ticker, host=client.user_config.tms_host)
                        logger.info(
                            f"[{self.user_id}] FetchUser{i+1} ({client.user_id}) using "
                            f"fetch_security_id={user_fetch_id} (host={client.user_config.tms_host})"
                        )
                    except Exception as e:
                        # Fallback to provided fetch_security_id
                        user_fetch_id = fetch_security_id
                        logger.warning(
                            f"[{self.user_id}] Could not resolve fetch_id for FetchUser{i+1}, "
                            f"using fallback: {user_fetch_id}. Error: {e}"
                        )
                else:
                    user_fetch_id = fetch_security_id

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
            # Single fetch user
            single_fetch_id = fetch_security_id
            logger.info(
                f"[{self.user_id}] Using fetch_security_id={single_fetch_id} for LTP monitoring"
            )
            price_fetcher = PriceFetcher(
                fetch_client=fetch_clients[0],
                security_id=single_fetch_id,
                poll_interval_ms=poll_interval_ms
            )

        price_fetcher.start()

        # Note: For ATRAD, we don't need token refresh manager
        # ATRAD client auto-refreshes session on 401
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
                    switched_to_slow = False  # Track if we ever switched to slow
                    permanently_fast = False  # Once we switch back to fast, stay fast forever

                    logger.info(
                        f"[{self.user_id}] NO LADDER MODE: Waiting for LTP >= Rs. {trigger_price:.1f} "
                        f"to place FINAL order at Rs. {final_price:.1f}"
                    )
                    logger.info(
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
                                logger.info(
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
                                    switched_to_slow = True
                                    logger.info(
                                        f"[{self.user_id}] LTP Rs. {ltp:.1f} < Rs. {switch_threshold:.1f} - "
                                        f"switching to SLOW polling ({slow_poll_ms}ms, cooldown OFF)"
                                    )
                                    # Update price fetcher settings if using MultiUserPriceFetcher
                                    if isinstance(price_fetcher, MultiUserPriceFetcher):
                                        price_fetcher.update_poll_settings(slow_poll_ms, enable_cooldown=False)
                                elif not using_fast_poll and ltp >= switch_threshold:
                                    # Switch back to fast polling permanently (enable cooldown)
                                    using_fast_poll = True
                                    permanently_fast = True
                                    logger.info(
                                        f"[{self.user_id}] LTP Rs. {ltp:.1f} >= Rs. {switch_threshold:.1f} - "
                                        f"switching to FAST polling ({fast_poll_ms}ms, cooldown ON) PERMANENTLY"
                                    )
                                    # Update price fetcher settings if using MultiUserPriceFetcher
                                    if isinstance(price_fetcher, MultiUserPriceFetcher):
                                        price_fetcher.update_poll_settings(fast_poll_ms, enable_cooldown=True)

                        # Sleep based on current polling mode
                        try:
                            sleep_duration = (slow_sleep_duration if not using_fast_poll else fast_sleep_duration)
                            time.sleep(sleep_duration)
                        except KeyboardInterrupt:
                            logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                            raise

                    # Place only the final order
                    current_level_index = len(price_levels) - 1
                else:
                    # Edge case: Less than 2 levels, just place the only order
                    logger.warning(f"[{self.user_id}] Only one level available, placing immediately")
                    current_level_index = 0

            # Wait for initial trigger if skip_first (and not no_ladder)
            elif skip_first:
                logger.info(
                    f"[{self.user_id}] Skip-first enabled: waiting for LTP >= Rs. {price_levels[0]:.1f}"
                )

                triggered = False
                while not triggered:
                    ltp = price_fetcher.get_latest_ltp()

                    if ltp is not None and ltp >= price_levels[0]:
                        logger.info(
                            f"[{self.user_id}] Initial trigger reached! LTP={ltp:.1f} >= "
                            f"Rs. {price_levels[0]:.1f}. Starting from level 2."
                        )
                        triggered = True
                        current_level_index = 1  # Start placing from ladder[1]
                    else:
                        try:
                            time.sleep(0.05)
                        except KeyboardInterrupt:
                            logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                            raise

            # Execute orders based on LTP triggers
            second_last_level_index = len(price_levels) - 2 if len(price_levels) >= 2 else -1
            # We place orders starting from current_level_index
            # For each level, we wait until LTP >= price_levels[level_index - 1]
            
            # Determine which level is second-to-last

            while current_level_index < len(price_levels):
                # Check if we should skip this level
                if current_level_index == second_last_level_index and skip_second_last:
                    logger.info(
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
                    logger.info(
                        f"[{self.user_id}] Placing first order at Rs. {target_price:.1f}"
                    )
                else:
                    # Wait for LTP >= previous ladder price
                    trigger_price = price_levels[current_level_index - 1]

                    if increment_pct == -1:
                        logger.info(
                            f"[{self.user_id}] Waiting for LTP >= Rs. {trigger_price:.1f} "
                            f"to place order at Rs. {target_price:.1f} (Limit +10%)"
                        )
                    else:
                        logger.info(
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
                                logger.warning(
                                    f"[{self.user_id}] LTP={ltp:.1f} >= Rs. {price_levels[current_level_index]:.1f}, "
                                    f"skipping missed level {current_level_index + 1}"
                                )
                                current_level_index += 1

                            # If we ended up at second-to-last level and should skip it, move to final level
                            if current_level_index == second_last_level_index and skip_second_last:
                                logger.info(
                                    f"[{self.user_id}] Skipping second-to-last level {current_level_index + 1} "
                                    f"(Rs. {price_levels[current_level_index]:.1f}) as requested"
                                )
                                current_level_index += 1

                            # Update target price after potential skips
                            target_price = price_levels[current_level_index]
                            increment_pct = actual_increments[current_level_index]

                            logger.info(
                                f"[{self.user_id}] TRIGGERED! LTP={ltp:.1f} >= "
                                f"Rs. {trigger_price:.1f}. Placing order at Rs. {target_price:.1f}"
                            )
                            triggered = True
                        else:
                            # Small sleep to avoid busy waiting
                            try:
                                time.sleep(0.05)
                            except KeyboardInterrupt:
                                logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
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

                logger.info(
                    f"[{self.user_id}] Placing order level {level_display}/{len(price_levels)} "
                    f"at Rs. {target_price:.1f}, Qty={qty_for_level}"
                )

                order_placed = False
                attempt = 0
                max_attempts = 3

                while not order_placed and attempt < max_attempts:
                    attempt += 1
                    if attempt > 1:
                        logger.debug(f"[{self.user_id}] Attempt #{attempt}/{max_attempts}")

                    try:
                        response = self.client.place_order(
                            symbol=symbol,
                            quantity=qty_for_level,
                            price=target_price,
                            side=side,
                            asset_select=asset_select,
                            board=board,
                            order_type=order_type,
                            **kwargs
                        )

                        if response:
                            logger.info(
                                f"[{self.user_id}] Order level {level_display} placed successfully"
                            )
                            order_placed = True
                            last_response = response

                            # Handle double buy for final level only
                            if double_buy and is_final_level:
                                self._execute_double_buy(
                                    symbol=symbol,
                                    order_price=target_price,
                                    order_quantity=qty_for_level,
                                    double_buy_quantity=double_buy_quantity,
                                    side=side,
                                    asset_select=asset_select,
                                    board=board,
                                    order_type=order_type,
                                    **kwargs
                                )

                            # Move to next level
                            current_level_index += 1

                            # Small delay between orders
                            if current_level_index < len(price_levels):
                                try:
                                    time.sleep(0.1)
                                except KeyboardInterrupt:
                                    logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                                    raise

                    except KeyboardInterrupt:
                        logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                        raise
                    except Exception as e:
                        error_msg = str(e)
                        # Handle different error types with appropriate delays
                        if "session" in error_msg.lower() or "401" in error_msg:
                            logger.debug(f"[{self.user_id}] Session issue, retrying")
                            try:
                                time.sleep(2)
                            except KeyboardInterrupt:
                                logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                                raise
                        elif "400" in error_msg or "Bad Request" in error_msg:
                            logger.warning(
                                f"[{self.user_id}] Error placing order level {level_display}: {error_msg}"
                            )
                            try:
                                time.sleep(0.5)
                            except KeyboardInterrupt:
                                logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                                raise
                        else:
                            logger.error(
                                f"[{self.user_id}] Error placing order level {level_display}: {error_msg}"
                            )
                            try:
                                time.sleep(0.5)
                            except KeyboardInterrupt:
                                logger.info(f"[{self.user_id}] IPO trigger interrupted by user")
                                raise

                # If order failed after max attempts, skip to next level
                if not order_placed:
                    logger.warning(
                        f"[{self.user_id}] Failed to place order at Rs. {target_price:.1f} "
                        f"after {max_attempts} attempts. Skipping to next level."
                    )
                    current_level_index += 1

        finally:
            # Stop background services
            price_fetcher.stop()

        total_placed = current_level_index
        logger.info(
            f"[{self.user_id}] IPO TRIGGER COMPLETE: {total_placed} orders placed"
        )
        return last_response

    def _execute_trigger_sell(
        self,
        symbol: str,
        sell_price: float,
        order_quantity: int,
        side: str,
        asset_select: str,
        board: str,
        order_type: str,
        fetch_client: Any,
        fetch_security_id: Optional[int] = None,
        ticker: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute trigger sell mode: Monitor LTP and place sell order when price rises to trigger level.

        Logic:
        - Calculate trigger_price from sell_price: trigger_price = sell_price / 1.02 (floored to 1 decimal)
        - Monitor LTP continuously with less aggressive polling (default 500ms)
        - When LTP >= trigger_price, place sell order at sell_price
        - Ensures no duplicate orders are placed

        Args:
            symbol: Stock symbol/ticker
            sell_price: The price at which to place the sell order
            order_quantity: Number of units to sell
            side: 'BUY' or 'SELL'
            asset_select: Asset type
            board: Board type
            order_type: Order type
            fetch_client: TMSClient instance for fetching LTP
            fetch_security_id: Security ID for fetching LTP
            ticker: Ticker symbol for resolving per-user fetch_id
            **kwargs: Additional ATRAD parameters

        Returns:
            Order placement response dictionary
        """
        from services.price_fetcher import PriceFetcher
        from utils import get_ticker_store

        # Calculate trigger price from sell price: trigger_price * 1.02 = sell_price
        # So: trigger_price = sell_price / 1.02
        trigger_price = sell_price / 1.02
        trigger_price = math.floor(trigger_price * 10) / 10

        logger.info(
            f"[{self.user_id}] TRIGGER SELL MODE: "
            f"Symbol={symbol}, Qty={order_quantity}, "
            f"Sell price: Rs. {sell_price:.1f}, Trigger price: Rs. {trigger_price:.1f}"
        )
        logger.info(
            f"[{self.user_id}] Will place sell order at Rs. {sell_price:.1f} when LTP >= Rs. {trigger_price:.1f}"
        )

        # Get poll interval
        poll_interval_ms = 500  # Default for sell trigger

        # Resolve fetch_security_id for this specific fetch client if ticker provided
        if ticker:
            ticker_store = get_ticker_store()
            user_fetch_id = ticker_store.get_fetch_id(ticker, host=fetch_client.user_config.tms_host)
            if user_fetch_id:
                fetch_security_id = user_fetch_id
                logger.info(
                    f"[{self.user_id}] Using host-specific fetch_id={fetch_security_id} for ticker {ticker}"
                )

        # Create price fetcher for monitoring
        price_fetcher = PriceFetcher(
            fetch_client=fetch_client,
            security_id=fetch_security_id,
            poll_interval_ms=poll_interval_ms
        )

        # Start monitoring
        price_fetcher.start()
        order_placed = False
        last_response = None

        try:
            logger.info(
                f"[{self.user_id}] Starting LTP monitoring (poll interval: {poll_interval_ms}ms)"
            )

            while not order_placed:
                # Get current LTP
                ltp = price_fetcher.get_latest_ltp()

                if ltp is None:
                    logger.debug(f"[{self.user_id}] Waiting for first LTP...")
                    time.sleep(poll_interval_ms / 1000)
                    continue

                # Check if trigger condition is met (sell when price rises)
                if ltp >= trigger_price:
                    logger.info(
                        f"[{self.user_id}] TRIGGER ACTIVATED: LTP Rs. {ltp:.1f} >= Trigger Rs. {trigger_price:.1f}"
                    )
                    logger.info(
                        f"[{self.user_id}] Placing sell order at Rs. {sell_price:.1f} x {order_quantity}"
                    )

                    try:
                        # Place sell order (side='SELL')
                        # No retry - validation errors (400) won't resolve on retry
                        response = self.client.place_order(
                            symbol=symbol,
                            quantity=order_quantity,
                            price=sell_price,
                            side=side,  # Should be 'SELL'
                            asset_select=asset_select,
                            board=board,
                            order_type=order_type,
                            **kwargs
                        )

                        logger.info(f"[{self.user_id}] Sell order placed successfully")
                        order_placed = True
                        last_response = response

                    except Exception as e:
                        logger.error(f"[{self.user_id}] Failed to place sell order: {str(e)}")
                        # Don't retry - raise immediately (400 errors are validation issues)
                        raise

                else:
                    # Not triggered yet
                    logger.debug(
                        f"[{self.user_id}] LTP Rs. {ltp:.1f} < Trigger Rs. {trigger_price:.1f} - waiting..."
                    )

                # Sleep before next check
                time.sleep(poll_interval_ms / 1000)

        finally:
            # Stop background services
            price_fetcher.stop()

        logger.info(f"[{self.user_id}] TRIGGER SELL COMPLETE")
        return last_response
