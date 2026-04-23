#!/usr/bin/env python3
"""NEPSE TMS Order Automation Bot entrypoint."""

import sys

from app.cli import create_parser, validate_args
from app.config_loader import (
    load_fetch_user_configs,
    load_just_buy_user_configs,
    load_pool_user_config,
    load_trader_config,
    load_user_config,
)
from app.execution import (
    execute_from_order_store,
    execute_ipo_sell_buy_trigger,
    execute_manual_order,
    execute_multi_queue_group,
    execute_order_for_user,
)
from utils import setup_logger


logger = setup_logger(
    name='main',
    log_file='tms_automation.log',
    level=20,
    console_output=True
)


def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Setup logging with specified level
    log_level_map = {
        'DEBUG': 10,
        'INFO': 20,
        'WARNING': 30,
        'ERROR': 40,
    }
    log_level = log_level_map.get(args.log_level, 20)

    logger.setLevel(log_level)

    for handler in logger.handlers:
        handler.setLevel(log_level)
    
    try:
        logger.info("=" * 60)
        logger.info("NEPSE TMS Order Automation Bot")
        logger.info("=" * 60)

        validate_args(args)
        user_config = load_user_config(args)
        user_pool = load_pool_user_config(args)
        fetch_user_configs, is_atrad_fetch = load_fetch_user_configs(args)
        just_buy_user_configs = load_just_buy_user_configs(args)

        if args.order_store:
            execute_from_order_store(
                user_config,
                args.order_store,
                fetch_user_configs,
                just_buy_user_configs,
                is_atrad_fetch,
                args.time,
                user_pool=user_pool,
            )
        else:
            if args.ipo_sell_buy_trigger:
                seller_config = load_trader_config(args.seller, "seller")
                buyer_config = load_trader_config(args.buyer, "buyer")
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
                    scheduled_time=args.time,
                )
            else:
                execute_manual_order(
                    user_config=user_config,
                    args=args,
                    fetch_user_configs=fetch_user_configs,
                    is_atrad_fetch=is_atrad_fetch,
                    just_buy_user_configs=just_buy_user_configs,
                )

        logger.info("=" * 60)
        logger.info("All orders completed successfully!")
        logger.info("=" * 60)

    except KeyboardInterrupt:
        try:
            sys.stdout.write("=" * 60 + "\n")
            sys.stdout.write("Operation cancelled by user (Ctrl+C)\n")
            sys.stdout.write("=" * 60 + "\n")
            sys.stdout.flush()
        except KeyboardInterrupt:
            pass
        sys.exit(130)
    except ValueError as exc:
        logger.error(f"Configuration Error: {str(exc)}")
        sys.exit(1)
    except Exception as exc:
        logger.error(f"Error: {str(exc)}", exc_info=True)
        sys.exit(1)


if __name__ == '__main__':
    main()
