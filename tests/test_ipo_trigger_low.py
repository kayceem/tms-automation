"""
Basic smoke tests for ipo-trigger-low mode.
Tests the lower price ladder calculation logic.
"""

import unittest
from services.base_order_service import BaseOrderService


class MockOrderService(BaseOrderService):
    """Mock implementation for testing base class methods."""

    def __init__(self):
        # Minimal init without real client
        self.user_id = "test_user"
        import logging
        self.logger = logging.getLogger(__name__)

    def _place_single_order(self, price, quantity, **params):
        return {"success": True, "price": price, "quantity": quantity}

    def _setup_token_manager(self):
        return None

    def _cleanup_token_manager(self, token_manager):
        pass

    def _get_identifier_for_logging(self, **params):
        return "test_security"


class TestIPOTriggerLow(unittest.TestCase):
    """Test suite for IPO trigger low mode."""

    def setUp(self):
        """Set up test fixtures."""
        self.service = MockOrderService()

    def test_calculate_lower_price_levels_price_greater_than_limit(self):
        """Test lower ladder calculation when price > limit."""
        # When price (1000) > limit (900), use price as reference
        price_levels, decrements = self.service._calculate_lower_price_levels(
            base_price=1000,
            limit_price=900
        )

        # Should calculate -9% and -10% of 1000
        self.assertEqual(len(price_levels), 2)
        self.assertEqual(price_levels[0], 910.0)  # 1000 * 0.91 = 910
        self.assertEqual(price_levels[1], 900.0)  # 1000 * 0.90 = 900
        self.assertEqual(decrements, [9, 10])

    def test_calculate_lower_price_levels_price_less_than_limit(self):
        """Test lower ladder calculation when price < limit."""
        # When price (1000) < limit (1100), use limit as reference with -8% and -9%
        price_levels, decrements = self.service._calculate_lower_price_levels(
            base_price=1000,
            limit_price=1100
        )

        # Should calculate -8% and -9% of 1100
        self.assertEqual(len(price_levels), 2)
        self.assertEqual(price_levels[0], 1012.0)  # 1100 * 0.92 = 1012
        self.assertEqual(price_levels[1], 1001.0)  # 1100 * 0.91 = 1001
        self.assertEqual(decrements, [8, 9])

    def test_calculate_lower_price_levels_no_limit(self):
        """Test lower ladder calculation with no limit."""
        # When no limit provided, use base_price as reference
        price_levels, decrements = self.service._calculate_lower_price_levels(
            base_price=1000,
            limit_price=None
        )

        # Should calculate -9% and -10% of 1000
        self.assertEqual(len(price_levels), 2)
        self.assertEqual(price_levels[0], 910.0)  # 1000 * 0.91 = 910
        self.assertEqual(price_levels[1], 900.0)  # 1000 * 0.90 = 900
        self.assertEqual(decrements, [9, 10])

    def test_calculate_lower_price_levels_flooring(self):
        """Test that prices are correctly floored to 1 decimal."""
        # Use a price that will test flooring
        price_levels, decrements = self.service._calculate_lower_price_levels(
            base_price=1234.56,
            limit_price=None
        )

        # 1234.56 * 0.91 = 1123.4496 -> floored to 1123.4
        # 1234.56 * 0.90 = 1111.104 -> floored to 1111.1
        self.assertEqual(price_levels[0], 1123.4)
        self.assertEqual(price_levels[1], 1111.1)


class TestOrderStoreMode(unittest.TestCase):
    """Test that ipo-trigger-low is accepted as a valid mode."""

    def test_mode_validation(self):
        """Test that ipo-trigger-low is in valid modes list."""
        from utils.order_store import OrderStore
        import tempfile
        import json
        import os

        # Create a temporary order store file with ipo-trigger-low mode
        test_order = {
            "orders": [
                {
                    "id": "test_low_trigger",
                    "execute": False,
                    "success": False,
                    "queue_id": 1,
                    "mode": "ipo-trigger-low",
                    "sell": False,
                    "ticker": "NABIL",
                    "price": 1000,
                    "quantity": 10,
                    "limit": 1100,
                    "skip_first": False,
                    "skip_second_last": False,
                    "no_ladder": False,
                    "base_quantity": None,
                    "double_buy": False,
                    "double_buy_quantity": None,
                    "time": None,
                    "refresh_before": 20
                }
            ]
        }

        # Write to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_order, f)
            temp_file = f.name

        try:
            # Load order store - should not raise ValueError
            store = OrderStore(temp_file)
            orders = store.get_executable_orders()

            # Verify order loaded successfully
            self.assertEqual(len(orders), 1)
            self.assertEqual(orders[0]['mode'], 'ipo-trigger-low')

        finally:
            # Clean up
            if os.path.exists(temp_file):
                os.unlink(temp_file)


if __name__ == '__main__':
    # Run tests
    unittest.main(verbosity=2)
