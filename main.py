#!/usr/bin/env python3
"""
NEPSE TMS Order Automation Bot

A command-line tool for automating order placement on NEPSE TMS.
"""

import argparse
import sys
from typing import Dict, Any, List, Optional

from config import UserConfig, ATRADUserConfig
from api import TMSClient, ATRADClient
from services import OrderService, OrderScheduler, ATRADOrderService
from utils import validate_positive_number, validate_positive_integer, setup_logger, OrderStore, detect_system_from_config

logger = setup_logger(
    name='main',
    log_file='tms_automation.log',
    level=20,
    console_output=True
)


def create_parser() -> argparse.ArgumentParser:
    """Create and configure argument parser."""
    parser = argparse.ArgumentParser(
        description='NEPSE TMS Order Automation Bot',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Using order store (recommended - predefined orders)
  python main.py --user-config users/user1.json --order-store order_store.json

  # Manual order with ticker symbol
  python main.py --user-config users/user1.json --ticker NABIL --price 500 --quantity 10

  # Manual order with explicit security IDs
  python main.py --user-config users/user1.json --security-id 123 --exchange-security-id 456 --price 500 --quantity 10

  # Scheduled manual order
  python main.py --user-config users/user1.json --ticker NABIL --price 500 --quantity 10 --time 14:30

  # IPO trigger mode (manual) - single fetch user
  python main.py --user-config users/user1.json --fetch-user users/fetch_user.json --ticker EXAMPLE --price 1000 --quantity 10 --ipo-trigger --limit 1050

  # IPO trigger mode with multi-user fetch (reduces rate limiting)
  python main.py --user-config users/user1.json --fetch-users users/fetch1.json users/fetch2.json --ticker EXAMPLE --price 1000 --quantity 10 --ipo-trigger --limit 1050

  # IPO trigger mode with ATRAD fetch users
  python main.py --user-config users/atrad_user1.json --fetch-users users/atrad_fetch1.json users/atrad_fetch2.json --atrad-fetch --ticker EXAMPLE --price 1000 --quantity 10 --ipo-trigger --limit 1050

  # IPO trigger mode with skip-first
  python main.py --user-config users/user1.json --fetch-user users/fetch_user.json --ticker EXAMPLE --price 1000 --quantity 10 --ipo-trigger --skip-first --limit 1050
        '''
    )

    # User configuration
    parser.add_argument(
        '--user-config',
        type=str,
        required=True,
        help='Path to user configuration JSON file'
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
        '--ipo-trigger',
        action='store_true',
        help='IPO trigger mode: monitor LTP and place ladder orders based on price levels. When LTP >= ladder[i], places order at ladder[i+1].'
    )
    parser.add_argument(
        '--trigger-sell',
        action='store_true',
        help='Trigger sell mode: monitor LTP and place sell order when price drops to trigger level. Trigger price calculated as sell_price / 1.02 (floored to 1 decimal).'
    )
    fetch_user_group = parser.add_mutually_exclusive_group()
    fetch_user_group.add_argument(
        '--fetch-user',
        type=str,
        help='Path to single fetch user JSON file (required for --ipo-trigger). This user will be used to fetch LTP.'
    )
    fetch_user_group.add_argument(
        '--fetch-users',
        type=str,
        nargs='+',
        help='Paths to multiple fetch user JSON files for multi-user rotation. Reduces rate limiting during LTP monitoring.'
    )
    parser.add_argument(
        '--atrad-fetch',
        action='store_true',
        help='Use ATRAD fetch users instead of TMS fetch users. Fetch users will use ATRAD client for LTP monitoring.'
    )
    parser.add_argument(
        '--skip-first',
        action='store_true',
        help='Skip the first ladder level in IPO trigger mode. Places first order when LTP reaches ladder[0], starting from ladder[1].'
    )
    parser.add_argument(
        '--limit',
        type=float,
        help='Upper limit price for IPO mode. Orders above +10 percent of this limit will be removed, and +10 percent of limit will be the final order'
    )
    parser.add_argument(
        '--log-level',
        type=str,
        default='INFO',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
        help='Logging level (default: INFO)'
    )
    parser.add_argument(
        '--double-buy',
        action='store_true',
        help='Enable double buy: place a second order 0.5s after first order succeeds'
    )
    parser.add_argument(
        '--double-buy-quantity',
        type=int,
        help='Quantity for the second order in double buy mode (defaults to same as --quantity if not specified)'
    )
    parser.add_argument(
        '--just-buy',
        action='store_true',
        help='Enable just buy mode (no_ladder only): Aggressively place orders when switch threshold is reached'
    )
    parser.add_argument(
        '--just-buy-interval',
        type=int,
        default=100,
        help='Interval between just buy order attempts in milliseconds (default: 100ms)'
    )
    parser.add_argument(
        '--just-buy-timeout',
        type=int,
        default=5,
        help='Total duration for just buy attempts in seconds (default: 5s)'
    )
    parser.add_argument(
        '--just-buy-pre-wait',
        type=int,
        default=0,
        help='Wait time in milliseconds after switch threshold before starting just buy (default: 0ms)'
    )

    # IPO Sell-Buy-Trigger Mode
    parser.add_argument(
        '--ipo-sell-buy-trigger',
        action='store_true',
        help='IPO sell-buy-trigger mode: Coordinates sell and buy orders when third last level reached'
    )
    parser.add_argument(
        '--seller',
        type=str,
        help='Path to seller user JSON file (required for --ipo-sell-buy-trigger). Can be TMS or ATRAD user.'
    )
    parser.add_argument(
        '--buyer',
        type=str,
        help='Path to buyer user JSON file (required for --ipo-sell-buy-trigger). Can be TMS or ATRAD user.'
    )
    parser.add_argument(
        '--sell-quantity',
        type=int,
        help='Quantity for sell order in ipo-sell-buy-trigger mode (required for --ipo-sell-buy-trigger)'
    )
    parser.add_argument(
        '--sell-pre-wait-ms',
        type=int,
        default=5000,
        help='Wait time in milliseconds before starting buy/sell sequence after third last level reached (default: 5000ms)'
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
            from utils import get_ticker_store
            ticker_store = get_ticker_store()
            security_id, exchange_security_id = ticker_store.lookup(args.ticker)

            args.security_id = security_id
            args.exchange_security_id = exchange_security_id
            # Note: fetch_id will be resolved later after fetch_user is loaded

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

    # Validate mutually exclusive IPO/trigger modes
    mode_flags = [args.ipo_trigger, args.trigger_sell, args.ipo_sell_buy_trigger]
    mode_count = sum(1 for flag in mode_flags if flag)

    if mode_count > 1:
        raise ValueError(
            "Cannot use multiple mode flags together. "
            "Choose one: --ipo-trigger, --trigger-sell, or --ipo-sell-buy-trigger"
        )

    # Validate fetch-user requirement for trigger modes
    has_fetch_user = args.fetch_user or args.fetch_users
    if args.ipo_trigger and not has_fetch_user:
        raise ValueError("--fetch-user or --fetch-users is required when using --ipo-trigger mode")

    if args.trigger_sell and not has_fetch_user:
        raise ValueError("--fetch-user is required when using --trigger-sell mode (only single fetch user supported)")

    # Validate ipo-sell-buy-trigger mode
    if args.ipo_sell_buy_trigger:
        if not args.seller:
            raise ValueError("--seller is required when using --ipo-sell-buy-trigger mode")
        if not args.buyer:
            raise ValueError("--buyer is required when using --ipo-sell-buy-trigger mode")
        if not args.sell_quantity:
            raise ValueError("--sell-quantity is required when using --ipo-sell-buy-trigger mode")
        if not has_fetch_user:
            raise ValueError("--fetch-user or --fetch-users is required when using --ipo-sell-buy-trigger mode")

        # Validate numeric values
        validate_positive_integer(args.sell_quantity, 'sell-quantity')
        validate_positive_integer(args.sell_pre_wait_ms, 'sell-pre-wait-ms')

    # Warn if seller/buyer specified without mode
    if (args.seller or args.buyer) and not args.ipo_sell_buy_trigger:
        logger.warning("--seller/--buyer flags are only used with --ipo-sell-buy-trigger mode. They will be ignored.")

    if has_fetch_user and not (args.ipo_trigger or args.trigger_sell or args.ipo_sell_buy_trigger):
        logger.warning("--fetch-user/--fetch-users flag is only used with --ipo-trigger, --trigger-sell, or --ipo-sell-buy-trigger mode. It will be ignored.")

    if args.skip_first and not args.ipo_trigger:
        logger.warning("--skip-first flag is only used with --ipo-trigger mode. It will be ignored.")

    if args.limit and not args.ipo_trigger:
        logger.warning("--limit flag is only used with --ipo-trigger mode. It will be ignored.")

    if args.limit:
        validate_positive_number(args.limit, 'limit')

    # Validate double-buy parameters
    if args.double_buy_quantity and not args.double_buy:
        logger.warning("--double-buy-quantity is only used with --double-buy flag. It will be ignored.")

    if args.double_buy_quantity:
        validate_positive_integer(args.double_buy_quantity, 'double-buy-quantity')

    # Validate just-buy parameters
    if hasattr(args, 'just_buy') and args.just_buy:
        if not args.ipo_trigger:
            raise ValueError("--just-buy can only be used with --ipo-trigger mode")
        # Note: no_ladder validation happens in order store, so we can't validate it here for CLI mode

    if hasattr(args, 'just_buy_interval') and args.just_buy_interval:
        validate_positive_integer(args.just_buy_interval, 'just-buy-interval')

    if hasattr(args, 'just_buy_timeout') and args.just_buy_timeout:
        validate_positive_integer(args.just_buy_timeout, 'just-buy-timeout')


def load_user_config(args: argparse.Namespace):
    """
    Load user configuration from JSON file.
    Auto-detects whether it's a TMS or ATRAD user.

    Args:
        args: Parsed arguments

    Returns:
        UserConfig or ATRADUserConfig instance
    """
    import json
    from pathlib import Path

    logger.info(f"Loading user configuration from {args.user_config}")

    # Read the config file to detect system type
    config_path = Path(args.user_config)
    with open(config_path, 'r') as f:
        config_data = json.load(f)

    # Detect system type
    system_type = detect_system_from_config(config_data)

    # Load appropriate config class
    if system_type == 'atrad':
        user_config = ATRADUserConfig.from_file(args.user_config)
        logger.info(f"Loaded ATRAD configuration for user: {user_config.user_id}")
    else:
        user_config = UserConfig.from_file(args.user_config)
        logger.info(f"Loaded TMS configuration for user: {user_config.user_id}")

    return user_config


def load_fetch_user_configs(args: argparse.Namespace):
    """
    Load fetch user configurations based on command-line arguments.
    Supports both TMS and ATRAD fetch users.

    Args:
        args: Parsed arguments

    Returns:
        Tuple of (fetch_user_configs, is_atrad_fetch) where:
        - fetch_user_configs: List of UserConfig or ATRADUserConfig instances
        - is_atrad_fetch: Boolean indicating if ATRAD fetch users are being used
    """
    fetch_user_configs = []
    is_atrad_fetch = args.atrad_fetch if hasattr(args, 'atrad_fetch') else False

    if args.fetch_user:
        # Single fetch user mode
        logger.info(f"Loading single fetch user configuration from {args.fetch_user}")

        if is_atrad_fetch:
            fetch_user_config = ATRADUserConfig.from_file(args.fetch_user)
            logger.info(f"Loaded ATRAD fetch user: {fetch_user_config.user_id}")
        else:
            fetch_user_config = UserConfig.from_file(args.fetch_user)
            logger.info(f"Loaded TMS fetch user: {fetch_user_config.user_id}")

        fetch_user_configs.append(fetch_user_config)

    elif args.fetch_users:
        # Multi-fetch user mode
        logger.info(f"Loading {len(args.fetch_users)} fetch user configurations")

        for idx, fetch_user_file in enumerate(args.fetch_users, 1):
            try:
                if is_atrad_fetch:
                    fetch_user_config = ATRADUserConfig.from_file(fetch_user_file)
                    logger.info(f"Loaded ATRAD fetch user {idx}: {fetch_user_config.user_id}")
                else:
                    fetch_user_config = UserConfig.from_file(fetch_user_file)
                    logger.info(f"Loaded TMS fetch user {idx}: {fetch_user_config.user_id}")

                fetch_user_configs.append(fetch_user_config)
            except Exception as e:
                logger.warning(f"Failed to load fetch user from {fetch_user_file}: {e}")

        if not fetch_user_configs:
            raise ValueError("No valid fetch user configurations loaded")

    if fetch_user_configs:
        system_type = "ATRAD" if is_atrad_fetch else "TMS"
        logger.info(f"Total {system_type} fetch users loaded: {len(fetch_user_configs)}")

    return fetch_user_configs, is_atrad_fetch


def load_trader_config(config_path: str, role: str):
    """
    Load trader configuration (seller or buyer) from JSON file.
    Auto-detects whether it's a TMS or ATRAD user.

    Args:
        config_path: Path to user config JSON
        role: "seller" or "buyer" (for logging)

    Returns:
        UserConfig or ATRADUserConfig instance
    """
    import json
    from pathlib import Path

    logger.info(f"Loading {role} configuration from {config_path}")

    # Read the config file to detect system type
    path = Path(config_path)
    with open(path, 'r') as f:
        config_data = json.load(f)

    # Detect system type
    system_type = detect_system_from_config(config_data)

    # Load appropriate config class
    if system_type == 'atrad':
        user_config = ATRADUserConfig.from_file(config_path)
        logger.info(f"Loaded ATRAD {role} configuration: {user_config.user_id}")
    else:
        user_config = UserConfig.from_file(config_path)
        logger.info(f"Loaded TMS {role} configuration: {user_config.user_id}")

    return user_config


def execute_order_for_user(
    user_config,  # UserConfig or ATRADUserConfig
    order_params: Dict[str, Any],
    scheduled_time: str = None,
    fetch_user_configs = None,  # List[UserConfig] or List[ATRADUserConfig]
    is_atrad_fetch: bool = False
) -> Dict[str, Any]:
    """
    Execute an order for a single user (supports both TMS and ATRAD).

    Args:
        user_config: UserConfig or ATRADUserConfig instance
        order_params: Order parameters dictionary
        scheduled_time: Optional scheduled time string
        fetch_user_configs: Optional list of fetch user configurations for trigger mode
        is_atrad_fetch: Whether fetch users are ATRAD users (default: False = TMS)

    Returns:
        API response dictionary
    """
    user_id = user_config.user_id

    try:
        logger.info(f"[{user_id}] Starting order execution")

        # Detect if this is ATRAD or TMS user
        is_atrad = isinstance(user_config, ATRADUserConfig)

        # Create fetch clients if provided
        fetch_clients = None
        if fetch_user_configs:
            if is_atrad_fetch:
                # Create ATRAD fetch clients
                fetch_clients = [ATRADClient(cfg) for cfg in fetch_user_configs]
                if len(fetch_clients) == 1:
                    logger.info(f"[{user_id}] ATRAD fetch client initialized: {fetch_user_configs[0].user_id}")
                else:
                    user_ids = ', '.join(cfg.user_id for cfg in fetch_user_configs)
                    logger.info(f"[{user_id}] Multi-user ATRAD fetch initialized: {len(fetch_clients)} users ({user_ids})")
            else:
                # Create TMS fetch clients
                fetch_clients = [TMSClient(cfg) for cfg in fetch_user_configs]
                if len(fetch_clients) == 1:
                    logger.info(f"[{user_id}] TMS fetch client initialized: {fetch_user_configs[0].user_id}")
                else:
                    user_ids = ', '.join(cfg.user_id for cfg in fetch_user_configs)
                    logger.info(f"[{user_id}] Multi-user TMS fetch initialized: {len(fetch_clients)} users ({user_ids})")

        if is_atrad:
            # ATRAD user - create ATRAD client and service
            logger.info(f"[{user_id}] Using ATRAD system")
            order_client = ATRADClient(user_config)
            # Create ATRAD order service
            order_service = ATRADOrderService(order_client)

        else:
            # TMS user - create TMS client and service
            logger.info(f"[{user_id}] Using TMS system")
            order_client = TMSClient(user_config)
            # Create TMS order service
            order_service = OrderService(order_client)

        # Execute order
        if scheduled_time:
            result = OrderScheduler.schedule_order(
                time_str=scheduled_time,
                order_func=order_service.execute_order,
                main_client=order_client,
                fetch_clients=fetch_clients,
                user_id=user_id,
                **order_params
            )
        else:
            # Immediate execution
            result = order_service.execute_order(fetch_clients=fetch_clients, **order_params)

        logger.info(f"[{user_id}] Order execution completed successfully")
        return result

    except Exception as e:
        logger.error(f"[{user_id}] Order execution failed: {str(e)}", exc_info=True)
        raise


def execute_multi_queue_group(
    user_config,  # UserConfig or ATRADUserConfig
    orders: List[Dict[str, Any]],
    order_store,
    fetch_user_configs = None,  # List[UserConfig] or List[ATRADUserConfig]
    is_atrad_fetch: bool = False
) -> Dict[str, Any]:
    """
    Execute a multi-queue order group.

    Args:
        user_config: Main user configuration
        orders: List of orders in the multi-queue group
        order_store: OrderStore instance
        fetch_user_configs: List of fetch user configurations
        is_atrad_fetch: True if using ATRAD fetch clients

    Returns:
        Last order response
    """

    logger.info(f"Preparing multi-queue execution for {len(orders)} orders:")
    for order in orders:
        logger.info(f"  - {order['id']} ({order['ticker']})")

    # Create main client
    if hasattr(user_config, 'atrad_base_url'):
        # ATRAD
        main_client = ATRADClient(user_config)
        order_service = ATRADOrderService(main_client)
    else:
        # TMS
        main_client = TMSClient(user_config)
        order_service = OrderService(main_client)

    # Create fetch clients
    if not fetch_user_configs:
        raise ValueError("Fetch user configs required for multi-queue mode")

    fetch_clients = []
    for fetch_config in fetch_user_configs:
        if is_atrad_fetch:
            fetch_clients.append(ATRADClient(fetch_config))
        else:
            fetch_clients.append(TMSClient(fetch_config))

    # Resolve tickers and add to orders
    from utils import get_ticker_store
    ticker_store = get_ticker_store()

    for order in orders:
        try:
            security_id, exchange_security_id = ticker_store.lookup(order['ticker'])

            # Get fetch_id
            fetch_host = None
            if fetch_user_configs and not is_atrad_fetch:
                fetch_host = fetch_user_configs[0].tms_host

            fetch_id = ticker_store.get_fetch_id(order['ticker'], host=fetch_host)

            # Add resolved IDs to order
            order['security_id'] = security_id
            order['exchange_security_id'] = exchange_security_id
            order['fetch_id'] = fetch_id
            order['symbol'] = order['ticker'].upper()

            logger.info(
                f"  {order['id']}: security_id={security_id}, "
                f"exchange_security_id={exchange_security_id}, fetch_id={fetch_id}"
            )

        except Exception as e:
            raise ValueError(f"Ticker lookup failed for '{order['ticker']}': {e}")

    # Check if any order has a scheduled time (use first order's time for the group)
    scheduled_time = orders[0].get('time') if orders else None

    # Warn if orders have different time values
    if scheduled_time:
        different_times = [order['id'] for order in orders if order.get('time') != scheduled_time]
        if different_times:
            logger.warning(
                f"Multi-queue group has orders with different scheduled times. "
                f"Using first order's time ({scheduled_time}). "
                f"Orders with different times: {', '.join(different_times)}"
            )
        logger.info(f"Multi-queue group has scheduled time: {scheduled_time}")
        logger.info(f"All orders in this group will execute at: {scheduled_time}")

    # Execute multi-queue
    try:
        if scheduled_time:
            # Scheduled execution using OrderScheduler
            def execute_multi_queue(**kwargs):
                """Wrapper function for scheduled multi-queue execution."""
                # Use fetch_clients from kwargs if provided (refreshed by scheduler)
                # Otherwise use the ones we created
                active_fetch_clients = kwargs.get('fetch_clients', fetch_clients)
                return order_service._execute_multi_queue_ipo_trigger(
                    orders=orders,
                    fetch_clients=active_fetch_clients
                )

            # Use OrderScheduler to schedule multi-queue execution
            responses = OrderScheduler.schedule_order(
                time_str=scheduled_time,
                order_func=execute_multi_queue,
                main_client=main_client,
                fetch_clients=fetch_clients,
                user_id=user_config.user_id
            )

            # Ensure responses is a list (multi-queue returns list)
            if not isinstance(responses, list):
                responses = [responses] if responses else []
        else:
            # Immediate execution
            responses = order_service._execute_multi_queue_ipo_trigger(
                orders=orders,
                fetch_clients=fetch_clients
            )

        # Mark all orders as successful
        for order in orders:
            order_store.mark_success(order['id'])
            logger.info(f"Order '{order['id']}' marked as successful in store")

        logger.info(f"Multi-queue group completed successfully")
        return responses[-1] if responses else None

    except Exception as e:
        logger.error(f"Multi-queue execution failed: {str(e)}")
        raise


def execute_from_order_store(
    user_config,  # UserConfig or ATRADUserConfig
    order_store_path: str,
    fetch_user_configs = None,  # List[UserConfig] or List[ATRADUserConfig]
    is_atrad_fetch: bool = False
) -> Dict[str, Any]:
    """
    Execute orders from the order store queue.
    Multiple orders with execute=true are executed sequentially based on queue_id.

    Args:
        user_config: UserConfig or ATRADUserConfig instance
        order_store_path: Path to order store JSON file
        fetch_user_configs: Optional list of fetch user configurations for trigger mode
        is_atrad_fetch: Whether fetch users are ATRAD users (default: False = TMS)

    Returns:
        API response dictionary from the last executed order

    Raises:
        ValueError: If no order to execute or validation fails
    """
    # Load order store
    logger.info(f"Loading order store from {order_store_path}")
    order_store = OrderStore(order_store_path)

    # Display order summary
    logger.info("\n" + order_store.get_order_summary())

    # Get all executable orders (sorted by queue_id)
    orders = order_store.get_executable_orders()

    if not orders:
        raise ValueError("No orders marked for execution in order store")

    logger.info(f"Found {len(orders)} order(s) in execution queue")
    logger.info("="*70)

    last_result = None

    # Group orders by queue_id and multi_queue status
    from collections import defaultdict
    queue_groups = defaultdict(list)
    for order in orders:
        validated_order = order_store.validate_order(order)
        queue_id = validated_order['queue_id']
        queue_groups[queue_id].append(validated_order)

    # Execute each queue group
    total_executed = 0
    for queue_id in sorted(queue_groups.keys()):
        group_orders = queue_groups[queue_id]

        # Check if this is a multi_queue group
        is_multi_queue = group_orders[0].get('multi_queue', False)

        if is_multi_queue and len(group_orders) > 1:
            # Multi-queue mode: execute all orders in this group concurrently
            logger.info(f"")
            logger.info(f"Queue {queue_id}: MULTI-QUEUE MODE ({len(group_orders)} orders)")
            logger.info("="*70)

            try:
                # Execute multi-queue group
                last_result = execute_multi_queue_group(
                    user_config=user_config,
                    orders=group_orders,
                    order_store=order_store,
                    fetch_user_configs=fetch_user_configs,
                    is_atrad_fetch=is_atrad_fetch
                )
                total_executed += len(group_orders)

            except Exception as e:
                logger.error(f"Multi-queue group (Queue {queue_id}) failed: {str(e)}")
                # Mark all orders in group as failed
                for order in group_orders:
                    order_store.mark_failed(order['id'])
                # Continue to next queue group
                logger.warning(f"Continuing to next queue group despite failure...")
                continue

        else:
            # Normal mode: execute orders sequentially
            for idx, order in enumerate(group_orders, 1):
                # Order already validated in grouping phase
                order_id = order['id']
                total_executed += 1

                logger.info(f"Executing order {total_executed}/{len(orders)} (Queue ID: {queue_id}): {order_id}")
            logger.info("="*70)

            # Resolve ticker to IDs
            try:
                from utils import get_ticker_store
                ticker_store = get_ticker_store()
                security_id, exchange_security_id = ticker_store.lookup(order['ticker'])

                # Get fetch_id with host-specific lookup if fetch_user is available (TMS only)
                fetch_host = None
                if fetch_user_configs and not is_atrad_fetch:
                    # Only TMS users have tms_host attribute
                    fetch_host = fetch_user_configs[0].tms_host

                fetch_id = ticker_store.get_fetch_id(order['ticker'], host=fetch_host)

                logger.info(
                    f"Ticker '{order['ticker']}' resolved to "
                    f"security_id={security_id}, exchange_security_id={exchange_security_id}, fetch_id={fetch_id}"
                )
                if fetch_host:
                    logger.debug(f"Fetch ID resolved for host: {fetch_host}")

            except (FileNotFoundError, ValueError) as e:
                order_store.mark_failed(order_id)
                raise ValueError(f"Ticker lookup failed for '{order['ticker']}': {e}")

            # Determine mode flags
            ipo_trigger_mode = order['mode'] == 'ipo-trigger'
            trigger_sell_mode = order['mode'] == 'trigger-sell'
            ipo_sell_buy_trigger_mode = order['mode'] == 'ipo-sell-buy-trigger'
            buy_or_sell = 2 if order['sell'] else 1

            # Validate fetch_user requirement for trigger modes
            if ipo_trigger_mode and not fetch_user_configs:
                order_store.mark_failed(order_id)
                raise ValueError(
                    "Fetch user configuration is required for 'ipo-trigger' mode. "
                    "Use --fetch-user or --fetch-users argument to specify fetch user JSON file(s)."
                )

            if trigger_sell_mode and not fetch_user_configs:
                order_store.mark_failed(order_id)
                raise ValueError(
                    "Fetch user configuration is required for 'trigger-sell' mode. "
                    "Use --fetch-user argument to specify fetch user JSON file."
                )

            if ipo_sell_buy_trigger_mode and not fetch_user_configs:
                order_store.mark_failed(order_id)
                raise ValueError(
                    "Fetch user configuration is required for 'ipo-sell-buy-trigger' mode. "
                    "Use --fetch-user or --fetch-users argument to specify fetch user JSON file(s)."
                )

            # Check if ipo-sell-buy-trigger mode - handle separately
            if ipo_sell_buy_trigger_mode:
                # Load seller and buyer configs
                seller_config = load_trader_config(order['seller_config'], "seller")
                buyer_config = load_trader_config(order['buyer_config'], "buyer")

                # Log execution details
                logger.info(f"Execution Mode: IPO-SELL-BUY-TRIGGER")
                logger.info(f"Seller: {seller_config.user_id}")
                logger.info(f"Buyer: {buyer_config.user_id}")
                logger.info(f"Ticker: {order['ticker']}")
                logger.info(f"Security ID: {security_id}")
                logger.info(f"Exchange Security ID: {exchange_security_id}")
                logger.info(f"Buy Price: {order['price']}, Buy Quantity: {order['quantity']}")
                logger.info(f"Sell Quantity: {order['sell_quantity']}")
                logger.info(f"Sell Pre-Wait: {order['sell_pre_wait_ms']}ms")
                if order['limit']:
                    logger.info(f"Limit: {order['limit']}")
                if order['time']:
                    logger.info(f"Scheduled Time: {order['time']}")
                logger.info(f"Token Refresh: {order['refresh_before']}s before execution")
                logger.info("="*70)

                try:
                    # Execute ipo-sell-buy-trigger mode
                    result = execute_ipo_sell_buy_trigger(
                        seller_config=seller_config,
                        buyer_config=buyer_config,
                        fetch_user_configs=fetch_user_configs,
                        is_atrad_fetch=is_atrad_fetch,
                        ticker=order['ticker'],
                        security_id=security_id,
                        exchange_security_id=exchange_security_id,
                        price=order['price'],
                        quantity=order['quantity'],
                        sell_quantity=order['sell_quantity'],
                        sell_pre_wait_ms=order['sell_pre_wait_ms'],
                        limit_price=order['limit'],
                        just_buy_interval_ms=order.get('just_buy_interval_ms', 100),
                        just_buy_timeout=order.get('just_buy_timeout', 5),
                        scheduled_time=order['time']
                    )

                    # Mark order as successful
                    order_store.mark_success(order_id)
                    logger.info(f"Order '{order_id}' marked as successful in store")
                    last_result = result

                except Exception as e:
                    order_store.mark_failed(order_id)
                    logger.error(f"Order '{order_id}' failed: {str(e)}")
                    # Continue with next order in queue instead of stopping
                    if idx < len(group_orders):
                        logger.warning(f"Continuing to next order in queue despite failure...")
                        logger.info("")
                    else:
                        raise

            else:
                # Standard order mode handling
                # Prepare order parameters
                order_params = {
                    'security_id': security_id,
                    'exchange_security_id': exchange_security_id,
                    'order_price': order['price'],
                    'order_quantity': order['quantity'],
                    'buy_or_sell': buy_or_sell,
                    'order_type': None,  # Use defaults from user config
                    'order_validity': None,
                    'ipo_trigger_mode': ipo_trigger_mode,
                    'trigger_sell_mode': trigger_sell_mode,
                    'limit_price': order['limit'],
                    'skip_first': order['skip_first'],
                    'skip_second_last': order['skip_second_last'],
                    'no_ladder': order['no_ladder'],
                    'fetch_id': fetch_id,
                    'base_quantity': order['base_quantity'],
                    'ticker': order['ticker'],  # Pass ticker for per-user fetch_id resolution
                    'double_buy': order['double_buy'],
                    'double_buy_quantity': order['double_buy_quantity'],
                    'just_buy': order.get('just_buy', False),
                    'just_buy_interval_ms': order.get('just_buy_interval_ms', 100),
                    'just_buy_timeout': order.get('just_buy_timeout', 5),
                    'just_buy_pre_wait_ms': order.get('just_buy_pre_wait_ms', 0),
                    'just_buy_max_requests': order.get('just_buy_max_requests'),
                    'just_buy_fade_interval_ms': order.get('just_buy_fade_interval_ms'),
                    'just_buy_fade_timeout': order.get('just_buy_fade_timeout'),
                    'symbol': order['ticker'].upper()
                }

                # Log execution details
                mode_str = order['mode'].upper()
                logger.info(f"Execution Mode: {mode_str}")
                logger.info(f"User: {user_config.user_id}")
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
                logger.info("="*70)

                try:
                    # Execute order
                    result = execute_order_for_user(
                        user_config=user_config,
                        order_params=order_params,
                        scheduled_time=order['time'],
                        fetch_user_configs=fetch_user_configs,
                        is_atrad_fetch=is_atrad_fetch
                    )

                    # Mark order as successful
                    order_store.mark_success(order_id)
                    logger.info(f"Order '{order_id}' marked as successful in store")
                    last_result = result

                except Exception as e:
                    order_store.mark_failed(order_id)
                    logger.error(f"Order '{order_id}' failed: {str(e)}")
                    # Continue with next order in queue instead of stopping
                    if idx < len(group_orders):
                        logger.warning(f"Continuing to next order in queue despite failure...")
                        logger.info("")
                    else:
                        raise

            # If there are more orders in queue, add a small delay before next order
            if idx < len(group_orders):
                logger.info(f"Order {idx}/{len(group_orders)} completed. Proceeding to next order in queue...")
                logger.info("")

    # All orders in queue completed
    logger.info("="*70)
    logger.info(f"Queue execution completed: {len(orders)} order(s) processed")
    logger.info("="*70)
    return last_result


def execute_ipo_sell_buy_trigger(
    seller_config,
    buyer_config,
    fetch_user_configs: List[Any],
    is_atrad_fetch: bool,
    ticker: str,
    security_id: int,
    exchange_security_id: int,
    price: float,
    quantity: int,
    sell_quantity: int,
    sell_pre_wait_ms: int,
    limit_price: Optional[float] = None,
    just_buy_interval_ms: int = 100,
    just_buy_timeout: int = 5,
    scheduled_time: str = None
) -> Dict[str, Any]:
    """
    Execute IPO sell-buy-trigger mode.

    Flow:
    1. Initialize seller and buyer service instances
    2. Calculate ladder for the stock
    3. Start price fetcher monitoring
    4. Wait for LTP >= third last level
    5. Start sell_pre_wait_ms timer
    6. At timer-100ms: Start spawning buy threads (just-buy style)
    7. At timer expiry: Place sell order (separate thread with retry)
    8. Exit when buy succeeds OR just_buy_limit reached

    Args:
        seller_config: Seller user configuration
        buyer_config: Buyer user configuration
        fetch_user_configs: List of fetch user configs
        is_atrad_fetch: True if fetch users are ATRAD
        ticker: Ticker symbol
        security_id: Security ID for TMS
        exchange_security_id: Exchange security ID for TMS
        price: Base price
        quantity: Buy quantity
        sell_quantity: Sell quantity
        sell_pre_wait_ms: Wait time before sell (ms)
        limit_price: Upper limit price
        just_buy_interval_ms: Buy thread spawn interval
        just_buy_timeout: Buy thread total duration
        scheduled_time: Optional scheduled time string (HH:MM or HH:MM:SS)

    Returns:
        Response dictionary
    """

    logger.info("="*70)
    logger.info("IPO SELL-BUY-TRIGGER MODE")
    logger.info("="*70)

    # Detect platform types
    is_seller_atrad = isinstance(seller_config, ATRADUserConfig)
    is_buyer_atrad = isinstance(buyer_config, ATRADUserConfig)

    logger.info(f"Seller: {seller_config.user_id} ({'ATRAD' if is_seller_atrad else 'TMS'})")
    logger.info(f"Buyer: {buyer_config.user_id} ({'ATRAD' if is_buyer_atrad else 'TMS'})")
    logger.info(f"Stock: {ticker}, Price: Rs. {price}, Limit: {limit_price or 'None'}")
    logger.info(f"Buy Quantity: {quantity}, Sell Quantity: {sell_quantity}")
    logger.info(f"Sell Pre-Wait: {sell_pre_wait_ms}ms")

    # Warn if same user
    if seller_config.user_id == buyer_config.user_id:
        logger.warning(
            f"Seller and buyer are the same user: {seller_config.user_id}. "
            f"This is allowed but may have account limitations."
        )

    # Create clients and fetch_clients list
    fetch_clients = []
    for fetch_config in fetch_user_configs:
        if is_atrad_fetch:
            fetch_clients.append(ATRADClient(fetch_config))
        else:
            fetch_clients.append(TMSClient(fetch_config))

    # Create seller service
    if is_seller_atrad:
        seller_client = ATRADClient(seller_config)
        seller_service = ATRADOrderService(seller_client)
    else:
        seller_client = TMSClient(seller_config)
        seller_service = OrderService(seller_client)

    # Create buyer service
    if is_buyer_atrad:
        buyer_client = ATRADClient(buyer_config)
        buyer_service = ATRADOrderService(buyer_client)
    else:
        buyer_client = TMSClient(buyer_config)
        buyer_service = OrderService(buyer_client)

    # Prepare execution parameters
    exec_params = {
        'buyer_service': buyer_service,
        'ticker': ticker,
        'security_id': security_id,
        'exchange_security_id': exchange_security_id,
        'symbol': ticker.upper() if ticker else None,
        'base_price': price,
        'buy_quantity': quantity,
        'sell_quantity': sell_quantity,
        'sell_pre_wait_ms': sell_pre_wait_ms,
        'limit_price': limit_price,
        'just_buy_interval_ms': just_buy_interval_ms,
        'just_buy_timeout': just_buy_timeout
    }

    # Execute with scheduling if time specified
    if scheduled_time:
        return OrderScheduler.schedule_order_sell_buy(
            time_str=scheduled_time,
            order_func=seller_service._execute_ipo_sell_buy_trigger,
            seller_client=seller_client,
            buyer_client=buyer_client,
            fetch_clients=fetch_clients,
            user_id=seller_config.user_id,
            **exec_params
        )
    else:
        # Immediate execution - delegate to service layer
        return seller_service._execute_ipo_sell_buy_trigger(fetch_clients=fetch_clients,**exec_params)


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
        logger.info("NEPSE TMS Order Automation Bot")
        logger.info("="*60)

        # Validate arguments
        validate_args(args)

        # Load user configuration
        user_config = load_user_config(args)

        # Load fetch user configurations if provided
        fetch_user_configs, is_atrad_fetch = load_fetch_user_configs(args)

        # For backward compatibility, keep fetch_user_config as the first fetch user
        fetch_user_config = fetch_user_configs[0] if fetch_user_configs else None

        # Check if using order store mode
        if args.order_store:
            # Order store mode
            execute_from_order_store(user_config, args.order_store, fetch_user_configs, is_atrad_fetch)
        else:
            # Check for ipo-sell-buy-trigger mode
            if args.ipo_sell_buy_trigger:
                # Load seller and buyer configs
                seller_config = load_trader_config(args.seller, "seller")
                buyer_config = load_trader_config(args.buyer, "buyer")

                # Execute ipo-sell-buy-trigger mode
                execute_ipo_sell_buy_trigger(
                    seller_config=seller_config,
                    buyer_config=buyer_config,
                    fetch_user_configs=fetch_user_configs,
                    is_atrad_fetch=is_atrad_fetch,
                    ticker=args.ticker,
                    security_id=args.security_id,
                    exchange_security_id=args.exchange_security_id,
                    price=args.price,
                    quantity=args.quantity,
                    sell_quantity=args.sell_quantity,
                    sell_pre_wait_ms=args.sell_pre_wait_ms,
                    limit_price=args.limit,
                    just_buy_interval_ms=getattr(args, 'just_buy_interval', 100),
                    just_buy_timeout=getattr(args, 'just_buy_timeout', 5),
                    scheduled_time=args.time
                )
            else:
                # Standard manual order mode
                # Determine buy or sell
                buy_or_sell = 2 if args.sell else 1

                # For multi-user fetch, we'll pass the ticker and let order_service resolve fetch_id per user
                # For backward compatibility with single user, we still resolve it here
                fetch_id = None
                ticker_symbol = None
                if args.ticker:
                    ticker_symbol = args.ticker.upper()
                    # Resolve fetch_id for logging purposes (using first fetch user's host if available, TMS only)
                    try:
                        from utils import get_ticker_store
                        ticker_store = get_ticker_store()

                        # Only TMS users have tms_host attribute
                        fetch_host = None
                        if fetch_user_config and not is_atrad_fetch:
                            fetch_host = fetch_user_config.tms_host

                        fetch_id = ticker_store.get_fetch_id(args.ticker, host=fetch_host)
                        logger.info(f"Fetch ID for '{args.ticker}': {fetch_id}")
                        if fetch_host:
                            logger.debug(f"Fetch ID resolved for host: {fetch_host}")
                    except Exception as e:
                        logger.warning(f"Could not resolve fetch_id for ticker '{args.ticker}': {e}")

                # Prepare order parameters (shared across all users)
                order_params = {
                    'security_id': args.security_id,
                    'exchange_security_id': args.exchange_security_id,
                    'order_price': args.price,
                    'order_quantity': args.quantity,
                    'buy_or_sell': buy_or_sell,
                    'order_type': args.order_type,
                    'order_validity': args.order_validity,
                    'ipo_trigger_mode': args.ipo_trigger,
                    'trigger_sell_mode': args.trigger_sell,
                    'limit_price': args.limit,
                    'skip_first': args.skip_first if hasattr(args, 'skip_first') else False,
                    'fetch_id': fetch_id,
                    'ticker': ticker_symbol,  # Pass ticker for per-user fetch_id resolution
                    'double_buy': args.double_buy if hasattr(args, 'double_buy') else False,
                    'double_buy_quantity': args.double_buy_quantity if hasattr(args, 'double_buy_quantity') else None,
                    'just_buy': args.just_buy if hasattr(args, 'just_buy') else False,
                    'just_buy_interval_ms': args.just_buy_interval if hasattr(args, 'just_buy_interval') else 100,
                    'just_buy_timeout': args.just_buy_timeout if hasattr(args, 'just_buy_timeout') else 5,
                    'just_buy_pre_wait_ms': args.just_buy_pre_wait if hasattr(args, 'just_buy_pre_wait') else 0,
                    'symbol': ticker_symbol
                }

                # Log execution mode
                mode = "SCHEDULED" if args.time else "IMMEDIATE"
                if args.ipo_trigger:
                    mode += " (IPO TRIGGER)"
                elif args.trigger_sell:
                    mode += " (TRIGGER SELL)"

                logger.info(f"Execution Mode: {mode}")
                logger.info(f"User: {user_config.user_id}")
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

                # Execute order
                execute_order_for_user(
                    user_config=user_config,
                    order_params=order_params,
                    scheduled_time=args.time,
                    fetch_user_configs=fetch_user_configs,
                    is_atrad_fetch=is_atrad_fetch
                )

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
