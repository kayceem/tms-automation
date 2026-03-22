"""Order store management for executing predefined orders."""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from utils.logger import get_logger

logger = get_logger(__name__)


class OrderStore:
    """Manages order store for executing predefined orders."""

    def __init__(self, store_path: str):
        """
        Initialize order store.

        Args:
            store_path: Path to order_store.json file
        """
        self.store_path = Path(store_path)
        self._data: Dict[str, Any] = {}
        self._load_store()

    def _load_store(self):
        """Load order store from JSON file."""
        if not self.store_path.exists():
            raise FileNotFoundError(
                f"Order store not found: {self.store_path}\n"
                f"Please create an order_store.json file with order definitions."
            )

        try:
            with open(self.store_path, 'r') as f:
                self._data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in order store: {e}")

        # Validate structure
        if 'orders' not in self._data:
            raise ValueError("Order store must contain 'orders' array")

        if not isinstance(self._data['orders'], list):
            raise ValueError("'orders' must be an array/list")

    def get_executable_order(self) -> Optional[Dict[str, Any]]:
        """
        Get the order marked for execution.

        Returns:
            Order dictionary if found, None otherwise

        Raises:
            ValueError: If validation fails (multiple orders marked, already successful, etc.)
        """
        orders = self._data.get('orders', [])

        if not orders:
            logger.warning("No orders found in order store")
            return None

        # Find orders marked for execution
        executable_orders = [
            order for order in orders
            if order.get('execute', False) and not order.get('success', False)
        ]

        # Check for already successful orders marked for execution
        successful_but_marked = [
            order for order in orders
            if order.get('execute', False) and order.get('success', False)
        ]

        if successful_but_marked:
            order_ids = [o.get('id', 'unknown') for o in successful_but_marked]
            raise ValueError(
                f"Found order(s) marked for execution that already succeeded: {', '.join(order_ids)}\n"
                f"Please set 'execute: false' for successful orders or create a new order."
            )

        # Validate only one order is marked for execution
        if len(executable_orders) == 0:
            logger.info("No orders marked for execution (execute=true, success=false)")
            return None

        if len(executable_orders) > 1:
            order_ids = [o.get('id', 'unknown') for o in executable_orders]
            raise ValueError(
                f"Multiple orders marked for execution: {', '.join(order_ids)}\n"
                f"Only ONE order can have 'execute: true' and 'success: false' at a time."
            )

        order = executable_orders[0]
        logger.info(f"Found executable order: {order.get('id', 'unknown')}")
        return order

    def validate_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate and normalize an order.

        Args:
            order: Order dictionary

        Returns:
            Validated and normalized order dictionary

        Raises:
            ValueError: If order is invalid
        """
        order_id = order.get('id', 'unknown')

        # Required fields
        required_fields = ['ticker', 'price', 'quantity', 'mode']
        missing_fields = [f for f in required_fields if f not in order or order[f] is None]

        if missing_fields:
            raise ValueError(
                f"Order '{order_id}' is missing required fields: {', '.join(missing_fields)}"
            )

        # Validate mode
        valid_modes = ['normal', 'ipo', 'ipo-sniper']
        mode = order['mode']
        if mode not in valid_modes:
            raise ValueError(
                f"Order '{order_id}' has invalid mode '{mode}'. "
                f"Valid modes: {', '.join(valid_modes)}"
            )

        # Validate price and quantity
        try:
            price = float(order['price'])
            if price <= 0:
                raise ValueError(f"Order '{order_id}' has invalid price: {price}")
        except (TypeError, ValueError) as e:
            raise ValueError(f"Order '{order_id}' has invalid price: {order['price']}")

        try:
            quantity = int(order['quantity'])
            if quantity <= 0:
                raise ValueError(f"Order '{order_id}' has invalid quantity: {quantity}")
        except (TypeError, ValueError) as e:
            raise ValueError(f"Order '{order_id}' has invalid quantity: {order['quantity']}")

        # Validate limit for IPO mode
        if mode == 'ipo' and 'limit' in order and order['limit'] is not None:
            try:
                limit = float(order['limit'])
                if limit <= 0:
                    raise ValueError(f"Order '{order_id}' has invalid limit: {limit}")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Order '{order_id}' has invalid limit: {order['limit']}")

        # Validate refresh_before
        if 'refresh_before' in order and order['refresh_before'] is not None:
            try:
                refresh_before = int(order['refresh_before'])
                if refresh_before < 0:
                    raise ValueError(
                        f"Order '{order_id}' has invalid refresh_before: {refresh_before}"
                    )
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"Order '{order_id}' has invalid refresh_before: {order['refresh_before']}"
                )

        # Normalize optional fields
        normalized = {
            'id': order_id,
            'ticker': str(order['ticker']).upper(),
            'price': float(order['price']),
            'quantity': int(order['quantity']),
            'mode': mode,
            'limit': float(order['limit']) if 'limit' in order and order['limit'] is not None else None,
            'time': order.get('time'),
            'refresh_before': int(order.get('refresh_before', 20)),
            'sell': bool(order.get('sell', False))
        }

        logger.debug(f"Order '{order_id}' validated successfully")
        return normalized

    def mark_success(self, order_id: str):
        """
        Mark an order as successfully executed.

        Args:
            order_id: Order ID to mark as successful
        """
        orders = self._data.get('orders', [])

        for order in orders:
            if order.get('id') == order_id:
                order['success'] = True
                order['execute'] = False  # Also disable execution
                self._save_store()
                logger.info(f"Order '{order_id}' marked as successful")
                return

        logger.warning(f"Order '{order_id}' not found, could not mark as successful")

    def mark_failed(self, order_id: str):
        """
        Mark an order as failed (keep execute=true so it can be retried).

        Args:
            order_id: Order ID
        """
        logger.info(f"Order '{order_id}' failed but remains marked for execution")
        # Don't modify the store - user can manually change if needed

    def _save_store(self):
        """Save order store back to JSON file."""
        try:
            with open(self.store_path, 'w') as f:
                json.dump(self._data, f, indent=2)
            logger.debug(f"Order store saved to {self.store_path}")
        except Exception as e:
            logger.error(f"Failed to save order store: {e}")
            raise

    def list_orders(self) -> List[Dict[str, Any]]:
        """
        Get all orders in the store.

        Returns:
            List of order dictionaries
        """
        return self._data.get('orders', [])

    def get_order_summary(self) -> str:
        """
        Get a human-readable summary of all orders.

        Returns:
            Formatted string with order summary
        """
        orders = self.list_orders()

        if not orders:
            return "No orders in store"

        lines = ["Order Store Summary:", "=" * 60]

        for order in orders:
            order_id = order.get('id', 'unknown')
            execute = order.get('execute', False)
            success = order.get('success', False)
            ticker = order.get('ticker', 'N/A')
            price = order.get('price', 0)
            qty = order.get('quantity', 0)
            mode = order.get('mode', 'normal')

            status = "✓ SUCCESS" if success else ("→ EXECUTE" if execute else "  PENDING")

            lines.append(
                f"{status} | {order_id:15} | {ticker:8} | "
                f"₨{price:8.1f} x {qty:4} | {mode:10}"
            )

        lines.append("=" * 60)
        return "\n".join(lines)
