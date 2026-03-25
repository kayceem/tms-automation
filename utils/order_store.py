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

    def get_executable_orders(self) -> List[Dict[str, Any]]:
        """
        Get all orders marked for execution, sorted by queue_id.

        Returns:
            List of order dictionaries sorted by queue_id (ascending)

        Raises:
            ValueError: If validation fails (successful orders marked for execution)
        """
        orders = self._data.get('orders', [])

        if not orders:
            logger.warning("No orders found in order store")
            return []

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

        if len(executable_orders) == 0:
            logger.info("No orders marked for execution (execute=true, success=false)")
            return []

        # Sort by queue_id (default to 999 if not specified)
        executable_orders.sort(key=lambda o: o.get('queue_id', 999))

        queue_ids = [f"{o.get('id', 'unknown')} (queue:{o.get('queue_id', 999)})" for o in executable_orders]
        logger.info(f"Found {len(executable_orders)} executable order(s): {', '.join(queue_ids)}")

        return executable_orders

    def get_executable_order(self) -> Optional[Dict[str, Any]]:
        """
        Get the first order marked for execution (backward compatibility).
        Returns the order with the lowest queue_id.

        Returns:
            Order dictionary if found, None otherwise

        Raises:
            ValueError: If validation fails
        """
        orders = self.get_executable_orders()
        return orders[0] if orders else None

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
        valid_modes = ['normal', 'ipo', 'ipo-sniper', 'ipo-trigger']
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

        # Validate limit for IPO modes
        if mode in ['ipo', 'ipo-trigger'] and 'limit' in order and order['limit'] is not None:
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

        # Validate base_quantity if provided
        base_quantity = 10  # Default
        if 'base_quantity' in order and order['base_quantity'] is not None:
            try:
                base_quantity = int(order['base_quantity'])
                if base_quantity <= 0:
                    raise ValueError(f"Order '{order_id}' has invalid base_quantity: {base_quantity}")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Order '{order_id}' has invalid base_quantity: {order['base_quantity']}")

        # Validate double_buy_quantity if provided
        double_buy_quantity = None
        if 'double_buy_quantity' in order and order['double_buy_quantity'] is not None:
            try:
                double_buy_quantity = int(order['double_buy_quantity'])
                if double_buy_quantity <= 0:
                    raise ValueError(f"Order '{order_id}' has invalid double_buy_quantity: {double_buy_quantity}")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Order '{order_id}' has invalid double_buy_quantity: {order['double_buy_quantity']}")

        # Validate queue_id if provided
        queue_id = 999  # Default
        if 'queue_id' in order and order['queue_id'] is not None:
            try:
                queue_id = int(order['queue_id'])
                if queue_id <= 0:
                    raise ValueError(f"Order '{order_id}' has invalid queue_id: {queue_id}")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Order '{order_id}' has invalid queue_id: {order['queue_id']}")

        # Normalize optional fields
        normalized = {
            'id': order_id,
            'ticker': str(order['ticker']).upper(),
            'price': float(order['price']),
            'quantity': int(order['quantity']),
            'base_quantity': base_quantity,
            'queue_id': queue_id,
            'mode': mode,
            'limit': float(order['limit']) if 'limit' in order and order['limit'] is not None else None,
            'time': order.get('time'),
            'refresh_before': int(order.get('refresh_before', 20)),
            'sell': bool(order.get('sell', False)),
            'skip_first': bool(order.get('skip_first', False)),
            'skip_second_last': bool(order.get('skip_second_last', False)),
            'no_ladder': bool(order.get('no_ladder', False)),
            'double_buy': bool(order.get('double_buy', False)),
            'double_buy_quantity': double_buy_quantity
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

        lines = ["Order Store Summary:", "=" * 70]

        for order in orders:
            order_id = order.get('id', 'unknown')
            execute = order.get('execute', False)
            success = order.get('success', False)
            ticker = order.get('ticker', 'N/A')
            price = order.get('price', 0)
            qty = order.get('quantity', 0)
            mode = order.get('mode', 'normal')
            queue_id = order.get('queue_id', 999)

            status = "✓ SUCCESS" if success else ("→ EXECUTE" if execute else "  PENDING")
            queue_str = f"Q{queue_id:02d}" if execute and not success else "   "

            lines.append(
                f"{status} | {queue_str} | {order_id:15} | {ticker:8} | "
                f"₨{price:8.1f} x {qty:4} | {mode:10}"
            )

        lines.append("=" * 70)
        return "\n".join(lines)
