#!/usr/bin/env python3
"""
NEPSE TMS Order Automation Bot - Multi-User Edition

A command-line tool for automating order placement on NEPSE TMS with multi-user support.
"""

import argparse
import sys
import threading
from pathlib import Path
from typing import List, Dict, Any

from config import UserConfig
from api import TMSClient
from services import OrderService, OrderScheduler
from utils import validate_positive_number, validate_positive_integer, setup_logger, lookup_ticker, get_ticker_store, OrderStore

logger = setup_logger(
    name='tms_automation',
    log_file='logs/tms_automation.log',
    level=20,
    console_output=True
)


def create_parser() -> argparse.ArgumentParser:
    """Create and configure argument parser."""
    parser = argparse.ArgumentParser(
        description='NEPSE TMS Order Automation Bot - Multi-User Edition',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Using order store (recommended - predefined orders)
  python main.py --user-config users/user1.json --order-store order_store.json

  # Multi-user with order store
  python main.py --user-configs users/ --order-store order_store.json

  # Manual order with ticker symbol
  python main.py --user-config users/user1.json --ticker NABIL --price 500 --quantity 10

  # Manual order with explicit security IDs
  python main.py --user-config users/user1.json --security-id 123 --exchange-security-id 456 --price 500 --quantity 10

  # Scheduled manual order
  python main.py --user-config users/user1.json --ticker NABIL --price 500 --quantity 10 --time 14:30

  # IPO sniping mode (manual)
  python main.py --user-configs users/ --ticker EXAMPLE --price 1000 --quantity 10 --ipo --limit 1050
        '''
    )

    # User configuration
    user_group = parser.add_mutually_exclusive_group(required=True)
    user_group.add_argument(
        '--user-config',
        type=str,
        help='Path to single user configuration JSON file'
    )
    user_group.add_argument(
        '--user-configs',
        type=str,
        help='Path to directory containing multiple user configuration JSON files'
    )

    # Order mode - either order store OR manual order specification
    order_mode = parser.add_mutually_exclusive_group(required=True)
    order_mode.add_argument(
        '--order-store',
        type=str,
        help='Path to order store JSON file. Executes the order marked with execute=true'
    )
    order_mode.add_argument(
        '--ticker',
        type=str,
        help='Ticker symbol (e.g., NABIL, NICA) for manual order. Will auto-populate security-id and exchange-security-id from ticker store'
    )
    order_mode.add_argument(
        '--security-id',
        type=int,
        help='Security ID for manual order (required if not using --ticker or --order-store)'
    )

    # Exchange security ID - required only when using --security-id
    parser.add_argument(
        '--exchange-security-id',
        type=int,
        help='Exchange security ID (required when using --security-id)'
    )

    # Order parameters (required for manual mode, ignored in order-store mode)
    parser.add_argument(
        '--price',
        type=float,
        help='Order price per unit (required for manual orders)'
    )
    parser.add_argument(
        '--quantity',
        type=int,
        help='Order quantity (number of units) (required for manual orders)'
    )

    # Optional parameters
    parser.add_argument(
        '--time',
        type=str,
        help='Schedule order for specific time (format: HH:MM or HH:MM:SS)'
    )
    parser.add_argument(
        '--sell',
        action='store_true',
        help='Place a sell order (default is buy)'
    )
    parser.add_argument(
        '--order-type',
        type=str,
        help='Order type (default: LMT). Options: LMT, MKT, SL, etc.'
    )
    parser.add_argument(
        '--order-validity',
        type=str,
        help='Order validity (default: DAY). Options: DAY, IOC, etc.'
    )
    parser.add_argument(
        '--client-data',
        type=str,
        help='Path to JSON file with client data (optional)'
    )
    parser.add_argument(
        '--ipo',
        action='store_true',
        help='IPO sniping mode: automatically place orders at +2%, +4%, +6%, +8%, +10%'
    )
    parser.add_argument(
        '--ipo-sniper',
        action='store_true',
        help='IPO sniper mode: aggressively place orders at +10% for 2 minutes'
    )
    parser.add_argument(
        '--limit',
        type=float,
        help='Upper limit price for IPO mode. Orders above +10%% of this limit will be removed, and +10%% of limit will be the final order'
    )
    parser.add_argument(
        '--log-level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)'
    )

    return parser


def validate_args(args: argparse.Namespace):
    """
    Validate command-line arguments and resolve ticker if provided.

    Args:
        args: Parsed arguments

    Raises:
        ValueError: If validation fails
    """
    # Skip validation for order store mode - will be validated separately
    if args.order_store:
        return

    # Manual order mode validation
    # Handle ticker lookup
    if args.ticker:
        try:
            security_id, exchange_security_id = lookup_ticker(args.ticker)
            args.security_id = security_id
            args.exchange_security_id = exchange_security_id
            logger.info(f"Ticker '{args.ticker}' resolved to security_id={security_id}, exchange_security_id={exchange_security_id}")
        except (FileNotFoundError, ValueError) as e:
            raise ValueError(f"Ticker lookup failed: {e}")
    else:
        # If using --security-id, --exchange-security-id is required
        if not args.exchange_security_id:
            raise ValueError("--exchange-security-id is required when using --security-id")

    # Validate required fields for manual mode
    if not args.price:
        raise ValueError("--price is required for manual orders")
    if not args.quantity:
        raise ValueError("--quantity is required for manual orders")

    validate_positive_integer(args.security_id, 'security-id')
    validate_positive_integer(args.exchange_security_id, 'exchange-security-id')
    validate_positive_number(args.price, 'price')
    validate_positive_integer(args.quantity, 'quantity')

    if args.ipo and args.ipo_sniper:
        raise ValueError("Cannot use both --ipo and --ipo-sniper flags together. Choose one.")

    if args.limit and not args.ipo:
        logger.warning("--limit flag is only used with --ipo mode. It will be ignored.")

    if args.limit:
        validate_positive_number(args.limit, 'limit')


def load_user_configs(args: argparse.Namespace) -> List[UserConfig]:
    """
    Load user configurations based on command-line arguments.

    Args:
        args: Parsed arguments

    Returns:
        List of UserConfig instances
    """
    user_configs = []

    if args.user_config:
        # Single user mode
        logger.info(f"Loading single user configuration from {args.user_config}")
        user_config = UserConfig.from_file(args.user_config)
        user_configs.append(user_config)
        logger.info(f"Loaded configuration for user: {user_config.user_id}")

    elif args.user_configs:
        # Multi-user mode
        config_dir = Path(args.user_configs)
        if not config_dir.exists():
            raise FileNotFoundError(f"User config directory not found: {args.user_configs}")

        if not config_dir.is_dir():
            raise ValueError(f"--user-configs must be a directory: {args.user_configs}")

        logger.info(f"Loading user configurations from directory: {args.user_configs}")

        config_files = sorted(config_dir.glob('*.json'))
        if not config_files:
            raise ValueError(f"No JSON configuration files found in {args.user_configs}")

        for config_file in config_files:
            try:
                user_config = UserConfig.from_file(str(config_file))
                user_configs.append(user_config)
                logger.info(f"Loaded configuration for user: {user_config.user_id}")
            except Exception as e:
                logger.warning(f"Failed to load {config_file}: {e}")

        if not user_configs:
            raise ValueError(f"No valid user configurations loaded from {args.user_configs}")

    logger.info(f"Total users loaded: {len(user_configs)}")
    return user_configs


def execute_order_for_user(
    user_config: UserConfig,
    order_params: Dict[str, Any],
    scheduled_time: str = None
) -> Dict[str, Any]:
    """
    Execute an order for a single user (thread-safe).

    Args:
        user_config: User configuration
        order_params: Order parameters dictionary
        scheduled_time: Optional scheduled time string

    Returns:
        API response dictionary
    """
    user_id = user_config.user_id

    try:
        logger.info(f"[{user_id}] Starting order execution")

        # Create user-specific TMS client
        tms_client = TMSClient(user_config)

        # Create order service
        order_service = OrderService(tms_client)

        # Execute order
        if scheduled_time:
            # Scheduled execution
            result = OrderScheduler.schedule_order(
                time_str=scheduled_time,
                order_func=order_service.execute_order,
                tms_client=tms_client,
                user_id=user_id,
                **order_params
            )
        else:
            # Immediate execution
            result = order_service.execute_order(**order_params)

        logger.info(f"[{user_id}] Order execution completed successfully")
        return result

    except Exception as e:
        logger.error(f"[{user_id}] Order execution failed: {str(e)}", exc_info=True)
        raise


def execute_from_order_store(
    user_configs: List[UserConfig],
    order_store_path: str
) -> Dict[str, Any]:
    """
    Execute an order from the order store.

    Args:
        user_configs: List of UserConfig instances
        order_store_path: Path to order store JSON file

    Returns:
        API response dictionary

    Raises:
        ValueError: If no order to execute or validation fails
    """
    # Load order store
    logger.info(f"Loading order store from {order_store_path}")
    order_store = OrderStore(order_store_path)

    # Display order summary
    logger.info("\n" + order_store.get_order_summary())

    # Get executable order
    order = order_store.get_executable_order()

    if order is None:
        raise ValueError("No order marked for execution in order store")

    # Validate order
    order = order_store.validate_order(order)
    order_id = order['id']

    logger.info("="*60)
    logger.info(f"Executing order: {order_id}")
    logger.info("="*60)

    # Resolve ticker to IDs
    try:
        security_id, exchange_security_id = lookup_ticker(order['ticker'])
        logger.info(
            f"Ticker '{order['ticker']}' resolved to "
            f"security_id={security_id}, exchange_security_id={exchange_security_id}"
        )
    except (FileNotFoundError, ValueError) as e:
        order_store.mark_failed(order_id)
        raise ValueError(f"Ticker lookup failed for '{order['ticker']}': {e}")

    # Determine mode flags
    ipo_mode = order['mode'] == 'ipo'
    ipo_sniper_mode = order['mode'] == 'ipo-sniper'
    buy_or_sell = 2 if order['sell'] else 1

    # Prepare order parameters
    order_params = {
        'security_id': security_id,
        'exchange_security_id': exchange_security_id,
        'order_price': order['price'],
        'order_quantity': order['quantity'],
        'buy_or_sell': buy_or_sell,
        'order_type': None,  # Use defaults from user config
        'order_validity': None,
        'client_data_file': None,
        'ipo_mode': ipo_mode,
        'ipo_sniper_mode': ipo_sniper_mode,
        'limit_price': order['limit']
    }

    # Log execution details
    mode_str = order['mode'].upper()
    logger.info(f"Execution Mode: {mode_str}")
    logger.info(f"Number of Users: {len(user_configs)}")
    logger.info(f"Order: {'SELL' if order['sell'] else 'BUY'}")
    logger.info(f"Ticker: {order['ticker']}")
    logger.info(f"Security ID: {security_id}")
    logger.info(f"Exchange Security ID: {exchange_security_id}")
    logger.info(f"Price: {order['price']}, Quantity: {order['quantity']}")
    if order['limit']:
        logger.info(f"Limit: {order['limit']}")
    if order['time']:
        logger.info(f"Scheduled Time: {order['time']}")
    logger.info(f"Token Refresh: {order['refresh_before']}s before execution")
    logger.info("="*60)

    try:
        # Execute order
        if len(user_configs) == 1:
            # Single user - execute directly
            result = execute_order_for_user(
                user_config=user_configs[0],
                order_params=order_params,
                scheduled_time=order['time']
            )
        else:
            # Multi-user - execute in parallel threads
            logger.info(f"Starting {len(user_configs)} threads for parallel execution")

            threads = []
            exceptions = []

            def thread_wrapper(user_config):
                try:
                    execute_order_for_user(
                        user_config=user_config,
                        order_params=order_params,
                        scheduled_time=order['time']
                    )
                except Exception as e:
                    exceptions.append((user_config.user_id, e))

            # Create and start threads
            for user_config in user_configs:
                thread = threading.Thread(
                    target=thread_wrapper,
                    args=(user_config,),
                    name=f"User-{user_config.user_id}"
                )
                threads.append(thread)
                thread.start()

            # Wait for all threads to complete
            for thread in threads:
                thread.join()

            # Check for exceptions
            if exceptions:
                logger.error(f"{"="*60}")
                logger.error(f"Execution completed with errors for {len(exceptions)} user(s)")
                for user_id, exc in exceptions:
                    logger.error(f"  [{user_id}] {str(exc)}")
                logger.error(f"{"="*60}")
                order_store.mark_failed(order_id)
                sys.exit(1)

            result = {"status": "success", "users": len(user_configs)}

        # Mark order as successful
        order_store.mark_success(order_id)
        logger.info(f"Order '{order_id}' marked as successful in store")

        return result

    except Exception as e:
        order_store.mark_failed(order_id)
        raise


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Setup logging with specified level
    log_level_map = {
        'DEBUG': 10,
        'INFO': 20,
        'WARNING': 30,
        'ERROR': 40
    }
    log_level = log_level_map.get(args.log_level, 20)

    # Reconfigure logger with user-specified level
    for handler in logger.handlers:
        handler.setLevel(log_level)
    logger.setLevel(log_level)

    try:
        logger.info("="*60)
        logger.info("NEPSE TMS Order Automation Bot - Multi-User Edition")
        logger.info("="*60)

        # Validate arguments
        validate_args(args)

        # Load user configurations
        user_configs = load_user_configs(args)

        # Check if using order store mode
        if args.order_store:
            # Order store mode
            execute_from_order_store(user_configs, args.order_store)
        else:
            # Manual order mode
            # Determine buy or sell
            buy_or_sell = 2 if args.sell else 1

            # Prepare order parameters (shared across all users)
            order_params = {
                'security_id': args.security_id,
                'exchange_security_id': args.exchange_security_id,
                'order_price': args.price,
                'order_quantity': args.quantity,
                'buy_or_sell': buy_or_sell,
                'order_type': args.order_type,
                'order_validity': args.order_validity,
                'client_data_file': args.client_data,
                'ipo_mode': args.ipo,
                'ipo_sniper_mode': args.ipo_sniper,
                'limit_price': args.limit
            }

            # Log execution mode
            mode = "SCHEDULED" if args.time else "IMMEDIATE"
            if args.ipo:
                mode += " (IPO SNIPING)"
            elif args.ipo_sniper:
                mode += " (IPO SNIPER)"

            logger.info(f"Execution Mode: {mode}")
            logger.info(f"Number of Users: {len(user_configs)}")
            logger.info(f"Order: {'SELL' if args.sell else 'BUY'}")

            # Display ticker info if available
            if args.ticker:
                try:
                    ticker_store = get_ticker_store()
                    name = ticker_store.get_name(args.ticker)
                    if name:
                        logger.info(f"Ticker: {args.ticker} ({name})")
                    else:
                        logger.info(f"Ticker: {args.ticker}")
                except Exception:
                    logger.info(f"Ticker: {args.ticker}")

            logger.info(f"Security ID: {args.security_id}")
            logger.info(f"Exchange Security ID: {args.exchange_security_id}")
            logger.info(f"Price: {args.price}, Quantity: {args.quantity}")
            logger.info("="*60)

            # Execute orders
            if len(user_configs) == 1:
                # Single user - execute directly
                execute_order_for_user(
                    user_config=user_configs[0],
                    order_params=order_params,
                    scheduled_time=args.time
                )
            else:
                # Multi-user - execute in parallel threads
                logger.info(f"Starting {len(user_configs)} threads for parallel execution")

                threads = []
                exceptions = []

                def thread_wrapper(user_config):
                    try:
                        execute_order_for_user(
                            user_config=user_config,
                            order_params=order_params,
                            scheduled_time=args.time
                        )
                    except Exception as e:
                        exceptions.append((user_config.user_id, e))

                # Create and start threads
                for user_config in user_configs:
                    thread = threading.Thread(
                        target=thread_wrapper,
                        args=(user_config,),
                        name=f"User-{user_config.user_id}"
                    )
                    threads.append(thread)
                    thread.start()

                # Wait for all threads to complete
                for thread in threads:
                    thread.join()

                # Check for exceptions
                if exceptions:
                    logger.error(f"{"="*60}")
                    logger.error(f"Execution completed with errors for {len(exceptions)} user(s)")
                    for user_id, exc in exceptions:
                        logger.error(f"  [{user_id}] {str(exc)}")
                    logger.error(f"{"="*60}")
                    sys.exit(1)

        logger.info("="*60)
        logger.info("All orders completed successfully!")
        logger.info("="*60)

    except KeyboardInterrupt:
        logger.info("="*60)
        logger.warning("Operation cancelled by user (Ctrl+C)")
        logger.info("="*60)
        sys.exit(130)  # Standard exit code for SIGINT
    except ValueError as e:
        logger.error(f"Configuration Error: {str(e)}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Error: {str(e)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
