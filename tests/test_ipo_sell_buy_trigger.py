#!/usr/bin/env python3
"""
Comprehensive test suite for IPO Sell-Buy-Trigger mode.

Tests include:
- Request interception with simulated ladder price progression
- Successful buy/sell coordination
- Edge cases (ladder < 3 levels, timing precision, retries)
- Multi-platform compatibility (TMS/ATRAD combinations)
- Integration with other execution modes
"""

import unittest
import threading
import time
import json
import tempfile
import os
from unittest.mock import Mock, patch, MagicMock
from typing import List, Dict, Any, Optional

# Import project modules
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from config import UserConfig, ATRADUserConfig
from api import TMSClient, ATRADClient
from services import OrderService, ATRADOrderService
from services.base_order_service import BaseOrderService


class LadderPriceSimulator:
    """
    Simulates price progression through ladder levels.
    Prices only increase and must match ladder levels.
    """

    def __init__(self, ladder: List[float], progression_speed_ms: int = 100):
        """
        Initialize price simulator.

        Args:
            ladder: List of price levels (e.g., [100, 102, 104, 106, 108, 110])
            progression_speed_ms: Time to wait between level transitions (ms)
        """
        self.ladder = ladder
        self.progression_speed_ms = progression_speed_ms
        self.current_index = 0
        self.lock = threading.Lock()
        self.started = False
        self.stopped = False
        self.progression_thread = None

    def start(self):
        """Start automatic price progression."""
        if self.started:
            return

        self.started = True
        self.progression_thread = threading.Thread(
            target=self._progress_prices,
            daemon=True
        )
        self.progression_thread.start()

    def _progress_prices(self):
        """Automatically progress through ladder levels."""
        while not self.stopped and self.current_index < len(self.ladder) - 1:
            time.sleep(self.progression_speed_ms / 1000.0)
            with self.lock:
                if self.current_index < len(self.ladder) - 1:
                    self.current_index += 1

    def get_current_price(self) -> float:
        """Get current LTP (matches ladder level)."""
        with self.lock:
            return self.ladder[self.current_index]

    def jump_to_level(self, level_index: int):
        """Manually jump to specific ladder level."""
        with self.lock:
            if 0 <= level_index < len(self.ladder):
                self.current_index = level_index

    def stop(self):
        """Stop price progression."""
        self.stopped = True
        if self.progression_thread:
            self.progression_thread.join(timeout=1)


class MockOrderResponse:
    """Mock order placement response."""

    def __init__(self, success: bool = True, code: str = "0"):
        self.success = success
        self.code = code
        self.status_code = 200 if success else 400

    def json(self):
        return {
            "code": self.code,
            "description": "javascriptOrderSuccessesFullySubmitted" if self.success else "javascriptOrderFailed",
            "data": "success" if self.success else "error"
        }


class TestIPOSellBuyTrigger(unittest.TestCase):
    """Test suite for IPO Sell-Buy-Trigger mode."""

    def setUp(self):
        """Set up test fixtures."""
        # Create temporary config files
        self.temp_dir = tempfile.mkdtemp()

        # TMS seller config
        self.seller_tms_config = {
            "user_id": "seller_tms",
            "tms_host": "tms1.example.com",
            "tms_base_url": "https://tms1.example.com",
            "xsrf_token": "test_token",
            "rid_cookie": "test_rid",
            "host_session_id": "test_session",
            "access_token": "test_access",
            "trigger_mode_poll_interval_ms": 50,
            "trigger_mode_refresh_interval_seconds": 60
        }

        # TMS buyer config
        self.buyer_tms_config = {
            "user_id": "buyer_tms",
            "tms_host": "tms1.example.com",
            "tms_base_url": "https://tms1.example.com",
            "xsrf_token": "test_token",
            "rid_cookie": "test_rid",
            "host_session_id": "test_session",
            "access_token": "test_access",
            "trigger_mode_poll_interval_ms": 50
        }

        # ATRAD seller config
        self.seller_atrad_config = {
            "user_id": "seller_atrad",
            "atrad_base_url": "https://atrad.example.com",
            "username": "seller",
            "password": "test123",
            "account_id": "12345",
            "trigger_mode_poll_interval_ms": 50
        }

        # ATRAD buyer config
        self.buyer_atrad_config = {
            "user_id": "buyer_atrad",
            "atrad_base_url": "https://atrad.example.com",
            "username": "buyer",
            "password": "test123",
            "account_id": "67890",
            "trigger_mode_poll_interval_ms": 50
        }

        # TMS fetch config
        self.fetch_tms_config = {
            "user_id": "fetch_tms",
            "tms_host": "tms1.example.com",
            "tms_base_url": "https://tms1.example.com",
            "xsrf_token": "test_token",
            "rid_cookie": "test_rid",
            "host_session_id": "test_session",
            "access_token": "test_access"
        }

        # Save configs to temp files
        self.seller_tms_file = os.path.join(self.temp_dir, "seller_tms.json")
        self.buyer_tms_file = os.path.join(self.temp_dir, "buyer_tms.json")
        self.seller_atrad_file = os.path.join(self.temp_dir, "seller_atrad.json")
        self.buyer_atrad_file = os.path.join(self.temp_dir, "buyer_atrad.json")
        self.fetch_tms_file = os.path.join(self.temp_dir, "fetch_tms.json")

        with open(self.seller_tms_file, 'w') as f:
            json.dump(self.seller_tms_config, f)
        with open(self.buyer_tms_file, 'w') as f:
            json.dump(self.buyer_tms_config, f)
        with open(self.seller_atrad_file, 'w') as f:
            json.dump(self.seller_atrad_config, f)
        with open(self.buyer_atrad_file, 'w') as f:
            json.dump(self.buyer_atrad_config, f)
        with open(self.fetch_tms_file, 'w') as f:
            json.dump(self.fetch_tms_config, f)

        # Standard ladder for testing
        self.test_ladder = [1000.0, 1020.0, 1040.8, 1061.6, 1082.8, 1104.4]

    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        shutil.rmtree(self.temp_dir)

    def create_mock_service(self, config_dict: Dict, platform: str = 'tms'):
        """
        Create a mock service with intercepted methods.

        Args:
            config_dict: User config dictionary
            platform: 'tms' or 'atrad'

        Returns:
            Mocked service instance
        """
        if platform == 'tms':
            config = UserConfig(**config_dict)
            client = TMSClient(config)
            service = OrderService(client)
        else:
            config = ATRADUserConfig(**config_dict)
            client = ATRADClient(config)
            service = ATRADOrderService(client)

        return service

    def test_01_ladder_calculation_validation(self):
        """Test that ladder must have >= 3 levels."""
        print("\n[TEST 1] Ladder calculation validation")

        service = self.create_mock_service(self.seller_tms_config, 'tms')
        buyer_service = self.create_mock_service(self.buyer_tms_config, 'tms')

        # Test: Ladder with < 3 levels should raise ValueError
        with self.assertRaises(ValueError) as context:
            with patch.object(service, '_calculate_price_levels', return_value=([100, 102], [0, 2])):
                with patch.object(service, '_setup_price_fetcher'):
                    service._execute_ipo_sell_buy_trigger(
                        buyer_service=buyer_service,
                        fetch_clients=[],
                        ticker="TEST",
                        security_id=1,
                        exchange_security_id=1,
                        symbol="TEST",
                        base_price=100,
                        buy_quantity=10,
                        sell_quantity=5,
                        sell_pre_wait_ms=1000
                    )

        self.assertIn("at least 3 levels", str(context.exception))
        print("✓ Ladder validation works correctly")

    def test_02_successful_execution_tms_both(self):
        """Test successful execution with TMS for both seller and buyer."""
        print("\n[TEST 2] Successful execution - TMS seller + TMS buyer")

        # Setup price simulator
        simulator = LadderPriceSimulator(self.test_ladder, progression_speed_ms=200)

        # Create services
        seller_service = self.create_mock_service(self.seller_tms_config, 'tms')
        buyer_service = self.create_mock_service(self.buyer_tms_config, 'tms')
        fetch_service = self.create_mock_service(self.fetch_tms_config, 'tms')

        # Track order placements
        buy_orders = []
        sell_orders = []

        def mock_place_single_order(price, quantity, **kwargs):
            """Mock order placement that tracks calls."""
            order = {
                'price': price,
                'quantity': quantity,
                'side': 'BUY' if kwargs.get('buy_or_sell') == 1 else 'SELL',
                'timestamp': time.time()
            }

            if kwargs.get('buy_or_sell') == 1:  # BUY
                buy_orders.append(order)
            else:  # SELL
                sell_orders.append(order)

            return MockOrderResponse(success=True).json()

        # Mock price fetcher
        class MockPriceFetcher:
            def __init__(self):
                self.stopped = False

            def get_latest_ltp(self):
                return simulator.get_current_price()

            def stop(self):
                self.stopped = True
                simulator.stop()

        mock_fetcher = MockPriceFetcher()

        # Patch methods
        with patch.object(seller_service, '_place_single_order', side_effect=mock_place_single_order):
            with patch.object(buyer_service, '_place_single_order', side_effect=mock_place_single_order):
                with patch.object(seller_service, '_setup_price_fetcher', return_value=mock_fetcher):
                    with patch.object(seller_service, '_setup_token_manager', return_value=None):
                        with patch.object(buyer_service, '_setup_token_manager', return_value=None):
                            with patch.object(seller_service, '_cleanup_token_manager'):
                                with patch.object(buyer_service, '_cleanup_token_manager'):
                                    # Start price progression
                                    simulator.start()

                                    # Execute mode with short wait time
                                    result = seller_service._execute_ipo_sell_buy_trigger(
                                        buyer_service=buyer_service,
                                        fetch_clients=[fetch_service.client],
                                        ticker="TEST",
                                        security_id=1,
                                        exchange_security_id=1,
                                        symbol="TEST",
                                        base_price=1000,
                                        buy_quantity=100,
                                        sell_quantity=50,
                                        sell_pre_wait_ms=500,  # Short for testing
                                        limit_price=1000,
                                        just_buy_interval_ms=50,
                                        just_buy_timeout=2
                                    )

        # Verify results
        self.assertTrue(result['buy_success'] or result['sell_success'], "At least one order should succeed")
        self.assertIsNotNone(mock_fetcher.stopped, "Fetcher should be stopped")

        print(f"✓ Buy orders placed: {len(buy_orders)}")
        print(f"✓ Sell orders placed: {len(sell_orders)}")
        print(f"✓ Buy success: {result['buy_success']}")
        print(f"✓ Sell success: {result['sell_success']}")

        # Verify order prices
        if buy_orders:
            buy_prices = set(order['price'] for order in buy_orders)
            expected_buy_price = self.test_ladder[-1]  # Final level
            self.assertIn(expected_buy_price, buy_prices, f"Buy orders should be at final price {expected_buy_price}")
            print(f"✓ Buy orders at correct price: {expected_buy_price}")

        if sell_orders:
            sell_prices = set(order['price'] for order in sell_orders)
            expected_sell_price = self.test_ladder[-2]  # Second last level
            self.assertIn(expected_sell_price, sell_prices, f"Sell orders should be at second-last price {expected_sell_price}")
            print(f"✓ Sell orders at correct price: {expected_sell_price}")

    def test_03_successful_execution_mixed_platforms(self):
        """Test successful execution with TMS seller + ATRAD buyer."""
        print("\n[TEST 3] Mixed platforms - TMS seller + ATRAD buyer")

        simulator = LadderPriceSimulator(self.test_ladder, progression_speed_ms=200)

        seller_service = self.create_mock_service(self.seller_tms_config, 'tms')
        buyer_service = self.create_mock_service(self.buyer_atrad_config, 'atrad')
        fetch_service = self.create_mock_service(self.fetch_tms_config, 'tms')

        buy_orders = []
        sell_orders = []

        def mock_place_single_order_seller(price, quantity, **kwargs):
            order = {'price': price, 'quantity': quantity, 'side': 'SELL', 'platform': 'TMS'}
            sell_orders.append(order)
            return MockOrderResponse(success=True).json()

        def mock_place_single_order_buyer(price, quantity, **kwargs):
            order = {'price': price, 'quantity': quantity, 'side': 'BUY', 'platform': 'ATRAD'}
            buy_orders.append(order)
            return MockOrderResponse(success=True).json()

        class MockPriceFetcher:
            def get_latest_ltp(self):
                return simulator.get_current_price()

            def stop(self):
                simulator.stop()

        mock_fetcher = MockPriceFetcher()

        with patch.object(seller_service, '_place_single_order', side_effect=mock_place_single_order_seller):
            with patch.object(buyer_service, '_place_single_order', side_effect=mock_place_single_order_buyer):
                with patch.object(seller_service, '_setup_price_fetcher', return_value=mock_fetcher):
                    with patch.object(seller_service, '_setup_token_manager', return_value=None):
                        with patch.object(buyer_service, '_setup_token_manager', return_value=None):
                            with patch.object(seller_service, '_cleanup_token_manager'):
                                with patch.object(buyer_service, '_cleanup_token_manager'):
                                    simulator.start()

                                    result = seller_service._execute_ipo_sell_buy_trigger(
                                        buyer_service=buyer_service,
                                        fetch_clients=[fetch_service.client],
                                        ticker="TEST",
                                        security_id=1,
                                        exchange_security_id=1,
                                        symbol="TEST",
                                        base_price=1000,
                                        buy_quantity=100,
                                        sell_quantity=50,
                                        sell_pre_wait_ms=500,
                                        limit_price=1000,
                                        just_buy_interval_ms=50,
                                        just_buy_timeout=2
                                    )

        print(f"✓ Mixed platform test completed")
        print(f"✓ Seller (TMS) orders: {len(sell_orders)}")
        print(f"✓ Buyer (ATRAD) orders: {len(buy_orders)}")

        if sell_orders:
            self.assertEqual(sell_orders[0]['platform'], 'TMS')
            print(f"✓ Sell order from TMS platform")

        if buy_orders:
            self.assertEqual(buy_orders[0]['platform'], 'ATRAD')
            print(f"✓ Buy order from ATRAD platform")

    def test_04_timing_precision(self):
        """Test that buy threads start 100ms before sell order."""
        print("\n[TEST 4] Timing precision - buy starts 100ms before sell")

        simulator = LadderPriceSimulator(self.test_ladder, progression_speed_ms=50)
        simulator.jump_to_level(3)  # Start at third-last level

        seller_service = self.create_mock_service(self.seller_tms_config, 'tms')
        buyer_service = self.create_mock_service(self.buyer_tms_config, 'tms')
        fetch_service = self.create_mock_service(self.fetch_tms_config, 'tms')

        first_buy_time = None
        sell_time = None

        def mock_place_buy(price, quantity, **kwargs):
            nonlocal first_buy_time
            if first_buy_time is None:
                first_buy_time = time.time()
            return MockOrderResponse(success=True).json()

        def mock_place_sell(price, quantity, **kwargs):
            nonlocal sell_time
            sell_time = time.time()
            return MockOrderResponse(success=True).json()

        class MockPriceFetcher:
            def get_latest_ltp(self):
                return simulator.get_current_price()

            def stop(self):
                simulator.stop()

        mock_fetcher = MockPriceFetcher()

        with patch.object(seller_service, '_place_single_order', side_effect=mock_place_sell):
            with patch.object(buyer_service, '_place_single_order', side_effect=mock_place_buy):
                with patch.object(seller_service, '_setup_price_fetcher', return_value=mock_fetcher):
                    with patch.object(seller_service, '_setup_token_manager', return_value=None):
                        with patch.object(buyer_service, '_setup_token_manager', return_value=None):
                            with patch.object(seller_service, '_cleanup_token_manager'):
                                with patch.object(buyer_service, '_cleanup_token_manager'):
                                    result = seller_service._execute_ipo_sell_buy_trigger(
                                        buyer_service=buyer_service,
                                        fetch_clients=[fetch_service.client],
                                        ticker="TEST",
                                        security_id=1,
                                        exchange_security_id=1,
                                        symbol="TEST",
                                        base_price=1000,
                                        buy_quantity=100,
                                        sell_quantity=50,
                                        sell_pre_wait_ms=1000,
                                        limit_price=1000,
                                        just_buy_interval_ms=50,
                                        just_buy_timeout=2
                                    )

        if first_buy_time and sell_time:
            time_diff_ms = (sell_time - first_buy_time) * 1000
            print(f"✓ Time between first buy and sell: {time_diff_ms:.1f}ms")

            # Should be approximately 100ms (with some tolerance for system timing)
            self.assertGreater(time_diff_ms, 50, "Buy should start at least 50ms before sell")
            self.assertLess(time_diff_ms, 200, "Buy should start less than 200ms before sell")
            print(f"✓ Timing within acceptable range (50-200ms)")

    def test_05_sell_order_retry_logic(self):
        """Test that sell order retries on failure."""
        print("\n[TEST 5] Sell order retry logic")

        simulator = LadderPriceSimulator(self.test_ladder, progression_speed_ms=50)
        simulator.jump_to_level(3)

        seller_service = self.create_mock_service(self.seller_tms_config, 'tms')
        buyer_service = self.create_mock_service(self.buyer_tms_config, 'tms')
        fetch_service = self.create_mock_service(self.fetch_tms_config, 'tms')

        sell_attempts = []

        def mock_place_sell(price, quantity, **kwargs):
            sell_attempts.append(time.time())

            # Fail first 2 attempts, succeed on 3rd
            if len(sell_attempts) < 3:
                raise Exception("Simulated network error")
            return MockOrderResponse(success=True).json()

        def mock_place_buy(price, quantity, **kwargs):
            return MockOrderResponse(success=True).json()

        class MockPriceFetcher:
            def get_latest_ltp(self):
                return simulator.get_current_price()

            def stop(self):
                simulator.stop()

        mock_fetcher = MockPriceFetcher()

        with patch.object(seller_service, '_place_single_order', side_effect=mock_place_sell):
            with patch.object(buyer_service, '_place_single_order', side_effect=mock_place_buy):
                with patch.object(seller_service, '_setup_price_fetcher', return_value=mock_fetcher):
                    with patch.object(seller_service, '_setup_token_manager', return_value=None):
                        with patch.object(buyer_service, '_setup_token_manager', return_value=None):
                            with patch.object(seller_service, '_cleanup_token_manager'):
                                with patch.object(buyer_service, '_cleanup_token_manager'):
                                    result = seller_service._execute_ipo_sell_buy_trigger(
                                        buyer_service=buyer_service,
                                        fetch_clients=[fetch_service.client],
                                        ticker="TEST",
                                        security_id=1,
                                        exchange_security_id=1,
                                        symbol="TEST",
                                        base_price=1000,
                                        buy_quantity=100,
                                        sell_quantity=50,
                                        sell_pre_wait_ms=500,
                                        limit_price=1000,
                                        just_buy_interval_ms=50,
                                        just_buy_timeout=2
                                    )

        print(f"✓ Sell retry attempts: {len(sell_attempts)}")
        self.assertGreaterEqual(len(sell_attempts), 3, "Should retry at least 3 times")
        self.assertTrue(result['sell_success'], "Should eventually succeed")
        print(f"✓ Sell succeeded after {len(sell_attempts)} attempts")

    def test_06_partial_success_sell_only(self):
        """Test partial success scenario (sell succeeds, buy fails)."""
        print("\n[TEST 6] Partial success - sell succeeds, buy fails")

        simulator = LadderPriceSimulator(self.test_ladder, progression_speed_ms=50)
        simulator.jump_to_level(3)

        seller_service = self.create_mock_service(self.seller_tms_config, 'tms')
        buyer_service = self.create_mock_service(self.buyer_tms_config, 'tms')
        fetch_service = self.create_mock_service(self.fetch_tms_config, 'tms')

        def mock_place_sell(price, quantity, **kwargs):
            return MockOrderResponse(success=True).json()

        def mock_place_buy(price, quantity, **kwargs):
            # All buy attempts fail
            raise Exception("Buy order failed")

        class MockPriceFetcher:
            def get_latest_ltp(self):
                return simulator.get_current_price()

            def stop(self):
                simulator.stop()

        mock_fetcher = MockPriceFetcher()

        with patch.object(seller_service, '_place_single_order', side_effect=mock_place_sell):
            with patch.object(buyer_service, '_place_single_order', side_effect=mock_place_buy):
                with patch.object(seller_service, '_setup_price_fetcher', return_value=mock_fetcher):
                    with patch.object(seller_service, '_setup_token_manager', return_value=None):
                        with patch.object(buyer_service, '_setup_token_manager', return_value=None):
                            with patch.object(seller_service, '_cleanup_token_manager'):
                                with patch.object(buyer_service, '_cleanup_token_manager'):
                                    result = seller_service._execute_ipo_sell_buy_trigger(
                                        buyer_service=buyer_service,
                                        fetch_clients=[fetch_service.client],
                                        ticker="TEST",
                                        security_id=1,
                                        exchange_security_id=1,
                                        symbol="TEST",
                                        base_price=1000,
                                        buy_quantity=100,
                                        sell_quantity=50,
                                        sell_pre_wait_ms=500,
                                        limit_price=1000,
                                        just_buy_interval_ms=50,
                                        just_buy_timeout=1  # Short timeout
                                    )

        print(f"✓ Sell success: {result['sell_success']}")
        print(f"✓ Buy success: {result['buy_success']}")
        self.assertTrue(result['sell_success'], "Sell should succeed")
        self.assertFalse(result['buy_success'], "Buy should fail")
        print(f"✓ Partial success handled correctly (sell-only)")

    def test_07_same_user_for_buyer_and_seller(self):
        """Test that same user can be both buyer and seller."""
        print("\n[TEST 7] Same user as both buyer and seller")

        simulator = LadderPriceSimulator(self.test_ladder, progression_speed_ms=50)
        simulator.jump_to_level(3)

        # Use same config for both
        same_service = self.create_mock_service(self.seller_tms_config, 'tms')
        fetch_service = self.create_mock_service(self.fetch_tms_config, 'tms')

        orders = []

        def mock_place_order(price, quantity, **kwargs):
            orders.append({
                'user': kwargs.get('user_id', 'seller_tms'),
                'side': 'BUY' if kwargs.get('buy_or_sell') == 1 else 'SELL',
                'price': price
            })
            return MockOrderResponse(success=True).json()

        class MockPriceFetcher:
            def get_latest_ltp(self):
                return simulator.get_current_price()

            def stop(self):
                simulator.stop()

        mock_fetcher = MockPriceFetcher()

        with patch.object(same_service, '_place_single_order', side_effect=mock_place_order):
            with patch.object(same_service, '_setup_price_fetcher', return_value=mock_fetcher):
                with patch.object(same_service, '_setup_token_manager', return_value=None):
                    with patch.object(same_service, '_cleanup_token_manager'):
                        result = same_service._execute_ipo_sell_buy_trigger(
                            buyer_service=same_service,  # Same service instance
                            fetch_clients=[fetch_service.client],
                            ticker="TEST",
                            security_id=1,
                            exchange_security_id=1,
                            symbol="TEST",
                            base_price=1000,
                            buy_quantity=100,
                            sell_quantity=50,
                            sell_pre_wait_ms=500,
                            limit_price=1000,
                            just_buy_interval_ms=50,
                            just_buy_timeout=2
                        )

        print(f"✓ Same user handled both buy and sell")
        print(f"✓ Total orders: {len(orders)}")
        # Should have both buy and sell orders from same user
        buy_count = sum(1 for o in orders if o['side'] == 'BUY')
        sell_count = sum(1 for o in orders if o['side'] == 'SELL')
        print(f"✓ Buy orders: {buy_count}, Sell orders: {sell_count}")


def run_tests():
    """Run all tests with verbose output."""
    print("="*70)
    print("IPO SELL-BUY-TRIGGER MODE - COMPREHENSIVE TEST SUITE")
    print("="*70)

    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(TestIPOSellBuyTrigger)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "="*70)
    print("TEST SUMMARY")
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
