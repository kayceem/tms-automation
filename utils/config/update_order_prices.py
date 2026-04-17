#!/usr/bin/env python3
"""
Update prices and limits in order store using ATRAD quote endpoint.

This script fetches current market prices for all tickers in the order store
and updates the 'price' and 'limit' fields with tradeprice and closingprice
from the ATRAD quote endpoint.
"""

import json
import argparse
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.atrad_client import ATRADClient
from config.models import ATRADUserConfig
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class PriceUpdateResult:
    updated_count: int
    skipped_count: int
    failed_count: int
    updated: Dict[str, Dict[str, float | None]]
    message: Optional[str] = None


def get_quote_data(client: ATRADClient, ticker: str) -> Optional[Dict[str, float]]:
    """
    Fetch quote data for a ticker using ATRAD quote endpoint.

    Args:
        client: ATRAD client instance
        ticker: Stock ticker symbol

    Returns:
        Dict with 'price' (tradeprice) and 'limit' (closingprice), or None if failed
    """
    try:
        logger.info(f"Fetching quote for {ticker}...")

        # Use the existing quote endpoint from client
        epoch_time_ms = lambda: int(round(time.time() * 1000))
        endpoint = f"{client.quick_watch_endpoint}&securityid={ticker}&watchId={client.user_config._watch_id}&dojo.preventCache="
        response = client.session.get(endpoint + str(epoch_time_ms()), timeout=5.0)
        response.encoding = 'utf-8'

        if response.status_code == 200:
            data = response.text.strip().replace("'", '"')
            data = json.loads(data)

            security = (data.get('data', {})).get('watch', [{}])[0]

            if not security or not isinstance(security, dict):
                logger.warning(f"No security data for {ticker}")
                return None
            print(f"Raw quote data for {ticker}: {security}")

            # Extract tradeprice and closingprice
            tradeprice_str = security.get('tradeprice', '')
            closingprice_str = security.get('closingprice', '')

            if tradeprice_str:
                tradeprice = float(tradeprice_str.replace(',', ''))
            else:
                tradeprice = None
            if closingprice_str:
                closingprice = float(closingprice_str.replace(',', ''))
            else:
                closingprice = None
            logger.info(f"{ticker}: price={tradeprice}, limit={closingprice}")

            return {
                'price': tradeprice,
                'limit': closingprice
            }

        else:
            logger.error(f"Failed to fetch quote for {ticker}: HTTP {response.status_code}")
            return None

    except Exception as e:
        logger.error(f"Error fetching quote for {ticker}: {str(e)}")
        return None


def update_order_store(
    order_store_path: str,
    atrad_user_path: str,
    dry_run: bool = False,
    ticker_filter: Optional[str] = None
) -> PriceUpdateResult:
    """
    Update prices in order store using ATRAD quotes.

    Args:
        order_store_path: Path to order store JSON file
        atrad_user_path: Path to ATRAD user config JSON file
        dry_run: If True, show changes without saving
        ticker_filter: If provided, only update this specific ticker
    """
    # Load ATRAD user config
    logger.info(f"Loading ATRAD user config from {atrad_user_path}")
    user_config = ATRADUserConfig.from_file(atrad_user_path)

    # Create ATRAD client
    logger.info(f"Initializing ATRAD client for user: {user_config.user_id}")
    client = ATRADClient(user_config)

    # Ensure authenticated
    if not client.ensure_authenticated():
        logger.error("Failed to authenticate ATRAD client")
        return PriceUpdateResult(
            updated_count=0,
            skipped_count=0,
            failed_count=0,
            updated={},
        )

    logger.info("ATRAD client authenticated")

    # Load order store
    logger.info(f"Loading order store from {order_store_path}")
    with open(order_store_path, 'r') as f:
        order_store = json.load(f)

    orders = order_store.get('orders', [])
    logger.info(f"Found {len(orders)} orders in store")

    # Track updates
    updated_count = 0
    skipped_count = 0
    failed_count = 0
    updated = {}
    # Process each order
    for order in orders:
        ticker = order.get('ticker', '').upper()
        order_id = order.get('id', 'unknown')

        # Skip if ticker filter is set and doesn't match
        if ticker_filter and ticker.upper() != ticker_filter.upper():
            skipped_count += 1
            continue

        if not ticker:
            logger.warning(f"Order {order_id} has no ticker, skipping")
            skipped_count += 1
            continue

        # Get current values
        old_price = order.get('price')
        old_limit = order.get('limit')

        # Fetch quote data
        quote = get_quote_data(client, ticker)

        if quote:
            new_price = quote['price']
            new_limit = quote['limit']

            # Only update limit if new_limit is not None
            if new_limit is not None:
                order['limit'] = new_limit
            if new_price is not None:
                order['price'] = new_price

            updated[ticker] = {
                'price': new_price,
                'limit': new_limit,
                'old_price': old_price,
                'old_limit': old_limit
            }
            updated_count += 1
        else:
            logger.error(f"Failed to get quote for {ticker} (order: {order_id})")
            failed_count += 1

        time.sleep(0.25)

    # Save updated order store
    if not dry_run and updated_count > 0:
        logger.info(f"Saving updated order store to {order_store_path}")
        with open(order_store_path, 'w') as f:
            json.dump(order_store, f, indent=2)
        logger.info("Order store saved")

    # Summary
    print("="*70)
    for ticker, data in updated.items():
        print(f"{ticker}:")
        print(f"  Price: {data['old_price']} -> {data['price']}")
        print(f"  Limit: {data['old_limit']} -> {data['limit']}")
    print("="*70)
    return PriceUpdateResult(
        updated_count=updated_count,
        skipped_count=skipped_count,
        failed_count=failed_count,
        updated=updated,
    )


def main():
    parser = argparse.ArgumentParser(
        description='Update prices and limits in order store using ATRAD quote endpoint',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run - show what would be updated without saving
  python utils/update_order_prices.py --dry-run

  # Update all orders in the default order store
  python utils/update_order_prices.py

  # Update only a specific ticker
  python utils/update_order_prices.py --ticker NABIL

  # Use a different ATRAD user config
  python utils/update_order_prices.py --atrad-user users/atrad_user2.json

  # Use a different order store
  python utils/update_order_prices.py --order-store stores/my_orders.json

The script will:
  1. Load the ATRAD user config and authenticate
  2. For each order in the store, fetch quote data from ATRAD
  3. Update 'price' field with 'tradeprice' from quote
  4. Update 'limit' field with 'closingprice' from quote
  5. Save the updated order store (unless --dry-run is used)
"""
    )

    parser.add_argument(
        '--order-store',
        default='stores/order_store.json',
        help='Path to order store JSON file (default: stores/order_store.json)'
    )

    parser.add_argument(
        '--atrad-user',
        default='users/atrad_user1.json',
        help='Path to ATRAD user config JSON file (default: users/atrad_user.json)'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be updated without actually saving changes'
    )

    parser.add_argument(
        '--ticker',
        help='Only update orders for this specific ticker (case-insensitive)'
    )

    args = parser.parse_args()

    # Resolve paths
    project_root = Path(__file__).parent.parent.parent
    order_store_path = project_root / args.order_store
    atrad_user_path = project_root / args.atrad_user

    # Check if files exist
    if not order_store_path.exists():
        print(f"Error: Order store not found: {order_store_path}")
        sys.exit(1)

    if not atrad_user_path.exists():
        print(f"Error: ATRAD user config not found: {atrad_user_path}")
        sys.exit(1)

    # only update outside of market hours (11:00 - 15:00)
    if time.localtime().tm_hour >= 11 and time.localtime().tm_hour < 15:
        print("Warning: It's currently market hours (11:00 - 15:00). Price updates may be inaccurate.")
        sys.exit(0)

    # Run update
    update_order_store(
        order_store_path=str(order_store_path),
        atrad_user_path=str(atrad_user_path),
        dry_run=args.dry_run,
        ticker_filter=args.ticker
    )


if __name__ == "__main__":
    main()
