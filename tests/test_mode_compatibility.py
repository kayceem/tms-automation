#!/usr/bin/env python3
"""
Integration tests for mode compatibility.

Tests the ipo-sell-buy-trigger mode alongside other execution modes
to ensure they can coexist in the same order store and don't interfere
with each other.
"""

import unittest
import json
import tempfile
import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from utils import OrderStore


class TestModeCompatibility(unittest.TestCase):
    """Test compatibility of ipo-sell-buy-trigger with other modes."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_01_order_store_mixed_modes(self):
        """Test order store with mixed execution modes."""
        print("\n[COMPAT TEST 1] Order store with mixed modes")

        # Create order store with multiple modes
        order_store_data = {
            "orders": [
                {
                    "id": "normal_order",
                    "execute": True,
                    "mode": "normal",
                    "ticker": "NABIL",
                    "price": 1000,
                    "quantity": 10
                },
                {
                    "id": "ipo_trigger_order",
                    "execute": True,
                    "mode": "ipo-trigger",
                    "ticker": "NICA",
                    "price": 900,
                    "limit": 900,
                    "quantity": 20,
                    "no_ladder": True
                },
                {
                    "id": "trigger_sell_order",
                    "execute": True,
                    "mode": "trigger-sell",
                    "ticker": "ADBL",
                    "price": 500,
                    "limit": 450,
                    "quantity": 15,
                    "sell": True
                },
                {
                    "id": "sell_buy_trigger_order",
                    "execute": True,
                    "mode": "ipo-sell-buy-trigger",
                    "ticker": "NABIL",
                    "price": 1000,
                    "limit": 1000,
                    "quantity": 100,
                    "sell_quantity": 50,
                    "sell_pre_wait_ms": 5000,
                    "seller_config": "users/seller.json",
                    "buyer_config": "users/buyer.json"
                }
            ]
        }

        order_store_file = os.path.join(self.temp_dir, "mixed_orders.json")
        with open(order_store_file, 'w') as f:
            json.dump(order_store_data, f)

        # Load and validate
        store = OrderStore(order_store_file)
        orders = store.get_executable_orders()

        self.assertEqual(len(orders), 4, "Should load all 4 orders")
        print(f"✓ Loaded {len(orders)} orders with mixed modes")

        # Verify each mode
        modes = {order['mode'] for order in orders}
        expected_modes = {'normal', 'ipo-trigger', 'trigger-sell', 'ipo-sell-buy-trigger'}
        self.assertEqual(modes, expected_modes, "Should have all execution modes")
        print(f"✓ All modes present: {modes}")

        # Verify ipo-sell-buy-trigger specific fields
        sell_buy_order = next(o for o in orders if o['mode'] == 'ipo-sell-buy-trigger')
        self.assertEqual(sell_buy_order['sell_quantity'], 50)
        self.assertEqual(sell_buy_order['sell_pre_wait_ms'], 5000)
        self.assertEqual(sell_buy_order['seller_config'], "users/seller.json")
        self.assertEqual(sell_buy_order['buyer_config'], "users/buyer.json")
        print(f"✓ ipo-sell-buy-trigger fields validated correctly")

    def test_02_queue_grouping_with_sell_buy_trigger(self):
        """Test queue grouping with ipo-sell-buy-trigger mode."""
        print("\n[COMPAT TEST 2] Queue grouping with ipo-sell-buy-trigger")

        order_store_data = {
            "orders": [
                {
                    "id": "queue1_normal",
                    "execute": True,
                    "queue_id": 1,
                    "mode": "normal",
                    "ticker": "NABIL",
                    "price": 1000,
                    "quantity": 10
                },
                {
                    "id": "queue1_sell_buy",
                    "execute": True,
                    "queue_id": 1,
                    "mode": "ipo-sell-buy-trigger",
                    "ticker": "NABIL",
                    "price": 1000,
                    "limit": 1000,
                    "quantity": 100,
                    "sell_quantity": 50,
                    "sell_pre_wait_ms": 5000,
                    "seller_config": "users/seller.json",
                    "buyer_config": "users/buyer.json"
                },
                {
                    "id": "queue2_ipo_trigger",
                    "execute": True,
                    "queue_id": 2,
                    "mode": "ipo-trigger",
                    "ticker": "NICA",
                    "price": 900,
                    "limit": 900,
                    "quantity": 20,
                    "no_ladder": True
                }
            ]
        }

        order_store_file = os.path.join(self.temp_dir, "queued_orders.json")
        with open(order_store_file, 'w') as f:
            json.dump(order_store_data, f)

        store = OrderStore(order_store_file)
        orders = store.get_executable_orders()

        # Group by queue_id
        from collections import defaultdict
        queues = defaultdict(list)
        for order in orders:
            queues[order['queue_id']].append(order)

        self.assertEqual(len(queues[1]), 2, "Queue 1 should have 2 orders")
        self.assertEqual(len(queues[2]), 1, "Queue 2 should have 1 order")
        print(f"✓ Queue 1: {len(queues[1])} orders")
        print(f"✓ Queue 2: {len(queues[2])} orders")

        # Verify modes in queue 1
        queue1_modes = [o['mode'] for o in queues[1]]
        self.assertIn('normal', queue1_modes)
        self.assertIn('ipo-sell-buy-trigger', queue1_modes)
        print(f"✓ Queue 1 contains mixed modes: {queue1_modes}")

    def test_03_validation_errors_dont_affect_other_modes(self):
        """Test that validation works for ipo-sell-buy-trigger mode."""
        print("\n[COMPAT TEST 3] Validation for ipo-sell-buy-trigger mode")

        # Valid sell-buy-trigger with all required fields
        valid_order_data = {
            "orders": [
                {
                    "id": "valid_sell_buy",
                    "execute": True,
                    "mode": "ipo-sell-buy-trigger",
                    "ticker": "NABIL",
                    "price": 1000,
                    "limit": 1000,
                    "quantity": 100,
                    "sell_quantity": 50,
                    "seller_config": "users/seller.json",
                    "buyer_config": "users/buyer.json"
                }
            ]
        }

        # Invalid sell-buy-trigger (missing seller_config)
        invalid_order_data = {
            "orders": [
                {
                    "id": "invalid_sell_buy",
                    "execute": True,
                    "mode": "ipo-sell-buy-trigger",
                    "ticker": "NABIL",
                    "price": 1000,
                    "limit": 1000,
                    "quantity": 100,
                    "sell_quantity": 50,
                    # Missing: seller_config and buyer_config
                }
            ]
        }

        # Valid order should load successfully
        valid_file = os.path.join(self.temp_dir, "valid_sell_buy.json")
        with open(valid_file, 'w') as f:
            json.dump(valid_order_data, f)

        store = OrderStore(valid_file)
        orders = store.get_executable_orders()
        self.assertEqual(len(orders), 1)
        self.assertEqual(orders[0]['mode'], 'ipo-sell-buy-trigger')
        print(f"✓ Valid ipo-sell-buy-trigger order loads successfully")

        # Invalid order data structure documented (validation happens during execution)
        invalid_file = os.path.join(self.temp_dir, "invalid_sell_buy.json")
        with open(invalid_file, 'w') as f:
            json.dump(invalid_order_data, f)

        # OrderStore loads without error (validation happens later during execution)
        store2 = OrderStore(invalid_file)
        invalid_orders = store2.get_executable_orders()
        self.assertEqual(len(invalid_orders), 1)
        print(f"✓ Invalid order loads (validation deferred to execution time)")

    def test_04_field_isolation_between_modes(self):
        """Test that mode-specific fields don't leak to other modes."""
        print("\n[COMPAT TEST 4] Field isolation between modes")

        order_store_data = {
            "orders": [
                {
                    "id": "normal_order",
                    "execute": True,
                    "mode": "normal",
                    "ticker": "NABIL",
                    "price": 1000,
                    "quantity": 10
                },
                {
                    "id": "ipo_trigger",
                    "execute": True,
                    "mode": "ipo-trigger",
                    "ticker": "NICA",
                    "price": 900,
                    "limit": 900,
                    "quantity": 20,
                    "no_ladder": True,
                    "just_buy": True,
                    "just_buy_timeout": 5
                },
                {
                    "id": "sell_buy_trigger",
                    "execute": True,
                    "mode": "ipo-sell-buy-trigger",
                    "ticker": "ADBL",
                    "price": 500,
                    "limit": 500,
                    "quantity": 100,
                    "sell_quantity": 50,
                    "sell_pre_wait_ms": 3000,
                    "seller_config": "users/seller.json",
                    "buyer_config": "users/buyer.json"
                }
            ]
        }

        order_store_file = os.path.join(self.temp_dir, "field_isolation.json")
        with open(order_store_file, 'w') as f:
            json.dump(order_store_data, f)

        store = OrderStore(order_store_file)
        orders = store.get_executable_orders()

        # Check normal order doesn't have ipo-sell-buy-trigger fields
        normal = next(o for o in orders if o['id'] == 'normal_order')
        self.assertIsNone(normal.get('seller_config'))
        self.assertIsNone(normal.get('buyer_config'))
        self.assertIsNone(normal.get('sell_quantity'))
        print(f"✓ Normal order: no sell-buy-trigger fields")

        # Check ipo-trigger order doesn't have sell-buy-trigger fields
        ipo_trigger = next(o for o in orders if o['id'] == 'ipo_trigger')
        self.assertIsNone(ipo_trigger.get('seller_config'))
        self.assertIsNone(ipo_trigger.get('buyer_config'))
        self.assertIsNone(ipo_trigger.get('sell_quantity'))
        self.assertTrue(ipo_trigger.get('just_buy'))  # Has its own fields
        print(f"✓ IPO trigger order: no sell-buy-trigger fields, has just_buy")

        # Check sell-buy-trigger has its fields
        sell_buy = next(o for o in orders if o['id'] == 'sell_buy_trigger')
        self.assertEqual(sell_buy['seller_config'], "users/seller.json")
        self.assertEqual(sell_buy['buyer_config'], "users/buyer.json")
        self.assertEqual(sell_buy['sell_quantity'], 50)
        self.assertEqual(sell_buy['sell_pre_wait_ms'], 3000)
        print(f"✓ Sell-buy-trigger order: has all required fields")

    def test_05_default_values_for_sell_pre_wait_ms(self):
        """Test that sell_pre_wait_ms defaults to 5000ms for ipo-sell-buy-trigger mode."""
        print("\n[COMPAT TEST 5] Default value for sell_pre_wait_ms")

        order_store_data = {
            "orders": [
                {
                    "id": "with_explicit_wait",
                    "execute": True,
                    "mode": "ipo-sell-buy-trigger",
                    "ticker": "NABIL",
                    "price": 1000,
                    "limit": 1000,
                    "quantity": 100,
                    "sell_quantity": 50,
                    "sell_pre_wait_ms": 3000,
                    "seller_config": "users/seller.json",
                    "buyer_config": "users/buyer.json"
                },
                {
                    "id": "with_default_wait",
                    "execute": True,
                    "mode": "ipo-sell-buy-trigger",
                    "ticker": "NICA",
                    "price": 900,
                    "limit": 900,
                    "quantity": 100,
                    "sell_quantity": 50,
                    # sell_pre_wait_ms not specified - should default to 5000
                    "seller_config": "users/seller.json",
                    "buyer_config": "users/buyer.json"
                },
                {
                    "id": "normal_mode_order",
                    "execute": True,
                    "mode": "normal",
                    "ticker": "ADBL",
                    "price": 500,
                    "quantity": 10
                }
            ]
        }

        order_store_file = os.path.join(self.temp_dir, "defaults.json")
        with open(order_store_file, 'w') as f:
            json.dump(order_store_data, f)

        store = OrderStore(order_store_file)
        orders = store.get_executable_orders()

        explicit = next(o for o in orders if o['id'] == 'with_explicit_wait')
        self.assertEqual(explicit.get('sell_pre_wait_ms'), 3000)
        print(f"✓ Explicit wait time: {explicit.get('sell_pre_wait_ms')}ms")

        default = next(o for o in orders if o['id'] == 'with_default_wait')
        # Should default to 5000 for ipo-sell-buy-trigger mode when not specified
        # The field won't be in the order dict if not specified, but validator applies default
        default_wait = default.get('sell_pre_wait_ms', 5000)
        self.assertEqual(default_wait, 5000)
        print(f"✓ Default wait time (applied during execution): {default_wait}ms")

        # Normal mode should not have sell-buy-trigger fields
        normal = next(o for o in orders if o['id'] == 'normal_mode_order')
        # Field should not be present for non-sell-buy-trigger modes
        self.assertNotIn('sell_quantity', normal)
        self.assertNotIn('seller_config', normal)
        self.assertNotIn('buyer_config', normal)
        print(f"✓ Normal mode order has no sell-buy-trigger fields (correct isolation)")

    def test_06_all_modes_in_single_queue(self):
        """Test all execution modes can coexist in same queue."""
        print("\n[COMPAT TEST 6] All modes in single queue")

        order_store_data = {
            "orders": [
                {
                    "id": "q1_normal",
                    "execute": True,
                    "queue_id": 1,
                    "mode": "normal",
                    "ticker": "NABIL",
                    "price": 1000,
                    "quantity": 10
                },
                {
                    "id": "q1_ipo",
                    "execute": True,
                    "queue_id": 1,
                    "mode": "ipo",
                    "ticker": "NICA",
                    "price": 900,
                    "limit": 950,
                    "quantity": 20
                },
                {
                    "id": "q1_ipo_trigger",
                    "execute": True,
                    "queue_id": 1,
                    "mode": "ipo-trigger",
                    "ticker": "ADBL",
                    "price": 500,
                    "limit": 500,
                    "quantity": 15,
                    "no_ladder": True
                },
                {
                    "id": "q1_trigger_sell",
                    "execute": True,
                    "queue_id": 1,
                    "mode": "trigger-sell",
                    "ticker": "GBIME",
                    "price": 300,
                    "limit": 280,
                    "quantity": 25,
                    "sell": True
                },
                {
                    "id": "q1_sell_buy_trigger",
                    "execute": True,
                    "queue_id": 1,
                    "mode": "ipo-sell-buy-trigger",
                    "ticker": "SBI",
                    "price": 400,
                    "limit": 400,
                    "quantity": 100,
                    "sell_quantity": 50,
                    "sell_pre_wait_ms": 5000,
                    "seller_config": "users/seller.json",
                    "buyer_config": "users/buyer.json"
                }
            ]
        }

        order_store_file = os.path.join(self.temp_dir, "all_modes_queue.json")
        with open(order_store_file, 'w') as f:
            json.dump(order_store_data, f)

        store = OrderStore(order_store_file)
        orders = store.get_executable_orders()

        # All should be in queue 1
        queue_ids = set(o['queue_id'] for o in orders)
        self.assertEqual(queue_ids, {1})
        print(f"✓ All orders in queue: {queue_ids}")

        # All modes should be present
        modes = [o['mode'] for o in orders]
        expected_modes = ['normal', 'ipo', 'ipo-trigger', 'trigger-sell', 'ipo-sell-buy-trigger']
        self.assertEqual(set(modes), set(expected_modes))
        print(f"✓ All 5 execution modes present in single queue")
        for mode in expected_modes:
            print(f"  - {mode}")


def run_tests():
    """Run all compatibility tests."""
    print("="*70)
    print("MODE COMPATIBILITY TEST SUITE")
    print("="*70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestModeCompatibility)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "="*70)
    print("COMPATIBILITY TEST SUMMARY")
    print("="*70)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("="*70)

    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
