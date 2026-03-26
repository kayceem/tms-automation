#!/usr/bin/env python3
"""
Test to determine exact token expiry time.

This test refreshes tokens and then attempts to place an order at specific
intervals after the refresh to determine when tokens expire.
"""

import sys
import time
import json
from pathlib import Path
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from api.tms_client import TMSClient
from config import UserConfig
from utils.logger import get_logger

logger = get_logger(__name__)


def test_token_expiry_at_intervals():
    """Test token expiry by placing orders at specific intervals after token refresh."""

    print("\n" + "="*80)
    print("TOKEN EXPIRY TEST - Testing order placement at intervals after token refresh")
    print("="*80)

    # Load user config
    user_config_path = Path(__file__).parent.parent / 'users' / 'user1.json'
    print(f"\nLoading user config from: {user_config_path}")

    with open(user_config_path, 'r') as f:
        user_config_data = json.load(f)

    user_config = UserConfig.from_dict(user_config_data)
    print(f"User: {user_config.user_id}")

    # Load first order from order store
    order_store_path = Path(__file__).parent.parent / 'stores' / 'order_store.json'
    print(f"Loading order from: {order_store_path}")

    with open(order_store_path, 'r') as f:
        order_store = json.load(f)

    if not order_store.get('orders'):
        print("ERROR: No orders found in order store")
        return False

    first_order = order_store['orders'][0]
    print(f"Order: {first_order['id']} - {first_order['ticker']}")
    print(f"Price: Rs. {first_order['price']}, Quantity: {first_order['quantity']}")

    # Load ticker info to get security IDs
    ticker_store_path = Path(__file__).parent.parent / 'stores' / 'ticker_store.json'
    with open(ticker_store_path, 'r') as f:
        ticker_store = json.load(f)

    ticker_symbol = first_order['ticker']
    ticker_info = ticker_store.get(ticker_symbol)

    if not ticker_info or ticker_symbol.startswith('_'):
        print(f"ERROR: Ticker {ticker_symbol} not found in ticker store")
        return False

    # Get security IDs (same for all hosts in the new format)
    security_id = ticker_info.get('security_id')
    exchange_security_id = ticker_info.get('exchange_security_id')

    if not security_id or not exchange_security_id:
        print(f"ERROR: Missing security IDs for ticker {ticker_symbol}")
        return False

    print(f"Security ID: {security_id}, Exchange Security ID: {exchange_security_id}")

    # Create TMS client
    client = TMSClient(user_config)

    # Test intervals (in seconds after token refresh)
    test_intervals = [59, 60, 61, 90, 120]

    results = []

    for interval in test_intervals:
        print("\n" + "-"*80)
        print(f"TEST: Placing order {interval} seconds after token refresh")
        print("-"*80)

        # Step 1: Refresh tokens
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Refreshing tokens...")
        refresh_success = client.refresh_tokens()

        if not refresh_success:
            print("ERROR: Token refresh failed")
            results.append({
                'interval': interval,
                'refresh_success': False,
                'order_success': None,
                'error': 'Token refresh failed'
            })
            continue

        refresh_time = datetime.now()
        print(f"[{refresh_time.strftime('%H:%M:%S')}] ✓ Tokens refreshed successfully")

        # Step 2: Wait for specified interval
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Waiting {interval} seconds before placing order...")

        # Show countdown for last 10 seconds
        if interval > 10:
            print(f"Sleeping for {interval - 10} seconds...")
            time.sleep(interval - 10)
            remaining = 10
        else:
            remaining = interval

        for i in range(remaining, 0, -1):
            print(f"  {i}...", end='', flush=True)
            time.sleep(1)
        print()

        # Step 3: Place order
        order_time = datetime.now()
        elapsed = (order_time - refresh_time).total_seconds()

        print(f"\n[{order_time.strftime('%H:%M:%S')}] Placing order (elapsed: {elapsed:.1f}s)...")

        try:
            response = client.place_order(
                security_id=security_id,
                exchange_security_id=exchange_security_id,
                order_price=first_order['price'],
                order_quantity=1,  # Use minimal quantity for testing
                order_type=1,  # LMT
                order_validity=0,  # DAY
                client_data=user_config.client_data,
                buy_or_sell=1  # Buy
            )

            status = response.get('status')
            message = response.get('message', 'No message')

            print(f"\nResponse Status: {status}")
            print(f"Response Message: {message}")

            success = status == 200

            results.append({
                'interval': interval,
                'refresh_success': True,
                'refresh_time': refresh_time.strftime('%H:%M:%S'),
                'order_time': order_time.strftime('%H:%M:%S'),
                'elapsed': elapsed,
                'order_success': success,
                'status': status,
                'message': message
            })

            if success:
                print(f"✓ Order placed successfully at {interval}s interval")
            else:
                print(f"✗ Order failed at {interval}s interval: {message}")

        except Exception as e:
            print(f"✗ Exception during order placement: {str(e)}")
            results.append({
                'interval': interval,
                'refresh_success': True,
                'refresh_time': refresh_time.strftime('%H:%M:%S'),
                'order_time': order_time.strftime('%H:%M:%S'),
                'elapsed': elapsed,
                'order_success': False,
                'error': str(e)
            })

        # Wait a bit between tests
        if interval != test_intervals[-1]:
            print("\nWaiting 5 seconds before next test...")
            time.sleep(5)

    # Print summary
    print("\n\n" + "="*80)
    print("TEST RESULTS SUMMARY")
    print("="*80)

    print(f"\n{'Interval':<12} {'Refresh':<10} {'Order':<10} {'Message':<40}")
    print("-"*80)

    for result in results:
        interval = f"{result['interval']}s"
        refresh = "✓" if result.get('refresh_success') else "✗"
        order = "✓" if result.get('order_success') else "✗"
        message = result.get('message', result.get('error', 'Unknown'))[:40]

        print(f"{interval:<12} {refresh:<10} {order:<10} {message:<40}")

    # Determine expiry threshold
    print("\n" + "="*80)
    print("ANALYSIS")
    print("="*80)

    success_intervals = [r['interval'] for r in results if r.get('order_success')]
    failed_intervals = [r['interval'] for r in results if r.get('order_success') == False]

    if success_intervals:
        print(f"\n✓ Successful intervals: {success_intervals}")

    if failed_intervals:
        print(f"✗ Failed intervals: {failed_intervals}")

    if success_intervals and failed_intervals:
        max_success = max(success_intervals)
        min_failure = min(failed_intervals)

        if min_failure > max_success:
            print(f"\n→ Tokens appear to expire between {max_success}s and {min_failure}s")
            print(f"→ Safe refresh interval: ≤{max_success}s")
        else:
            print(f"\n→ Results are inconclusive - failures at {min_failure}s but success at {max_success}s")
    elif not failed_intervals:
        print(f"\n→ All intervals succeeded - tokens valid for at least {max(success_intervals)}s")
    else:
        print(f"\n→ All intervals failed - check token refresh or order parameters")

    print("\n" + "="*80)

    return True


if __name__ == '__main__':
    try:
        success = test_token_expiry_at_intervals()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print("\n\nTest interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
