"""ATRAD Order service for placing and managing orders."""

import json
import math
import time
from typing import Dict, Any, Optional, List
from api import ATRADClient
from services.orders.base_order_service import BaseOrderService
from services.orders.order_dispatch import (
    normalize_fetch_clients,
    resolve_fetch_security_id,
    select_trigger_sell_client,
)
from utils.logger import get_logger

logger = get_logger(__name__)


class ATRADOrderService(BaseOrderService):
    """Service for placing orders on NEPSE ATRAD."""

    def __init__(self, atrad_client: ATRADClient):
        """
        Initialize order service with an ATRAD client.

        Args:
            atrad_client: ATRADClient instance configured for a specific user
        """
        super().__init__(atrad_client, atrad_client.user_id)

        logger.info(f"[{self.user_id}] ATRADOrderService initialized")

    def execute_order(
        self,
        symbol: str,
        order_price: float,
        order_quantity: int,
        buy_or_sell: int = 1,
        ipo_trigger_mode: bool = False,
        ipo_trigger_low_mode: bool = False,
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
        just_buy: bool = False,
        just_buy_interval_ms: int = 100,
        just_buy_timeout: int = 5,
        just_buy_pre_wait_ms: int = 0,
        just_buy_max_requests: Optional[int] = None,
        just_buy_fade_interval_ms: Optional[int] = None,
        just_buy_fade_timeout: Optional[int] = None,
        timeout_ipo_trigger_low: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Execute an order immediately on ATRAD.

        Args:
            symbol: Stock symbol/ticker
            order_price: Price per unit
            order_quantity: Number of units
            buy_or_sell: 1 for buy, 2 for sell
            ipo_trigger_mode: Enable IPO trigger mode (price-based ladder triggering)
            trigger_sell_mode: Enable trigger sell mode (sell when LTP reaches trigger price)
            limit_price: Optional upper limit price for IPO trigger mode
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

        try:
            return self._dispatch_order(
                symbol=symbol,
                order_price=order_price,
                order_quantity=order_quantity,
                side=side,
                ipo_trigger_mode=ipo_trigger_mode,
                ipo_trigger_low_mode=ipo_trigger_low_mode,
                trigger_sell_mode=trigger_sell_mode,
                limit_price=limit_price,
                base_quantity=base_quantity,
                double_buy=double_buy,
                double_buy_quantity=double_buy_quantity,
                fetch_client=fetch_client,
                fetch_clients=fetch_clients,
                skip_first=skip_first,
                skip_second_last=skip_second_last,
                no_ladder=no_ladder,
                fetch_id=fetch_id,
                ticker=ticker,
                just_buy=just_buy,
                just_buy_interval_ms=just_buy_interval_ms,
                just_buy_timeout=just_buy_timeout,
                just_buy_pre_wait_ms=just_buy_pre_wait_ms,
                just_buy_max_requests=just_buy_max_requests,
                just_buy_fade_interval_ms=just_buy_fade_interval_ms,
                just_buy_fade_timeout=just_buy_fade_timeout,
                timeout_ipo_trigger_low=timeout_ipo_trigger_low,
                **kwargs,
            )
        finally:
            self.client.flush_successful_orders()

    def _dispatch_order(
        self,
        symbol,
        order_price,
        order_quantity,
        side,
        ipo_trigger_mode,
        ipo_trigger_low_mode,
        trigger_sell_mode,
        limit_price,
        base_quantity,
        double_buy,
        double_buy_quantity,
        fetch_client,
        fetch_clients,
        skip_first,
        skip_second_last,
        no_ladder,
        fetch_id,
        ticker,
        just_buy,
        just_buy_interval_ms,
        just_buy_timeout,
        just_buy_pre_wait_ms,
        just_buy_max_requests,
        just_buy_fade_interval_ms,
        just_buy_fade_timeout,
        timeout_ipo_trigger_low,
        **kwargs,
    ) -> Dict[str, Any]:
        # IPO Trigger Mode: Price-based ladder triggering
        if ipo_trigger_mode:
            actual_fetch_clients = normalize_fetch_clients(fetch_client, fetch_clients, "IPO trigger mode")

            return self._execute_ipo_trigger(
                symbol=symbol,
                base_price=order_price,
                order_quantity=order_quantity,
                side=side,
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
                just_buy=just_buy,
                just_buy_interval_ms=just_buy_interval_ms,
                just_buy_timeout=just_buy_timeout,
                just_buy_pre_wait_ms=just_buy_pre_wait_ms,
                just_buy_max_requests=just_buy_max_requests,
                just_buy_fade_interval_ms=just_buy_fade_interval_ms,
                just_buy_fade_timeout=just_buy_fade_timeout,
                **kwargs
            )

        # IPO Trigger Low Mode: Monitor LTP and place order at -9% when LTP <= -8%
        if ipo_trigger_low_mode:
            actual_fetch_clients = normalize_fetch_clients(fetch_client, fetch_clients, "IPO trigger low mode")

            return self._execute_ipo_trigger_low(
                symbol=symbol,
                base_price=order_price,
                order_quantity=order_quantity,
                side=side,
                limit_price=limit_price,
                fetch_clients=actual_fetch_clients,
                fetch_security_id=fetch_id,
                ticker=ticker,
                timeout_ipo_trigger_low=timeout_ipo_trigger_low,
                **kwargs
            )

        # Trigger Sell Mode: Monitor LTP and sell when price drops to trigger level
        if trigger_sell_mode:
            actual_fetch_client = select_trigger_sell_client(fetch_client, fetch_clients)

            return self._execute_trigger_sell(
                symbol=symbol,
                sell_price=order_price,
                order_quantity=order_quantity,
                side=side,
                fetch_client=actual_fetch_client,
                fetch_security_id=resolve_fetch_security_id(fetch_id, fetch_id),
                ticker=ticker,
                limit_price=limit_price,
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
                    **kwargs
                )

            return response

        except Exception as e:
            logger.error(f"[{self.user_id}] Error placing order: {str(e)}", exc_info=True)
            raise

    # =========================================================================
    # Abstract Method Implementations (from BaseOrderService)
    # =========================================================================

    def _place_single_order(self, price: float, quantity: int, **params) -> Dict[str, Any]:
        """Place a single order with ATRAD-specific parameters."""
        return self.client.place_order(
            symbol=params.get('symbol'),
            quantity=quantity,
            price=price,
            side=params.get('side'),
            market_price=params.get('market_price')  # Pass LTP as market price
        )

    def _setup_token_manager(self) -> Optional[Any]:
        """ATRAD auto-refreshes tokens on 401, so no token manager needed."""
        return None

    def _cleanup_token_manager(self, token_manager: Optional[Any]):
        """ATRAD auto-refreshes tokens, nothing to clean up."""
        pass

    def _get_identifier_for_logging(self, **params) -> str:
        """Get human-readable identifier for logging (ATRAD uses symbol)."""
        return f"Symbol={params['symbol']}"
