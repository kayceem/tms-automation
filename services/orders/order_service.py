"""Order service for placing and managing orders."""

import json
import math
import time
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from api import TMSClient
from services.fetchers.price_fetcher import TokenRefreshManager
from services.orders.base_order_service import BaseOrderService
from services.orders.order_dispatch import (
    normalize_fetch_clients,
    resolve_fetch_security_id,
    select_trigger_sell_client,
)
from utils.logger import get_logger

logger = get_logger(__name__)


class OrderService(BaseOrderService):
    """Service for placing orders on NEPSE TMS."""

    def __init__(self, tms_client: TMSClient):
        """
        Initialize order service with a TMS client.

        Args:
            tms_client: TMSClient instance configured for a specific user
        """
        super().__init__(tms_client, tms_client.user_id)
        self._order_success = threading.Event()
        self._lock = threading.Lock()

        logger.info(f"[{self.user_id}] OrderService initialized")

    def execute_order(
        self,
        symbol: str,
        security_id: int,
        exchange_security_id: int,
        order_price: float,
        order_quantity: int,
        buy_or_sell: int = 1,
        order_type: str = None,
        order_validity: str = None,
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
        just_buy_services: Optional[List[Any]] = None,
        timeout_ipo_trigger_low: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Execute an order immediately.

        Args:
            security_id: Security ID
            exchange_security_id: Exchange security ID
            order_price: Price per unit
            order_quantity: Number of units
            buy_or_sell: 1 for buy, 2 for sell
            order_type: Order type (LMT, MKT, etc.)
            order_validity: Order validity (DAY, IOC, etc.)
            ipo_trigger_mode: Enable IPO trigger mode (price-based ladder triggering)
            trigger_sell_mode: Enable trigger sell mode (sell when LTP reaches trigger price)
            limit_price: Optional upper limit price for IPO sniping mode
            base_quantity: Quantity for all ladder levels except final
            double_buy: Place a second order 0.5s after first order succeeds
            double_buy_quantity: Quantity for the second order
            fetch_client: TMSClient instance for fetching prices (deprecated, use fetch_clients)
            fetch_clients: List of TMSClient instances for fetching prices (required for trigger mode)
            skip_first: Skip the first ladder level (trigger mode only)
            skip_second_last: Skip the second-to-last ladder level (trigger mode only)
            no_ladder: Skip ALL ladder levels, only place final order when LTP reaches second-to-last (trigger mode only)
            fetch_id: Security ID for fetching LTP (defaults to security_id if not provided)
            base_quantity: Quantity for all ladder levels except final (defaults to order_quantity for all levels)
            ticker: Ticker symbol for resolving per-user fetch_id (optional)

        Returns:
            API response dictionary
        """

        # IPO Trigger Mode: Price-based ladder triggering
        if ipo_trigger_mode:
            actual_fetch_clients = normalize_fetch_clients(fetch_client, fetch_clients, "IPO trigger mode")
            fetch_security_id = resolve_fetch_security_id(fetch_id, security_id)

            return self._execute_ipo_trigger(
                security_id=security_id,
                exchange_security_id=exchange_security_id,
                base_price=order_price,
                order_quantity=order_quantity,
                buy_or_sell=buy_or_sell,
                order_type=order_type,
                order_validity=order_validity,
                limit_price=limit_price,
                fetch_clients=actual_fetch_clients,
                skip_first=skip_first,
                skip_second_last=skip_second_last,
                no_ladder=no_ladder,
                fetch_security_id=fetch_security_id,
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
                just_buy_services=just_buy_services,
            )

        # IPO Trigger Low Mode: Monitor LTP and place order at -9% when LTP <= -8%
        if ipo_trigger_low_mode:
            actual_fetch_clients = normalize_fetch_clients(fetch_client, fetch_clients, "IPO trigger low mode")
            fetch_security_id = resolve_fetch_security_id(fetch_id, security_id)

            return self._execute_ipo_trigger_low(
                security_id=security_id,
                exchange_security_id=exchange_security_id,
                base_price=order_price,
                order_quantity=order_quantity,
                buy_or_sell=buy_or_sell,
                order_type=order_type,
                order_validity=order_validity,
                limit_price=limit_price,
                fetch_clients=actual_fetch_clients,
                fetch_security_id=fetch_security_id,
                ticker=ticker,
                timeout_ipo_trigger_low=timeout_ipo_trigger_low
            )

        # Trigger Sell Mode: Monitor LTP and sell when price drops to trigger level
        if trigger_sell_mode:
            actual_fetch_client = select_trigger_sell_client(fetch_client, fetch_clients)
            fetch_security_id = resolve_fetch_security_id(fetch_id, security_id)

            return self._execute_trigger_sell(
                security_id=security_id,
                exchange_security_id=exchange_security_id,
                sell_price=order_price,
                order_quantity=order_quantity,
                order_type=order_type,
                order_validity=order_validity,
                fetch_client=actual_fetch_client,
                fetch_security_id=fetch_security_id,
                ticker=ticker,
                limit_price=limit_price
            )

        # Normal single order execution
        order_side = 'SELL' if buy_or_sell == 2 else 'BUY'
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
                buy_or_sell=buy_or_sell,
                order_type=order_type,
                order_validity=order_validity
            )

            logger.info(f"[{self.user_id}] Order placed successfully")
            logger.debug(f"[{self.user_id}] Response: {json.dumps(response, indent=2)}")

            # Handle double buy if enabled
            if double_buy:
                self._execute_double_buy(
                    security_id=security_id,
                    exchange_security_id=exchange_security_id,
                    order_price=order_price,
                    order_quantity=order_quantity,
                    double_buy_quantity=double_buy_quantity,
                    buy_or_sell=buy_or_sell,
                    order_type=order_type,
                    order_validity=order_validity
                )

            return response

        except Exception as e:
            logger.error(f"[{self.user_id}] Error placing order: {str(e)}", exc_info=True)
            raise

    # =========================================================================
    # Abstract Method Implementations (from BaseOrderService)
    # =========================================================================

    def _place_single_order(self, price: float, quantity: int, **params) -> Dict[str, Any]:
        """Place a single order with TMS-specific parameters."""
        return self.client.place_order(
            security_id=params['security_id'],
            exchange_security_id=params['exchange_security_id'],
            order_price=price,
            order_quantity=quantity,
            buy_or_sell=params['buy_or_sell'],
            order_type=params.get('order_type'),
            order_validity=params.get('order_validity')
        )


    def _setup_token_manager(self) -> Optional[Any]:
        """Setup TMS token refresh manager for trigger modes."""
        refresh_interval = self.client.user_config.trigger_mode_refresh_interval_seconds
        manager = TokenRefreshManager(
            tms_client=self.client,
            refresh_interval_seconds=refresh_interval
        )
        manager.start()
        return manager

    def _cleanup_token_manager(self, token_manager: Optional[Any]):
        """Stop TMS token refresh manager."""
        if token_manager:
            token_manager.stop()

    def _get_identifier_for_logging(self, **params) -> str:
        """Get human-readable identifier for logging (TMS uses security_id)."""
        return f"Security={params['security_id']}"
