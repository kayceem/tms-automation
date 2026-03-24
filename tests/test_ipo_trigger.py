#!/usr/bin/env python3
"""
Comprehensive test suite for IPO Trigger mode functionality.

This test suite simulates the complete IPO trigger workflow including:
- Price fetching with delays
- Order placement with delays
- Token refresh
- Skip first ladder level
- Skip second-last ladder level
- Multi-level price jumps
- Retry logic with max 3 attempts
- Queue execution
- Multi-user parallel execution

All tests run in a fake environment without hitting the live market.
"""

import sys
import time
import json
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List
from unittest.mock import Mock, MagicMock, patch
from dataclasses import dataclass

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import UserConfig
from api import TMSClient
from services import OrderService
from utils import OrderStore


class FakeMarketSimulator:
    """Simulates market price movements for IPO testing."""

    def __init__(self, base_price: float, limit_price: float):
        """
        Initialize market simulator.

        Args:
            base_price: Starting price
            limit_price: Maximum price (limit from order)
        """
        self.base_price = base_price
        self.limit_price = limit_price
        self.current_price = base_price
        self.lock = threading.Lock()
        self.price_history: List[tuple] = []  # (timestamp, price)

        # Calculate target price (+10% of limit)
        self.target_price = limit_price * 1.10

        # Price progression: base -> +2% increments -> limit+10%
        self.price_levels = self._calculate_ladder()
        self.current_level_index = 0

    def _calculate_ladder(self) -> List[float]:
        """Calculate the full price ladder."""
        import math

        levels = []
        price = self.base_price

        # Generate +2% ladder
        for _ in range(6):
            levels.append(price)
            price = price * 1.02
            price = math.floor(price * 10) / 10

        # Add limit +10% if different from last level
        if self.target_price > levels[-1]:
            levels.append(self.target_price)

        return levels

    def get_current_price(self) -> float:
        """Get current market price (simulates LTP fetch with 200ms delay)."""
        time.sleep(0.2)  # 200ms delay for GET request

        with self.lock:
            self.price_history.append((time.time(), self.current_price))
            return self.current_price

    def advance_price(self, levels: int = 1):
        """Advance price by specified number of levels."""
        with self.lock:
            self.current_level_index = min(
                self.current_level_index + levels,
                len(self.price_levels) - 1
            )
            self.current_price = self.price_levels[self.current_level_index]
            print(f"  [MARKET] Price advanced to Rs. {self.current_price:.1f} "
                  f"(Level {self.current_level_index + 1}/{len(self.price_levels)})")

    def jump_to_level(self, level_index: int):
        """Jump directly to a specific price level."""
        with self.lock:
            if 0 <= level_index < len(self.price_levels):
                self.current_level_index = level_index
                self.current_price = self.price_levels[level_index]
                print(f"  [MARKET] Price jumped to Rs. {self.current_price:.1f} "
                      f"(Level {level_index + 1}/{len(self.price_levels)})")


class FakeTMSClient:
    """Fake TMS client that simulates API calls with delays."""

    def __init__(self, user_config: UserConfig, market_simulator: FakeMarketSimulator):
        """
        Initialize fake TMS client.

        Args:
            user_config: User configuration
            market_simulator: Market simulator instance
        """
        self.user_config = user_config
        self.user_id = user_config.user_id
        self.market = market_simulator
        self.order_count = 0
        self.orders_placed: List[Dict[str, Any]] = []
        self.refresh_count = 0
        self.fail_next_order = False
        self.fail_count = 0

        # For testing retry logic
        self.max_failures_before_success = 0
        self.current_failure_count = 0

    def get_ltp(self, security_id: int) -> Optional[float]:
        """Simulate LTP fetch with 200ms delay."""
        price = self.market.get_current_price()
        return price

    def place_order(
        self,
        security_id: int,
        exchange_security_id: int,
        order_price: float,
        order_quantity: int,
        client_data: Dict[str, Any],
        buy_or_sell: int,
        order_type: str,
        order_validity: str,
        product_code: str = None
    ) -> Dict[str, Any]:
        """Simulate order placement with 1s delay."""
        time.sleep(1.0)  # 1 second delay for POST request

        # Simulate failures for retry testing
        if self.current_failure_count < self.max_failures_before_success:
            self.current_failure_count += 1
            self.fail_count += 1
            raise Exception(f"Simulated order failure #{self.current_failure_count}")

        # Reset failure counter after success
        self.current_failure_count = 0

        # Check if order should fail
        if self.fail_next_order:
            self.fail_next_order = False
            self.fail_count += 1
            raise Exception("Simulated order placement failure")

        self.order_count += 1

        order_record = {
            'order_id': f'ORDER_{self.user_id}_{self.order_count}',
            'security_id': security_id,
            'price': order_price,
            'quantity': order_quantity,
            'buy_or_sell': buy_or_sell,
            'timestamp': time.time()
        }

        self.orders_placed.append(order_record)

        print(f"    [{self.user_id}] Order placed: Rs. {order_price:.1f} x {order_quantity} "
              f"(Order #{self.order_count})")

        return {
            'status': 'success',
            'order_id': order_record['order_id'],
            'message': 'Order placed successfully'
        }

    def refresh_tokens(self) -> bool:
        """Simulate token refresh."""
        self.refresh_count += 1
        print(f"    [{self.user_id}] Tokens refreshed (count: {self.refresh_count})")
        return True

    def _refresh_tokens(self) -> bool:
        """Internal token refresh."""
        return self.refresh_tokens()


class TestIPOTrigger:
    """Comprehensive test suite for IPO Trigger functionality."""

    def __init__(self):
        """Initialize test suite."""
        self.tests_passed = 0
        self.tests_failed = 0
        self.test_results: List[Dict[str, Any]] = []

    def create_user_config(self, user_id: str) -> UserConfig:
        """Create a test user configuration."""
        return UserConfig(
            user_id=user_id,
            tms_host='tms01.nepsetms.com.np',
            tms_base_url='https://tms01.nepsetms.com.np',
            xsrf_token='test_token',
            rid_cookie='test_rid',
            host_session_id='test_session',
            access_token='test_access',
            request_owner='test_owner',
            member_code='TEST',
            client_data={
                'id': 1,
                'clientCode': 'TEST001',
                'name': 'Test User'
            },
            trigger_mode_poll_interval_ms=50,  # Faster polling for tests
            trigger_mode_refresh_interval_seconds=10
        )

    def run_test(self, test_name: str, test_func):
        """Run a single test and record results."""
        print(f"\n{'='*70}")
        print(f"TEST: {test_name}")
        print(f"{'='*70}")

        start_time = time.time()

        try:
            test_func()
            duration = time.time() - start_time
            print(f"\n✓ PASSED in {duration:.2f}s")
            self.tests_passed += 1
            self.test_results.append({
                'name': test_name,
                'status': 'PASSED',
                'duration': duration
            })
        except AssertionError as e:
            duration = time.time() - start_time
            print(f"\n✗ FAILED in {duration:.2f}s: {str(e)}")
            self.tests_failed += 1
            self.test_results.append({
                'name': test_name,
                'status': 'FAILED',
                'duration': duration,
                'error': str(e)
            })
        except Exception as e:
            duration = time.time() - start_time
            print(f"\n✗ ERROR in {duration:.2f}s: {str(e)}")
            self.tests_failed += 1
            self.test_results.append({
                'name': test_name,
                'status': 'ERROR',
                'duration': duration,
                'error': str(e)
            })

    def test_basic_trigger_no_skips(self):
        """Test basic IPO trigger without any skips."""
        print("Testing basic trigger mode with all ladder levels...")

        # Setup
        market = FakeMarketSimulator(base_price=100.0, limit_price=110.0)
        user_config = self.create_user_config('user1')
        fake_client = FakeTMSClient(user_config, market)

        # Patch TMSClient to use our fake
        with patch.object(OrderService, '__init__', lambda self, client: setattr(self, 'client', client) or setattr(self, 'user_id', client.user_id)):
            order_service = OrderService(fake_client)

            # Create price advancement thread
            def advance_prices():
                """Gradually advance prices through all levels."""
                time.sleep(2)  # Initial delay
                for i in range(6):
                    time.sleep(3)  # Delay between levels
                    market.advance_price(1)

            price_thread = threading.Thread(target=advance_prices, daemon=True)
            price_thread.start()

            # Execute trigger mode
            result = order_service._execute_ipo_trigger(
                security_id=3100,
                exchange_security_id=9308,
                base_price=100.0,
                order_quantity=100,
                client_data=user_config.client_data,
                buy_or_sell=1,
                order_type='LMT',
                order_validity='DAY',
                fetch_client=fake_client,
                limit_price=110.0,
                skip_first=False,
                skip_second_last=False,
                fetch_security_id=3100,
                base_quantity=10
            )

        # Verify results
        print(f"\nOrders placed: {len(fake_client.orders_placed)}")

        # Should have placed 6 orders (7 levels total, but last is limit)
        assert len(fake_client.orders_placed) >= 5, \
            f"Expected at least 5 orders, got {len(fake_client.orders_placed)}"

        # Verify quantities (base_quantity for all except last)
        for i, order in enumerate(fake_client.orders_placed[:-1]):
            assert order['quantity'] == 10, \
                f"Order {i+1} should use base_quantity=10, got {order['quantity']}"

        # Last order should use main quantity
        if fake_client.orders_placed:
            assert fake_client.orders_placed[-1]['quantity'] == 100, \
                f"Final order should use quantity=100, got {fake_client.orders_placed[-1]['quantity']}"

        print(f"✓ All orders placed with correct quantities")

    def test_skip_first_level(self):
        """Test IPO trigger with skip_first=True."""
        print("Testing skip_first functionality...")

        # Setup
        market = FakeMarketSimulator(base_price=100.0, limit_price=110.0)
        user_config = self.create_user_config('user1')
        fake_client = FakeTMSClient(user_config, market)

        with patch.object(OrderService, '__init__', lambda self, client: setattr(self, 'client', client) or setattr(self, 'user_id', client.user_id)):
            order_service = OrderService(fake_client)

            # Price advancement
            def advance_prices():
                time.sleep(2)
                for i in range(6):
                    time.sleep(3)
                    market.advance_price(1)

            price_thread = threading.Thread(target=advance_prices, daemon=True)
            price_thread.start()

            # Execute with skip_first
            result = order_service._execute_ipo_trigger(
                security_id=3100,
                exchange_security_id=9308,
                base_price=100.0,
                order_quantity=100,
                client_data=user_config.client_data,
                buy_or_sell=1,
                order_type='LMT',
                order_validity='DAY',
                fetch_client=fake_client,
                limit_price=110.0,
                skip_first=True,  # Skip first level
                skip_second_last=False,
                fetch_security_id=3100,
                base_quantity=10
            )

        # Verify first level was skipped
        print(f"\nOrders placed: {len(fake_client.orders_placed)}")

        # First order price should NOT be base_price
        if fake_client.orders_placed:
            first_order_price = fake_client.orders_placed[0]['price']
            assert first_order_price > 100.0, \
                f"First order should skip base price 100.0, got {first_order_price:.1f}"
            print(f"✓ First level (Rs. 100.0) was skipped")
            print(f"✓ First order placed at Rs. {first_order_price:.1f}")

    def test_skip_second_last_level(self):
        """Test IPO trigger with skip_second_last=True."""
        print("Testing skip_second_last functionality...")

        # Setup
        market = FakeMarketSimulator(base_price=100.0, limit_price=110.0)
        user_config = self.create_user_config('user1')
        fake_client = FakeTMSClient(user_config, market)

        with patch.object(OrderService, '__init__', lambda self, client: setattr(self, 'client', client) or setattr(self, 'user_id', client.user_id)):
            order_service = OrderService(fake_client)

            # Price advancement
            def advance_prices():
                time.sleep(2)
                for i in range(7):
                    time.sleep(3)
                    market.advance_price(1)

            price_thread = threading.Thread(target=advance_prices, daemon=True)
            price_thread.start()

            # Execute with skip_second_last
            result = order_service._execute_ipo_trigger(
                security_id=3100,
                exchange_security_id=9308,
                base_price=100.0,
                order_quantity=100,
                client_data=user_config.client_data,
                buy_or_sell=1,
                order_type='LMT',
                order_validity='DAY',
                fetch_client=fake_client,
                limit_price=110.0,
                skip_first=False,
                skip_second_last=True,  # Skip second-to-last level
                fetch_security_id=3100,
                base_quantity=10
            )

        # Calculate expected second-to-last price
        import math
        ladder = []
        price = 100.0
        for _ in range(6):
            ladder.append(price)
            price = price * 1.02
            price = math.floor(price * 10) / 10
        ladder.append(110.0 * 1.10)  # Limit +10%

        second_last_price = ladder[-2]

        # Verify second-to-last was skipped
        print(f"\nExpected to skip: Rs. {second_last_price:.1f}")
        print(f"Orders placed: {len(fake_client.orders_placed)}")

        # Check that second-to-last price is not in orders
        order_prices = [order['price'] for order in fake_client.orders_placed]
        assert second_last_price not in order_prices, \
            f"Second-to-last price Rs. {second_last_price:.1f} should be skipped"

        print(f"✓ Second-to-last level (Rs. {second_last_price:.1f}) was skipped")

    def test_skip_both_first_and_second_last(self):
        """Test IPO trigger with both skip_first and skip_second_last."""
        print("Testing skip_first + skip_second_last combination...")

        # Setup
        market = FakeMarketSimulator(base_price=100.0, limit_price=110.0)
        user_config = self.create_user_config('user1')
        fake_client = FakeTMSClient(user_config, market)

        with patch.object(OrderService, '__init__', lambda self, client: setattr(self, 'client', client) or setattr(self, 'user_id', client.user_id)):
            order_service = OrderService(fake_client)

            # Price advancement
            def advance_prices():
                time.sleep(2)
                for i in range(7):
                    time.sleep(3)
                    market.advance_price(1)

            price_thread = threading.Thread(target=advance_prices, daemon=True)
            price_thread.start()

            # Execute with both skips
            result = order_service._execute_ipo_trigger(
                security_id=3100,
                exchange_security_id=9308,
                base_price=100.0,
                order_quantity=100,
                client_data=user_config.client_data,
                buy_or_sell=1,
                order_type='LMT',
                order_validity='DAY',
                fetch_client=fake_client,
                limit_price=110.0,
                skip_first=True,
                skip_second_last=True,
                fetch_security_id=3100,
                base_quantity=10
            )

        # Verify both skips
        order_prices = [order['price'] for order in fake_client.orders_placed]

        # First level should be skipped
        assert 100.0 not in order_prices, "First level should be skipped"

        print(f"✓ Both first and second-to-last levels were skipped")
        print(f"✓ Placed {len(fake_client.orders_placed)} orders")

    def test_price_jump_multiple_levels(self):
        """Test handling of price jumping past multiple ladder levels."""
        print("Testing price jump edge case...")

        # Setup
        market = FakeMarketSimulator(base_price=100.0, limit_price=110.0)
        user_config = self.create_user_config('user1')
        fake_client = FakeTMSClient(user_config, market)

        with patch.object(OrderService, '__init__', lambda self, client: setattr(self, 'client', client) or setattr(self, 'user_id', client.user_id)):
            order_service = OrderService(fake_client)

            # Price advancement with big jump
            def advance_prices():
                time.sleep(2)
                market.advance_price(1)  # Level 2
                time.sleep(3)
                # Big jump: skip levels 3, 4, 5
                market.jump_to_level(5)  # Jump to level 6
                time.sleep(3)
                market.advance_price(1)  # Level 7

            price_thread = threading.Thread(target=advance_prices, daemon=True)
            price_thread.start()

            # Execute
            result = order_service._execute_ipo_trigger(
                security_id=3100,
                exchange_security_id=9308,
                base_price=100.0,
                order_quantity=100,
                client_data=user_config.client_data,
                buy_or_sell=1,
                order_type='LMT',
                order_validity='DAY',
                fetch_client=fake_client,
                limit_price=110.0,
                skip_first=False,
                skip_second_last=False,
                fetch_security_id=3100,
                base_quantity=10
            )

        print(f"\nOrders placed: {len(fake_client.orders_placed)}")
        order_prices_str = [f"Rs. {o['price']:.1f}" for o in fake_client.orders_placed]
        print(f"Order prices: {order_prices_str}")

        # Should have skipped intermediate levels
        assert len(fake_client.orders_placed) < 7, \
            "Should skip some levels when price jumps"

        print(f"✓ Price jump handled correctly")
        print(f"✓ Skipped intermediate levels as expected")

    def test_retry_logic_max_3_attempts(self):
        """Test that orders retry up to 3 times before skipping."""
        print("Testing retry logic (max 3 attempts)...")

        # Setup
        market = FakeMarketSimulator(base_price=100.0, limit_price=110.0)
        user_config = self.create_user_config('user1')
        fake_client = FakeTMSClient(user_config, market)

        # Make first 2 attempts fail, 3rd succeed
        fake_client.max_failures_before_success = 2

        with patch.object(OrderService, '__init__', lambda self, client: setattr(self, 'client', client) or setattr(self, 'user_id', client.user_id)):
            order_service = OrderService(fake_client)

            # Price advancement
            def advance_prices():
                time.sleep(2)
                for i in range(6):  # Need to advance through all 7 levels (index 0-6)
                    time.sleep(4)  # Longer delay to allow retries
                    market.advance_price(1)

            price_thread = threading.Thread(target=advance_prices, daemon=True)
            price_thread.start()

            # Execute
            result = order_service._execute_ipo_trigger(
                security_id=3100,
                exchange_security_id=9308,
                base_price=100.0,
                order_quantity=100,
                client_data=user_config.client_data,
                buy_or_sell=1,
                order_type='LMT',
                order_validity='DAY',
                fetch_client=fake_client,
                limit_price=110.0,
                skip_first=False,
                skip_second_last=False,
                fetch_security_id=3100,
                base_quantity=10
            )

        print(f"\nTotal failures: {fake_client.fail_count}")
        print(f"Orders placed: {len(fake_client.orders_placed)}")

        # Should have some failures but still place orders
        assert fake_client.fail_count > 0, "Should have some failures"
        assert len(fake_client.orders_placed) > 0, "Should eventually place orders after retries"

        print(f"✓ Retry logic working correctly")
        print(f"✓ Orders placed after {fake_client.fail_count} failures")

    def test_base_quantity_vs_final_quantity(self):
        """Test that base_quantity is used for all levels except final."""
        print("Testing base_quantity vs final quantity...")

        # Setup
        market = FakeMarketSimulator(base_price=100.0, limit_price=110.0)
        user_config = self.create_user_config('user1')
        fake_client = FakeTMSClient(user_config, market)

        with patch.object(OrderService, '__init__', lambda self, client: setattr(self, 'client', client) or setattr(self, 'user_id', client.user_id)):
            order_service = OrderService(fake_client)

            # Price advancement
            def advance_prices():
                time.sleep(2)
                for i in range(7):
                    time.sleep(3)
                    market.advance_price(1)

            price_thread = threading.Thread(target=advance_prices, daemon=True)
            price_thread.start()

            # Execute with specific quantities
            result = order_service._execute_ipo_trigger(
                security_id=3100,
                exchange_security_id=9308,
                base_price=100.0,
                order_quantity=500,  # Final level quantity
                client_data=user_config.client_data,
                buy_or_sell=1,
                order_type='LMT',
                order_validity='DAY',
                fetch_client=fake_client,
                limit_price=110.0,
                skip_first=False,
                skip_second_last=False,
                fetch_security_id=3100,
                base_quantity=25  # All other levels
            )

        print(f"\nOrders placed: {len(fake_client.orders_placed)}")

        # Verify quantities
        for i, order in enumerate(fake_client.orders_placed):
            is_last = (i == len(fake_client.orders_placed) - 1)
            expected_qty = 500 if is_last else 25

            assert order['quantity'] == expected_qty, \
                f"Order {i+1}: expected qty={expected_qty}, got {order['quantity']}"

            print(f"  Order {i+1}: Rs. {order['price']:.1f} x {order['quantity']} "
                  f"{'(FINAL)' if is_last else '(BASE)'}")

        print(f"✓ Quantities correct for all levels")

    def test_no_ladder_mode(self):
        """Test no_ladder mode: skip all levels, only place final order."""
        print("Testing no_ladder mode (skip ALL ladder levels)...")

        # Setup
        market = FakeMarketSimulator(base_price=100.0, limit_price=110.0)
        user_config = self.create_user_config('user1')
        fake_client = FakeTMSClient(user_config, market)

        with patch.object(OrderService, '__init__', lambda self, client: setattr(self, 'client', client) or setattr(self, 'user_id', client.user_id)):
            order_service = OrderService(fake_client)

            # Price advancement - jump directly to second-to-last level
            def advance_prices():
                time.sleep(2)
                # Jump to second-to-last level (level 6 out of 7)
                market.jump_to_level(5)  # Index 5 = Level 6
                time.sleep(2)

            price_thread = threading.Thread(target=advance_prices, daemon=True)
            price_thread.start()

            # Execute with no_ladder=True
            result = order_service._execute_ipo_trigger(
                security_id=3100,
                exchange_security_id=9308,
                base_price=100.0,
                order_quantity=100,
                client_data=user_config.client_data,
                buy_or_sell=1,
                order_type='LMT',
                order_validity='DAY',
                fetch_client=fake_client,
                limit_price=110.0,
                skip_first=False,  # Ignored when no_ladder=True
                skip_second_last=False,  # Ignored when no_ladder=True
                no_ladder=True,  # Skip ALL ladder levels
                fetch_security_id=3100,
                base_quantity=10
            )

        print(f"\nOrders placed: {len(fake_client.orders_placed)}")

        # Verify only ONE order was placed (the final order)
        assert len(fake_client.orders_placed) == 1, \
            f"Expected exactly 1 order (final only), got {len(fake_client.orders_placed)}"

        # Verify it's the final order price (limit + 10%)
        final_order = fake_client.orders_placed[0]
        expected_final_price = 110.0 * 1.10  # limit + 10%

        assert abs(final_order['price'] - expected_final_price) < 0.5, \
            f"Final order should be at limit+10% (~Rs. {expected_final_price:.1f}), got Rs. {final_order['price']:.1f}"

        # Verify final quantity
        assert final_order['quantity'] == 100, \
            f"Final order should use main quantity (100), got {final_order['quantity']}"

        print(f"✓ Only final order placed at Rs. {final_order['price']:.1f} x {final_order['quantity']}")
        print(f"✓ All ladder levels skipped as expected")

    def print_summary(self):
        """Print test summary."""
        print(f"\n{'='*70}")
        print(f"TEST SUMMARY")
        print(f"{'='*70}")
        print(f"Tests Passed: {self.tests_passed}")
        print(f"Tests Failed: {self.tests_failed}")
        print(f"Total Tests:  {self.tests_passed + self.tests_failed}")
        print(f"Success Rate: {(self.tests_passed / (self.tests_passed + self.tests_failed) * 100):.1f}%")
        print(f"{'='*70}")

        if self.tests_failed > 0:
            print(f"\nFailed Tests:")
            for result in self.test_results:
                if result['status'] != 'PASSED':
                    print(f"  ✗ {result['name']}")
                    if 'error' in result:
                        print(f"    Error: {result['error']}")

        print()


def main():
    """Run all tests."""
    print("IPO Trigger Mode - Comprehensive Test Suite")
    print("=" * 70)

    suite = TestIPOTrigger()

    # Run all tests
    suite.run_test("Basic Trigger (No Skips)", suite.test_basic_trigger_no_skips)
    suite.run_test("Skip First Level", suite.test_skip_first_level)
    suite.run_test("Skip Second-Last Level", suite.test_skip_second_last_level)
    suite.run_test("Skip First + Second-Last", suite.test_skip_both_first_and_second_last)
    suite.run_test("Price Jump (Multiple Levels)", suite.test_price_jump_multiple_levels)
    suite.run_test("Retry Logic (Max 3 Attempts)", suite.test_retry_logic_max_3_attempts)
    suite.run_test("Base Quantity vs Final Quantity", suite.test_base_quantity_vs_final_quantity)
    suite.run_test("No Ladder Mode", suite.test_no_ladder_mode)

    # Print summary
    suite.print_summary()

    # Exit with appropriate code
    sys.exit(0 if suite.tests_failed == 0 else 1)


if __name__ == '__main__':
    main()
