"""CLI parser and argument validation helpers."""

import argparse
import logging

from utils import validate_positive_integer, validate_positive_number


logger = logging.getLogger("main")


def create_parser() -> argparse.ArgumentParser:
    """Create and configure argument parser."""
    parser = argparse.ArgumentParser(
        description='NEPSE TMS Order Automation Bot',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  # Using order store (recommended - predefined orders)
  python main.py --user-config users/user1.json --order-store order_store.json
  python main.py --pool-users users/user1.json users/user2.json --order-store order_store.json

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

    parser.add_argument('--user-config', type=str, help='Path to user configuration JSON file')
    parser.add_argument('--pool-users', type=str, nargs='+', help='Paths to pooled user configuration JSON files. Order-store only; order.user_id selects the main user and the remaining users become fetch users.')
    order_mode = parser.add_mutually_exclusive_group(required=True)
    order_mode.add_argument('--order-store', type=str, help='Path to order store JSON file. Executes the order marked with execute=true')
    order_mode.add_argument('--ticker', type=str, help='Ticker symbol (e.g., NABIL, NICA) for manual order. Will auto-populate security-id and exchange-security-id from ticker store')
    order_mode.add_argument('--security-id', type=int, help='Security ID for manual order (required if not using --ticker or --order-store)')

    parser.add_argument('--exchange-security-id', type=int, help='Exchange security ID (required when using --security-id)')
    parser.add_argument('--price', type=float, help='Order price per unit (required for manual orders)')
    parser.add_argument('--quantity', type=int, help='Order quantity (number of units) (required for manual orders)')
    parser.add_argument('--time', type=str, help='Schedule order for specific time (format: HH:MM or HH:MM:SS). When used with --order-store, overrides the time of the first order in the queue.')
    parser.add_argument('--sell', action='store_true', help='Place a sell order (default is buy)')
    parser.add_argument('--order-type', type=str, help='Order type (default: LMT). Options: LMT, MKT, SL, etc.')
    parser.add_argument('--order-validity', type=str, help='Order validity (default: DAY). Options: DAY, IOC, etc.')
    parser.add_argument('--client-data', type=str, help='Path to JSON file with client data (optional)')
    parser.add_argument('--ipo-trigger', action='store_true', help='IPO trigger mode: monitor LTP and place ladder orders based on price levels. When LTP >= ladder[i], places order at ladder[i+1].')
    parser.add_argument('--ipo-trigger-low', action='store_true', help='IPO trigger low mode: monitor LTP and place order at lower prices. If price>=limit: trigger at -9%% and order at -10%% of price. If price<limit: trigger at -8%% and order at -9%% of limit.')
    parser.add_argument('--timeout-ipo-trigger-low', type=int, default=None, help='Timeout in seconds for IPO trigger low mode. If trigger condition not met within timeout, skip order and move on (default: no timeout)')
    parser.add_argument('--trigger-sell', action='store_true', help='Trigger sell mode: monitor LTP and place sell order when price drops to trigger level. Trigger price calculated as sell_price / 1.03 (floored to 1 decimal).')

    fetch_user_group = parser.add_mutually_exclusive_group()
    fetch_user_group.add_argument('--fetch-user', type=str, help='Path to single fetch user JSON file (required for --ipo-trigger). This user will be used to fetch LTP.')
    fetch_user_group.add_argument('--fetch-users', type=str, nargs='+', help='Paths to multiple fetch user JSON files for multi-user rotation. Reduces rate limiting during LTP monitoring.')
    parser.add_argument('--just-buy-users', type=str, nargs='+', help='Paths to order-user JSON files used for parallel just-buy submissions.')

    parser.add_argument('--atrad-fetch', action='store_true', help='Use ATRAD fetch users instead of TMS fetch users. Fetch users will use ATRAD client for LTP monitoring.')
    parser.add_argument('--skip-first', action='store_true', help='Skip the first ladder level in IPO trigger mode. Places first order when LTP reaches ladder[0], starting from ladder[1].')
    parser.add_argument('--limit', type=float, help='Upper limit price for IPO mode. Orders above +15 percent of this limit will be removed, and +15 percent of limit will be the final order')
    parser.add_argument('--log-level', type=str, default='INFO', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'], help='Logging level (default: INFO)')
    parser.add_argument('--double-buy', action='store_true', help='Enable double buy: place a second order 0.5s after first order succeeds')
    parser.add_argument('--double-buy-quantity', type=int, help='Quantity for the second order in double buy mode (defaults to same as --quantity if not specified)')
    parser.add_argument('--just-buy', action='store_true', help='Enable just buy mode (no_ladder only): Aggressively place orders when switch threshold is reached')
    parser.add_argument('--just-buy-interval', type=int, default=100, help='Interval between just buy order attempts in milliseconds (default: 100ms)')
    parser.add_argument('--just-buy-timeout', type=int, default=5, help='Total duration for just buy attempts in seconds (default: 5s)')
    parser.add_argument('--just-buy-pre-wait', type=int, default=0, help='Wait time in milliseconds after switch threshold before starting just buy (default: 0ms)')

    parser.add_argument('--ipo-sell-buy-trigger', action='store_true', help='IPO sell-buy-trigger mode: Coordinates sell and buy orders when third last level reached')
    parser.add_argument('--seller', type=str, help='Path to seller user JSON file (required for --ipo-sell-buy-trigger). Can be TMS or ATRAD user.')
    parser.add_argument('--buyer', type=str, help='Path to buyer user JSON file (required for --ipo-sell-buy-trigger). Can be TMS or ATRAD user.')
    parser.add_argument('--sell-quantity', type=int, help='Quantity for sell order in ipo-sell-buy-trigger mode (required for --ipo-sell-buy-trigger)')
    parser.add_argument('--sell-pre-wait-ms', type=int, default=5000, help='Wait time in milliseconds before starting buy/sell sequence after third last level reached (default: 5000ms)')
    return parser


def validate_args(args: argparse.Namespace):
    """Validate command-line arguments and resolve ticker if provided."""
    has_pool_users = bool(getattr(args, "pool_users", None))
    has_user_config = bool(getattr(args, "user_config", None))

    if has_pool_users:
        if not args.order_store:
            raise ValueError("--pool-users can only be used with --order-store")
        if has_user_config:
            raise ValueError("--pool-users cannot be used together with --user-config")
        if args.fetch_user or args.fetch_users:
            raise ValueError("--pool-users cannot be used together with --fetch-user or --fetch-users")
        if getattr(args, "atrad_fetch", False):
            raise ValueError("--pool-users cannot be used together with --atrad-fetch")
    elif not has_user_config:
        raise ValueError("--user-config is required unless using --pool-users with --order-store")

    if args.order_store:
        return

    if args.ticker:
        try:
            from utils import get_ticker_store
            ticker_store = get_ticker_store()
            security_id, exchange_security_id = ticker_store.lookup(args.ticker)
            args.security_id = security_id
            args.exchange_security_id = exchange_security_id
            logger.info(f"Ticker '{args.ticker}' resolved to security_id={security_id}, exchange_security_id={exchange_security_id}")
        except (FileNotFoundError, ValueError) as exc:
            raise ValueError(f"Ticker lookup failed: {exc}")
    elif not args.exchange_security_id:
        raise ValueError("--exchange-security-id is required when using --security-id")

    if not args.price:
        raise ValueError("--price is required for manual orders")
    if not args.quantity:
        raise ValueError("--quantity is required for manual orders")

    validate_positive_integer(args.security_id, 'security-id')
    validate_positive_integer(args.exchange_security_id, 'exchange-security-id')
    validate_positive_number(args.price, 'price')
    validate_positive_integer(args.quantity, 'quantity')

    mode_flags = [args.ipo_trigger, args.ipo_trigger_low, args.trigger_sell, args.ipo_sell_buy_trigger]
    mode_count = sum(1 for flag in mode_flags if flag)
    if mode_count > 1:
        raise ValueError(
            "Cannot use multiple mode flags together. "
            "Choose one: --ipo-trigger, --ipo-trigger-low, --trigger-sell, or --ipo-sell-buy-trigger"
        )

    has_fetch_user = args.fetch_user or args.fetch_users
    if args.ipo_trigger and not has_fetch_user:
        raise ValueError("--fetch-user or --fetch-users is required when using --ipo-trigger mode")
    if args.ipo_trigger_low and not has_fetch_user:
        raise ValueError("--fetch-user or --fetch-users is required when using --ipo-trigger-low mode")
    if args.trigger_sell and not has_fetch_user:
        raise ValueError("--fetch-user or --fetch-users is required when using --trigger-sell mode")

    if args.ipo_sell_buy_trigger:
        if not args.seller:
            raise ValueError("--seller is required when using --ipo-sell-buy-trigger mode")
        if not args.buyer:
            raise ValueError("--buyer is required when using --ipo-sell-buy-trigger mode")
        if not args.sell_quantity:
            raise ValueError("--sell-quantity is required when using --ipo-sell-buy-trigger mode")
        if not has_fetch_user:
            raise ValueError("--fetch-user or --fetch-users is required when using --ipo-sell-buy-trigger mode")
        validate_positive_integer(args.sell_quantity, 'sell-quantity')
        validate_positive_integer(args.sell_pre_wait_ms, 'sell-pre-wait-ms')

    if (args.seller or args.buyer) and not args.ipo_sell_buy_trigger:
        logger.warning("--seller/--buyer flags are only used with --ipo-sell-buy-trigger mode. They will be ignored.")
    if has_fetch_user and not (args.ipo_trigger or args.ipo_trigger_low or args.trigger_sell or args.ipo_sell_buy_trigger):
        logger.warning("--fetch-user/--fetch-users flag is only used with --ipo-trigger, --ipo-trigger-low, --trigger-sell, or --ipo-sell-buy-trigger mode. It will be ignored.")
    if args.skip_first and not args.ipo_trigger:
        logger.warning("--skip-first flag is only used with --ipo-trigger mode. It will be ignored.")
    if args.limit and not (args.ipo_trigger or args.ipo_trigger_low):
        logger.warning("--limit flag is only used with --ipo-trigger or --ipo-trigger-low mode. It will be ignored.")
    if args.limit:
        validate_positive_number(args.limit, 'limit')

    if args.double_buy_quantity and not args.double_buy:
        logger.warning("--double-buy-quantity is only used with --double-buy flag. It will be ignored.")
    if args.double_buy_quantity:
        validate_positive_integer(args.double_buy_quantity, 'double-buy-quantity')

    if hasattr(args, 'just_buy') and args.just_buy and not args.ipo_trigger:
        raise ValueError("--just-buy can only be used with --ipo-trigger mode")
    if getattr(args, "just_buy_users", None) and not getattr(args, "just_buy", False):
        raise ValueError("--just-buy-users can only be used together with --just-buy")
    if hasattr(args, 'just_buy_interval') and args.just_buy_interval:
        validate_positive_integer(args.just_buy_interval, 'just-buy-interval')
    if hasattr(args, 'just_buy_timeout') and args.just_buy_timeout:
        validate_positive_integer(args.just_buy_timeout, 'just-buy-timeout')
