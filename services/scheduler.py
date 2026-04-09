"""Scheduler service for executing orders at specific times."""

import time
from datetime import datetime, timedelta
from typing import Callable, Dict, Any, List, Optional
from utils.logger import get_logger

logger = get_logger(__name__)


class OrderScheduler:
    """Scheduler for executing orders at specific times."""

    @staticmethod
    def parse_time(time_str: str) -> datetime:
        """
        Parse time string to datetime object.

        Args:
            time_str: Time in format HH:MM or HH:MM:SS

        Returns:
            datetime object for today at specified time

        Raises:
            ValueError: If time format is invalid
        """
        try:
            # Try parsing with seconds
            if time_str.count(':') == 2:
                time_obj = datetime.strptime(time_str, '%H:%M:%S').time()
            # Try parsing without seconds
            elif time_str.count(':') == 1:
                time_obj = datetime.strptime(time_str, '%H:%M').time()
            else:
                raise ValueError("Invalid time format")

            # Combine with today's date
            now = datetime.now()
            scheduled_time = datetime.combine(now.date(), time_obj)

            # If the time has already passed today, schedule for tomorrow
            if scheduled_time < now:
                scheduled_time += timedelta(days=1)

            return scheduled_time

        except ValueError as e:
            raise ValueError(
                f"Invalid time format '{time_str}'. "
                "Please use HH:MM or HH:MM:SS format (e.g., 14:30 or 14:30:00)"
            ) from e

    @staticmethod
    def wait_until(target_time: datetime, main_client=None, fetch_clients: Optional[List] = None, user_id: str = "unknown"):
        """
        Wait until the specified time, refreshing tokens 10 seconds before.

        Args:
            target_time: Target datetime to wait for
            main_client: Optional Client instance for token refresh
            fetch_clients: Optional list of fetch user Client instances for token refresh
            user_id: User identifier for logging
        """
        now = datetime.now()
        wait_seconds = (target_time - now).total_seconds()

        if wait_seconds <= 0:
            logger.warning(f"[{user_id}] Target time has already passed!")
            return

        logger.info(
            f"[{user_id}] Scheduled execution: "
            f"current={now.strftime('%Y-%m-%d %H:%M:%S')}, "
            f"target={target_time.strftime('%Y-%m-%d %H:%M:%S')}, "
            f"wait={int(wait_seconds)}s"
        )

        # Calculate when to refresh tokens
        refresh_time = target_time - timedelta(seconds=15)
        refresh_seconds = (refresh_time - datetime.now()).total_seconds()

        # If we have enough time, wait until refresh time
        if refresh_seconds > 0 and main_client:
            logger.info(
                f"[{user_id}] Token refresh scheduled for "
                f"{refresh_time.strftime('%H:%M:%S')} (15s before execution)"
            )
            try:
                time.sleep(refresh_seconds)
            except KeyboardInterrupt:
                logger.info(f"[{user_id}] Wait interrupted by user")
                raise

            # Refresh tokens for main client
            logger.info(f"[{user_id}] PRE-EXECUTION TOKEN REFRESH")
            logger.debug(
                f"[{user_id}] Current={datetime.now().strftime('%H:%M:%S')}, "
                f"Execution={target_time.strftime('%H:%M:%S')}"
            )

            success = main_client.refresh_tokens()
            if success:
                logger.info(f"[{user_id}] Main user tokens refreshed successfully")
            else:
                logger.warning(
                    f"[{user_id}] Main user token refresh failed, will attempt with current tokens"
                )

            # Refresh tokens for fetch users
            if fetch_clients:
                logger.info(f"[{user_id}] Refreshing tokens for {len(fetch_clients)} fetch user(s)")
                for i, fetch_client in enumerate(fetch_clients, 1):
                    fetch_user_id = getattr(fetch_client, 'user_id', f'FetchUser{i}')
                    try:
                        fetch_success = fetch_client.refresh_tokens()
                        if fetch_success:
                            logger.info(f"[{user_id}] Fetch user {fetch_user_id} tokens refreshed successfully")
                        else:
                            logger.warning(f"[{user_id}] Fetch user {fetch_user_id} token refresh failed")
                    except Exception as e:
                        logger.warning(f"[{user_id}] Fetch user {fetch_user_id} token refresh error: {str(e)}")

            # Update wait_seconds for final countdown
            wait_seconds = (target_time - datetime.now()).total_seconds()

        # Show countdown for last 10 seconds
        if wait_seconds > 10:
            logger.debug(f"[{user_id}] Sleeping for {int(wait_seconds - 10)}s until countdown")
            try:
                time.sleep(wait_seconds - 10)
            except KeyboardInterrupt:
                logger.info(f"[{user_id}] Wait interrupted by user")
                raise
            wait_seconds = 10

        # Countdown
        logger.debug(f"[{user_id}] Starting final countdown: {int(wait_seconds)}s")
        try:
            for i in range(int(wait_seconds), 0, -1):
                if i <= 5:  # Only log last 5 seconds
                    logger.debug(f"[{user_id}] Order execution in {i} seconds")
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info(f"[{user_id}] Countdown interrupted by user")
            raise

        logger.info(f"[{user_id}] Executing order now!")

    @classmethod
    def schedule_order(
        cls,
        time_str: str,
        order_func: Callable,
        main_client=None,
        fetch_clients: Optional[List] = None,
        user_id: str = "unknown",
        **order_params
    ) -> Dict[str, Any]:
        """
        Schedule an order to be executed at a specific time.
        Automatically refreshes tokens 10 seconds before execution.

        Args:
            time_str: Time string in HH:MM or HH:MM:SS format
            order_func: Function to execute (should be OrderService.execute_order)
            main_client: Optional Client instance for pre-execution token refresh
            fetch_clients: Optional list of fetch user Client instances for token refresh
            user_id: User identifier for logging
            **order_params: Parameters to pass to order_func

        Returns:
            Result from order_func
        """
        target_time = cls.parse_time(time_str)
        logger.info(f"[{user_id}] Order scheduled for {target_time.strftime('%Y-%m-%d %H:%M:%S')}")

        cls.wait_until(target_time, main_client=main_client, fetch_clients=fetch_clients, user_id=user_id)

        # Add fetch_clients back to order_params if it exists
        if fetch_clients is not None:
            order_params = {**order_params, 'fetch_clients': fetch_clients}

        return order_func(**order_params)

    @classmethod
    def schedule_order_sell_buy(
        cls,
        time_str: str,
        order_func: Callable,
        seller_client=None,
        buyer_client=None,
        fetch_clients: Optional[List] = None,
        user_id: str = "unknown",
        **order_params
    ) -> Dict[str, Any]:
        """
        Schedule an ipo-sell-buy-trigger order with two main clients (seller and buyer).
        Automatically refreshes tokens for seller, buyer, and fetch users before execution.

        Args:
            time_str: Time string in HH:MM or HH:MM:SS format
            order_func: Function to execute (should be service._execute_ipo_sell_buy_trigger)
            seller_client: Seller client instance for token refresh (TMS or ATRAD)
            buyer_client: Buyer client instance for token refresh (TMS or ATRAD)
            fetch_clients: List of fetch user client instances for token refresh (TMS or ATRAD)
            user_id: User identifier for logging
            **order_params: Parameters to pass to order_func

        Returns:
            Result from order_func
        """
        target_time = cls.parse_time(time_str)
        logger.info(f"[{user_id}] IPO-SELL-BUY-TRIGGER order scheduled for {target_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # Wait and refresh tokens
        now = datetime.now()
        wait_seconds = (target_time - now).total_seconds()

        if wait_seconds <= 0:
            logger.warning(f"[{user_id}] Target time has already passed!")
        else:
            logger.info(
                f"[{user_id}] Scheduled execution: "
                f"current={now.strftime('%Y-%m-%d %H:%M:%S')}, "
                f"target={target_time.strftime('%Y-%m-%d %H:%M:%S')}, "
                f"wait={int(wait_seconds)}s"
            )

            # Calculate when to refresh tokens
            refresh_time = target_time - timedelta(seconds=15)
            refresh_seconds = (refresh_time - datetime.now()).total_seconds()

            # If we have enough time, wait until refresh time
            if refresh_seconds > 0:
                logger.info(
                    f"[{user_id}] Token refresh scheduled for "
                    f"{refresh_time.strftime('%H:%M:%S')} (15s before execution)"
                )
                try:
                    time.sleep(refresh_seconds)
                except KeyboardInterrupt:
                    logger.info(f"[{user_id}] Wait interrupted by user")
                    raise

                # Refresh tokens for all clients
                logger.info(f"[{user_id}] PRE-EXECUTION TOKEN REFRESH")
                logger.debug(
                    f"[{user_id}] Current={datetime.now().strftime('%H:%M:%S')}, "
                    f"Execution={target_time.strftime('%H:%M:%S')}"
                )

                # Refresh seller tokens
                if seller_client:
                    seller_user_id = getattr(seller_client, 'user_id', 'Seller')
                    try:
                        # Check if client has refresh_tokens method (TMS clients)
                        if hasattr(seller_client, 'refresh_tokens'):
                            success = seller_client.refresh_tokens()
                            if success:
                                logger.info(f"[{user_id}] Seller ({seller_user_id}) tokens refreshed successfully")
                            else:
                                logger.warning(f"[{user_id}] Seller ({seller_user_id}) token refresh failed")
                        else:
                            # ATRAD client - no token refresh needed
                            logger.debug(f"[{user_id}] Seller ({seller_user_id}) is ATRAD - no token refresh needed")
                    except Exception as e:
                        logger.warning(f"[{user_id}] Seller ({seller_user_id}) token refresh error: {str(e)}")

                # Refresh buyer tokens
                if buyer_client:
                    buyer_user_id = getattr(buyer_client, 'user_id', 'Buyer')
                    try:
                        # Check if client has refresh_tokens method (TMS clients)
                        if hasattr(buyer_client, 'refresh_tokens'):
                            success = buyer_client.refresh_tokens()
                            if success:
                                logger.info(f"[{user_id}] Buyer ({buyer_user_id}) tokens refreshed successfully")
                            else:
                                logger.warning(f"[{user_id}] Buyer ({buyer_user_id}) token refresh failed")
                        else:
                            # ATRAD client - no token refresh needed
                            logger.debug(f"[{user_id}] Buyer ({buyer_user_id}) is ATRAD - no token refresh needed")
                    except Exception as e:
                        logger.warning(f"[{user_id}] Buyer ({buyer_user_id}) token refresh error: {str(e)}")

                # Refresh fetch users tokens
                if fetch_clients:
                    logger.info(f"[{user_id}] Refreshing tokens for {len(fetch_clients)} fetch user(s)")
                    for i, fetch_client in enumerate(fetch_clients, 1):
                        fetch_user_id = getattr(fetch_client, 'user_id', f'FetchUser{i}')
                        try:
                            # Check if client has refresh_tokens method (TMS clients)
                            if hasattr(fetch_client, 'refresh_tokens'):
                                fetch_success = fetch_client.refresh_tokens()
                                if fetch_success:
                                    logger.info(f"[{user_id}] Fetch user {fetch_user_id} tokens refreshed successfully")
                                else:
                                    logger.warning(f"[{user_id}] Fetch user {fetch_user_id} token refresh failed")
                            else:
                                # ATRAD client - no token refresh needed
                                logger.debug(f"[{user_id}] Fetch user {fetch_user_id} is ATRAD - no token refresh needed")
                        except Exception as e:
                            logger.warning(f"[{user_id}] Fetch user {fetch_user_id} token refresh error: {str(e)}")

                # Update wait_seconds for final countdown
                wait_seconds = (target_time - datetime.now()).total_seconds()

            # Show countdown for last 10 seconds
            if wait_seconds > 10:
                logger.debug(f"[{user_id}] Sleeping for {int(wait_seconds - 10)}s until countdown")
                try:
                    time.sleep(wait_seconds - 10)
                except KeyboardInterrupt:
                    logger.info(f"[{user_id}] Wait interrupted by user")
                    raise
                wait_seconds = 10

            # Countdown
            logger.debug(f"[{user_id}] Starting final countdown: {int(wait_seconds)}s")
            try:
                for i in range(int(wait_seconds), 0, -1):
                    if i <= 5:  # Only log last 5 seconds
                        logger.debug(f"[{user_id}] Order execution in {i} seconds")
                    time.sleep(1)
            except KeyboardInterrupt:
                logger.info(f"[{user_id}] Countdown interrupted by user")
                raise

            logger.info(f"[{user_id}] Executing order now!")

        # Add fetch_clients back to order_params if it exists
        if fetch_clients is not None:
            order_params = {**order_params, 'fetch_clients': fetch_clients}

        return order_func(**order_params)
