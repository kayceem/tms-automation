"""Order store management for executing predefined orders."""

from pathlib import Path
from typing import Dict, Any, Optional, List

from config.loaders.file_utils import load_json_file, save_json_file
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
            self._data = load_json_file(
                str(self.store_path),
                "Order store not found: {file_path}",
            )
        except ValueError as e:
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

        # Validate multi_queue consistency across queue groups
        self._validate_multi_queue_consistency(executable_orders)

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
        valid_modes = ['normal', 'ipo', 'ipo-trigger', 'ipo-trigger-low', 'trigger-sell', 'ipo-sell-buy-trigger']
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

        # Validate just_buy_interval_ms if provided
        just_buy_interval_ms = 100  # Default
        if 'just_buy_interval_ms' in order and order['just_buy_interval_ms'] is not None:
            try:
                just_buy_interval_ms = int(order['just_buy_interval_ms'])
                if just_buy_interval_ms <= 0:
                    raise ValueError(f"Order '{order_id}' has invalid just_buy_interval_ms: {just_buy_interval_ms}")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Order '{order_id}' has invalid just_buy_interval_ms: {order['just_buy_interval_ms']}")

        # Validate just_buy_timeout if provided
        just_buy_timeout = 5  # Default
        if 'just_buy_timeout' in order and order['just_buy_timeout'] is not None:
            try:
                just_buy_timeout = int(order['just_buy_timeout'])
                if just_buy_timeout <= 0:
                    raise ValueError(f"Order '{order_id}' has invalid just_buy_timeout: {just_buy_timeout}")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Order '{order_id}' has invalid just_buy_timeout: {order['just_buy_timeout']}")

        # Validate just_buy_pre_wait_ms if provided
        just_buy_pre_wait_ms = 0  # Default
        if 'just_buy_pre_wait_ms' in order and order['just_buy_pre_wait_ms'] is not None:
            try:
                just_buy_pre_wait_ms = int(order['just_buy_pre_wait_ms'])
                if just_buy_pre_wait_ms < 0:
                    raise ValueError(f"Order '{order_id}' has invalid just_buy_pre_wait_ms: {just_buy_pre_wait_ms}")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Order '{order_id}' has invalid just_buy_pre_wait_ms: {order['just_buy_pre_wait_ms']}")

        # Validate just_buy_max_requests if provided
        just_buy_max_requests = None  # Default
        if 'just_buy_max_requests' in order and order['just_buy_max_requests'] is not None:
            try:
                just_buy_max_requests = int(order['just_buy_max_requests'])
                if just_buy_max_requests <= 0:
                    raise ValueError(f"Order '{order_id}' has invalid just_buy_max_requests: {just_buy_max_requests}")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Order '{order_id}' has invalid just_buy_max_requests: {order['just_buy_max_requests']}")

        # Validate just_buy_fade_interval_ms if provided
        just_buy_fade_interval_ms = None  # Default
        if 'just_buy_fade_interval_ms' in order and order['just_buy_fade_interval_ms'] is not None:
            try:
                just_buy_fade_interval_ms = int(order['just_buy_fade_interval_ms'])
                if just_buy_fade_interval_ms <= 0:
                    raise ValueError(f"Order '{order_id}' has invalid just_buy_fade_interval_ms: {just_buy_fade_interval_ms}")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Order '{order_id}' has invalid just_buy_fade_interval_ms: {order['just_buy_fade_interval_ms']}")

        # Validate just_buy_fade_timeout if provided
        just_buy_fade_timeout = None  # Default
        if 'just_buy_fade_timeout' in order and order['just_buy_fade_timeout'] is not None:
            try:
                just_buy_fade_timeout = int(order['just_buy_fade_timeout'])
                if just_buy_fade_timeout <= 0:
                    raise ValueError(f"Order '{order_id}' has invalid just_buy_fade_timeout: {just_buy_fade_timeout}")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Order '{order_id}' has invalid just_buy_fade_timeout: {order['just_buy_fade_timeout']}")

        # Validate just_buy only works with no_ladder
        just_buy = bool(order.get('just_buy', False))
        no_ladder = bool(order.get('no_ladder', False))
        if just_buy and not no_ladder:
            raise ValueError(
                f"Order '{order_id}': just_buy can only be used with no_ladder=true"
            )

        # Validate multi_queue
        multi_queue = bool(order.get('multi_queue', False))
        if multi_queue:
            # multi_queue requires no_ladder
            if not no_ladder:
                raise ValueError(
                    f"Order '{order_id}': multi_queue requires no_ladder=true"
                )
            # multi_queue requires ipo-trigger mode
            if mode != 'ipo-trigger':
                raise ValueError(
                    f"Order '{order_id}': multi_queue requires mode='ipo-trigger'"
                )

        # Validate ipo-sell-buy-trigger mode
        if mode == 'ipo-sell-buy-trigger':
            if 'seller_config' not in order or not order['seller_config']:
                raise ValueError(f"Order '{order_id}': ipo-sell-buy-trigger requires 'seller_config'")
            if 'buyer_config' not in order or not order['buyer_config']:
                raise ValueError(f"Order '{order_id}': ipo-sell-buy-trigger requires 'buyer_config'")
            if 'sell_quantity' not in order or not order['sell_quantity']:
                raise ValueError(f"Order '{order_id}': ipo-sell-buy-trigger requires 'sell_quantity'")

            # Validate sell_quantity
            try:
                sell_quantity = int(order['sell_quantity'])
                if sell_quantity <= 0:
                    raise ValueError(f"Order '{order_id}' has invalid sell_quantity: {sell_quantity}")
            except (TypeError, ValueError) as e:
                raise ValueError(f"Order '{order_id}' has invalid sell_quantity: {order['sell_quantity']}")

            # Validate sell_pre_wait_ms if provided
            if 'sell_pre_wait_ms' in order and order['sell_pre_wait_ms'] is not None:
                try:
                    sell_pre_wait_ms = int(order['sell_pre_wait_ms'])
                    if sell_pre_wait_ms < 0:
                        raise ValueError(f"Order '{order_id}' has invalid sell_pre_wait_ms: {sell_pre_wait_ms}")
                except (TypeError, ValueError) as e:
                    raise ValueError(f"Order '{order_id}' has invalid sell_pre_wait_ms: {order['sell_pre_wait_ms']}")

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
            'sell': bool(order.get('sell', False)),
            'skip_first': bool(order.get('skip_first', False)),
            'skip_second_last': bool(order.get('skip_second_last', False)),
            'no_ladder': no_ladder,
            'double_buy': bool(order.get('double_buy', False)),
            'double_buy_quantity': double_buy_quantity,
            'just_buy': just_buy,
            'just_buy_interval_ms': just_buy_interval_ms,
            'just_buy_timeout': just_buy_timeout,
            'just_buy_pre_wait_ms': just_buy_pre_wait_ms,
            'just_buy_max_requests': just_buy_max_requests,
            'just_buy_fade_interval_ms': just_buy_fade_interval_ms,
            'just_buy_fade_timeout': just_buy_fade_timeout,
            'multi_queue': multi_queue,
            'seller_config': order.get('seller_config') if mode == 'ipo-sell-buy-trigger' else None,
            'buyer_config': order.get('buyer_config') if mode == 'ipo-sell-buy-trigger' else None,
            'sell_quantity': int(order['sell_quantity']) if mode == 'ipo-sell-buy-trigger' and 'sell_quantity' in order else None,
            'sell_pre_wait_ms': int(order.get('sell_pre_wait_ms', 5000)) if mode == 'ipo-sell-buy-trigger' else 5000
        }

        logger.debug(f"Order '{order_id}' validated successfully")
        return normalized

    def _validate_multi_queue_consistency(self, orders: List[Dict[str, Any]]) -> None:
        """
        Validate that all orders with the same queue_id have consistent multi_queue values.

        Args:
            orders: List of validated orders

        Raises:
            ValueError: If multi_queue values are inconsistent within a queue group
        """
        from collections import defaultdict

        # Group orders by queue_id
        queue_groups = defaultdict(list)
        for order in orders:
            queue_id = order.get('queue_id', 999)
            queue_groups[queue_id].append(order)

        # Check each queue group for consistency
        for queue_id, group_orders in queue_groups.items():
            if len(group_orders) <= 1:
                continue  # Single order, no consistency check needed

            # Check if all orders have the same multi_queue value
            multi_queue_values = {order.get('multi_queue', False) for order in group_orders}

            if len(multi_queue_values) > 1:
                # Inconsistent multi_queue values
                order_ids = [order.get('id', 'unknown') for order in group_orders]
                raise ValueError(
                    f"Orders in queue {queue_id} have inconsistent multi_queue values: {', '.join(order_ids)}\n"
                    f"All orders with the same queue_id must have the same multi_queue setting."
                )

            # If multi_queue is true, validate requirements
            if True in multi_queue_values:
                # Check minimum 2 orders for multi_queue
                if len(group_orders) < 2:
                    order_id = group_orders[0].get('id', 'unknown')
                    logger.warning(
                        f"Order '{order_id}' has multi_queue=true but is alone in queue {queue_id}. "
                        f"Multi-queue requires at least 2 orders."
                    )

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
            save_json_file(str(self.store_path), self._data)
            logger.debug(f"Order store saved to {self.store_path}")
        except Exception as e:
            logger.error(f"Failed to save order store: {e}")
            raise

    def save(self):
        """Public save wrapper for callers that mutate store data."""
        self._save_store()

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get a single order by id."""
        for order in self._data.get('orders', []):
            if order.get('id') == order_id:
                return order
        return None

    def _prepare_order_for_storage(
        self,
        order: Dict[str, Any],
        *,
        existing_order: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        normalized = self.validate_order(order)
        merged = dict(existing_order or {})
        merged.update(order)
        merged.update(normalized)

        if existing_order is not None:
            merged.setdefault('execute', existing_order.get('execute', False))
            merged.setdefault('success', existing_order.get('success', False))
        else:
            merged['execute'] = bool(order.get('execute', False))
            merged['success'] = bool(order.get('success', False))

        return merged

    def add_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and append a new order."""
        order_id = order.get('id')
        if not order_id:
            raise ValueError("Order is missing required field: id")
        if self.get_order(str(order_id)) is not None:
            raise ValueError(f"Order '{order_id}' already exists")

        prepared_order = self._prepare_order_for_storage(order)
        self._data.setdefault('orders', []).append(prepared_order)
        self._save_store()
        return prepared_order

    def update_order(self, order_id: str, order: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing order by id."""
        orders = self._data.get('orders', [])
        for index, existing_order in enumerate(orders):
            if existing_order.get('id') != order_id:
                continue

            requested_id = order.get('id', order_id)
            if requested_id != order_id and self.get_order(str(requested_id)) is not None:
                raise ValueError(f"Order '{requested_id}' already exists")

            updated_order = self._prepare_order_for_storage(
                {**existing_order, **order, 'id': requested_id},
                existing_order=existing_order,
            )
            orders[index] = updated_order
            self._save_store()
            return updated_order

        raise ValueError(f"Order '{order_id}' not found")

    def remove_order(self, order_id: str) -> Dict[str, Any]:
        """Remove an order by id and save the store."""
        orders = self._data.get('orders', [])
        for index, order in enumerate(orders):
            if order.get('id') == order_id:
                removed = orders.pop(index)
                self._save_store()
                return removed
        raise ValueError(f"Order '{order_id}' not found")

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

            status = "SUCCESS" if success else ("EXECUTE" if execute else "PENDING")
            queue_str = f"Q{queue_id:02d}" if execute and not success else " - "

            lines.append(
                f"{status} | {queue_str} | {order_id:15} | {ticker:8} | "
                f"₨{price:8.1f} x {qty:4} | {mode:10}"
            )

        lines.append("=" * 70)
        return "\n".join(lines)

    def refresh(self):
        """Reload the store data from the JSON file."""
        self._load_store()