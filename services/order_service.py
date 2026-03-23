"""Order service for placing and managing orders."""

import json
import math
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from api import TMSClient
from utils.helpers import load_client_data, load_order_params
from utils.logger import get_logger

logger = get_logger(__name__)


class OrderService:
    """Service for placing orders on NEPSE TMS."""

    def __init__(self, tms_client: TMSClient):
        """
        Initialize order service with a TMS client.

        Args:
            tms_client: TMSClient instance configured for a specific user
        """
        self.client = tms_client
        self.user_id = tms_client.user_id
        self._order_success = threading.Event()
        self._lock = threading.Lock()

        logger.info(f"[{self.user_id}] OrderService initialized")

    def execute_order(
        self,
        security_id: int,
        exchange_security_id: int,
        order_price: float,
        order_quantity: int,
        client_data_file: Optional[str] = None,
        buy_or_sell: int = 1,
        order_type: str = None,
        order_validity: str = None,
        ipo_mode: bool = False,
        ipo_sniper_mode: bool = False,
        limit_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Execute an order immediately.

        Args:
            security_id: Security ID
            exchange_security_id: Exchange security ID
            order_price: Price per unit
            order_quantity: Number of units
            client_data_file: Path to JSON file with client data (optional)
            buy_or_sell: 1 for buy, 2 for sell
            order_type: Order type (LMT, MKT, etc.)
            order_validity: Order validity (DAY, IOC, etc.)
            ipo_mode: Enable IPO sniping mode (auto-place at +2%, +4%, +6%, +8%, +10%)
            ipo_sniper_mode: Enable IPO sniper mode (aggressive +10% placement)
            limit_price: Optional upper limit price for IPO sniping mode

        Returns:
            API response dictionary
        """
        # Load client data
        client_data = self._get_client_data(client_data_file)

        # IPO Sniper Mode: Aggressive placement at +10%
        if ipo_sniper_mode:
            return self._execute_ipo_sniper(
                security_id=security_id,
                exchange_security_id=exchange_security_id,
                base_price=order_price,
                order_quantity=order_quantity,
                client_data=client_data,
                buy_or_sell=buy_or_sell,
                order_type=order_type,
                order_validity=order_validity
            )

        # IPO Mode: Sequential placement at multiple price levels
        if ipo_mode:
            return self._execute_ipo_snipe(
                security_id=security_id,
                exchange_security_id=exchange_security_id,
                base_price=order_price,
                order_quantity=order_quantity,
                client_data=client_data,
                buy_or_sell=buy_or_sell,
                order_type=order_type,
                order_validity=order_validity,
                limit_price=limit_price
            )

        # Normal single order execution
        order_side = 'BUY' if buy_or_sell == 1 else 'SELL'
        logger.info(
            f"[{self.user_id}] Executing {order_side} order: "
            f"Security={security_id}, Price={order_price}, Qty={order_quantity}, "
            f"Type={order_type or 'LMT'}, Validity={order_validity or 'DAY'}"
        )

        try:
            response = self.client.place_order(
                security_id=security_id,
                exchange_security_id=exchange_security_id,
                order_price=order_price,
                order_quantity=order_quantity,
                client_data=client_data,
                buy_or_sell=buy_or_sell,
                order_type=order_type,
                order_validity=order_validity
            )

            logger.info(f"[{self.user_id}] Order placed successfully")
            logger.debug(f"[{self.user_id}] Response: {json.dumps(response, indent=2)}")
            return response

        except Exception as e:
            logger.error(f"[{self.user_id}] Error placing order: {str(e)}", exc_info=True)
            raise

    def _get_client_data(self, client_data_file: Optional[str]) -> Dict[str, Any]:
        """
        Get client data from file, user config, or raise error.

        Args:
            client_data_file: Path to client data JSON file (optional override)

        Returns:
            Client data dictionary

        Raises:
            ValueError: If no client data is available
        """
        # Priority 1: Explicit file path provided
        if client_data_file:
            logger.debug(f"[{self.user_id}] Loading client data from {client_data_file}")
            return load_client_data(client_data_file)

        # Priority 2: Client data from user config
        if self.client.user_config.client_data:
            logger.debug(f"[{self.user_id}] Using client data from user configuration")
            return self.client.user_config.client_data

        # No client data available - raise error with helpful message
        raise ValueError(
            f"[{self.user_id}] No client data available. Please either:\n"
            f"  1. Add 'client_data' to your user configuration JSON file, OR\n"
            f"  2. Use --client-data argument to specify a client data file\n"
            f"  See client_data.example.json for the required format"
        )

    def _execute_ipo_snipe(
        self,
        security_id: int,
        exchange_security_id: int,
        base_price: float,
        order_quantity: int,
        client_data: Dict[str, Any],
        buy_or_sell: int,
        order_type: str,
        order_validity: str,
        limit_price: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Execute IPO sniping: place orders at base price, then +2%, +4%, +6%, +8%, +10%.
        If limit_price is provided, calculates +10% of limit and adjusts the ladder.

        Args:
            security_id: Security ID
            exchange_security_id: Exchange security ID
            base_price: Starting price
            order_quantity: Number of units
            client_data: Client information dictionary
            buy_or_sell: 1 for buy, 2 for sell
            order_type: Order type (LMT, MKT, etc.)
            order_validity: Order validity (DAY, IOC, etc.)
            limit_price: Optional upper limit price for calculations

        Returns:
            Last API response dictionary
        """
        # Pre-calculate all price levels
        price_increments = [0, 2, 2, 2, 2, 2]
        price_levels: List[float] = []
        actual_increments: List[int] = []

        # Calculate standard ladder prices
        for increment in price_increments:
            new_price = base_price * (1 + increment / 100)
            floored_price = math.floor(new_price * 10) / 10
            base_price = floored_price  # Update base price for next level
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
            f"Security={security_id}, Qty={order_quantity}, "
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

            if increment_pct == -1:
                logger.info(
                    f"[{self.user_id}] Placing order level {level_num}/{len(price_levels)} "
                    f"(Limit +10%) at Rs. {price:.1f}"
                )
            else:
                logger.info(
                    f"[{self.user_id}] Placing order level {level_num}/{len(price_levels)} "
                    f"(+{increment_pct}%) at Rs. {price:.1f}"
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
                        security_id=security_id,
                        exchange_security_id=exchange_security_id,
                        order_price=price,
                        order_quantity=order_quantity,
                        client_data=client_data,
                        buy_or_sell=buy_or_sell,
                        order_type=order_type,
                        order_validity=order_validity
                    )

                    if response:
                        logger.info(
                            f"[{self.user_id}] Order level {level_num} placed successfully"
                        )
                        order_placed = True
                        last_response = response

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
                    if "401" in error_msg or "Unauthorized" in error_msg:
                        logger.debug(f"[{self.user_id}] Token issue, retrying")
                        try:
                            time.sleep(0.5)
                        except KeyboardInterrupt:
                            logger.info(f"[{self.user_id}] IPO sniping interrupted by user")
                            raise
                    elif "400" in error_msg or "Bad Request" in error_msg:
                        logger.warning(
                            f"[{self.user_id}] Error placing order level {level_num}: {error_msg}"
                        )
                        try:
                            time.sleep(2.5)
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
        security_id: int,
        exchange_security_id: int,
        base_price: float,
        order_quantity: int,
        client_data: Dict[str, Any],
        buy_or_sell: int,
        order_type: str,
        order_validity: str
    ) -> Dict[str, Any]:
        """
        Execute IPO sniper: aggressively place orders at +10% for configured duration.

        Args:
            security_id: Security ID
            exchange_security_id: Exchange security ID
            base_price: Starting price
            order_quantity: Number of units
            client_data: Client information dictionary
            buy_or_sell: 1 for buy, 2 for sell
            order_type: Order type (LMT, MKT, etc.)
            order_validity: Order validity (DAY, IOC, etc.)

        Returns:
            API response dictionary
        """
        # Calculate +10% price and floor to 1 decimal
        target_price = base_price * 1.10
        target_price = math.floor(target_price * 10) / 10

        # Get duration from user config (defaults to 2 minutes)
        duration_minutes = self.client.user_config.ipo_sniper_duration_minutes
        end_time = datetime.now() + timedelta(minutes=duration_minutes)
        start_time = datetime.now()

        logger.info(
            f"[{self.user_id}] IPO SNIPER MODE: Security={security_id}, "
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
                    security_id=security_id,
                    exchange_security_id=exchange_security_id,
                    order_price=target_price,
                    order_quantity=order_quantity,
                    client_data=client_data,
                    buy_or_sell=buy_or_sell,
                    order_type=order_type,
                    order_validity=order_validity
                )

                if response:
                    logger.info(
                        f"[{self.user_id}] IPO SNIPER SUCCESS on attempt #{attempt} "
                        f"at {datetime.now().strftime('%H:%M:%S.%f')[:-3]}"
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
                    if "401" in error_msg or "Unauthorized" in error_msg or "SESSION NOT ACTIVE" in error_msg:
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
        duration_minutes = self.client.user_config.ipo_sniper_duration_minutes
        logger.error(
            f"[{self.user_id}] IPO SNIPER TIMEOUT after {attempt} attempts "
            f"({duration_minutes} minutes elapsed)"
        )
        raise Exception(f"IPO Sniper timeout: Could not place order within {duration_minutes} minutes")
