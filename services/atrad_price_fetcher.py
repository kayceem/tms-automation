"""Price fetcher service for monitoring LTP in trigger mode."""

import time
import threading
from typing import Optional, List
from dataclasses import dataclass
from api import ATRADClient
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ATRADFetchUser:
    """Represents a fetch user with their own ATRAD client for LTP monitoring."""
    name: str
    client: ATRADClient
    symbol: str

    def __post_init__(self):
        """Validate the client."""
        if not isinstance(self.client, ATRADClient):
            raise ValueError(f"client must be an ATRADClient instance")


class ATRADPriceFetcher:
    """
    Service for continuously monitoring LTP using a dedicated fetch user.
    Handles automatic token refresh for the fetch user.
    """

    def __init__(self, fetch_client: ATRADClient, symbol: str, poll_interval_ms: int = 100):
        """
        Initialize price fetcher.

        Args:
            fetch_client: ATRADClient instance for the fetch user
            symbol: Symbol to monitor
            poll_interval_ms: Polling interval in milliseconds
        """
        self.fetch_client = fetch_client
        self.symbol = symbol
        self.poll_interval_ms = poll_interval_ms
        self.poll_interval_seconds = poll_interval_ms / 1000.0

        self._latest_ltp: Optional[float] = None
        self._running = False
        self._paused = False
        self._lock = threading.Lock()
        self._fetch_thread: Optional[threading.Thread] = None

        # Market details monitoring
        self._market_details_running = False
        self._market_details_thread: Optional[threading.Thread] = None

        logger.info(
            f"[{self.fetch_client.user_id}] ATRADPriceFetcher initialized for "
            f"symbol={self.symbol}, poll_interval={self.poll_interval_ms}ms"
        )

    def start(self):
        """Start the price fetching thread."""
        if self._running:
            logger.warning(f"[{self.fetch_client.user_id}] ATRADPriceFetcher already running")
            return

        self._running = True
        self._fetch_thread = threading.Thread(
            target=self._fetch_loop,
            name=f"ATRADPriceFetcher-{self.fetch_client.user_id}",
            daemon=True
        )
        self._fetch_thread.start()
        logger.info(f"[{self.fetch_client.user_id}] ATRADPriceFetcher started")

    def stop(self):
        """Stop the price fetching thread."""
        if not self._running:
            return

        self._running = False
        if self._fetch_thread:
            self._fetch_thread.join(timeout=5.0)
        logger.info(f"[{self.fetch_client.user_id}] ATRADPriceFetcher stopped")

    def get_latest_ltp(self) -> Optional[float]:
        """
        Get the latest LTP value (thread-safe).

        Returns:
            Latest LTP or None if not yet fetched
        """
        with self._lock:
            return self._latest_ltp

    def pause(self):
        """
        Pause LTP fetching (thread-safe).
        Fetch loop will stop fetching but continue running.
        """
        with self._lock:
            if not self._paused:
                self._paused = True
                logger.info(f"[{self.fetch_client.user_id}] ATRADPriceFetcher paused")

    def resume(self):
        """
        Resume LTP fetching (thread-safe).
        Fetch loop will continue fetching LTP.
        """
        with self._lock:
            if self._paused:
                self._paused = False
                logger.info(f"[{self.fetch_client.user_id}] ATRADPriceFetcher resumed")

    def start_market_details(self):
        """
        Start market details monitoring.
        Pauses LTP fetching and starts fetching market details (bid/ask data).
        """
        if self._market_details_running:
            logger.warning(f"[{self.fetch_client.user_id}] Market details monitoring already running")
            return

        # Pause LTP fetching
        self.pause()

        # Start market details thread
        self._market_details_running = True
        self._market_details_thread = threading.Thread(
            target=self._market_details_loop,
            name=f"ATRADMarketDetails-{self.fetch_client.user_id}",
            daemon=True
        )
        self._market_details_thread.start()
        logger.info(f"[{self.fetch_client.user_id}] Market details monitoring started")

    def stop_market_details(self):
        """
        Stop market details monitoring.
        Stops fetching market details and resumes LTP fetching.
        """
        if not self._market_details_running:
            return

        # Stop market details thread
        self._market_details_running = False
        if self._market_details_thread:
            self._market_details_thread.join(timeout=2.0)

        # Resume LTP fetching
        self.resume()
        logger.info(f"[{self.fetch_client.user_id}] Market details monitoring stopped")

    def _market_details_loop(self):
        """Main loop for fetching market details at regular intervals."""
        logger.info(
            f"[{self.fetch_client.user_id}] Starting market details loop "
            f"(interval={self.poll_interval_ms}ms)"
        )

        timeout = max(min(self.poll_interval_seconds * 4, 0.05), 0.02)
        sleep_duration = min((self.poll_interval_seconds * 2), 0.005)
        while self._market_details_running:
            try:
                # Fetch market details from client
                bid = self.fetch_client.get_market_details(self.symbol, timeout=timeout)

                if bid:
                    # Log bid data (splits and quantity)
                    logger.info(
                        f"[{self.fetch_client.user_id}] Market Details for {self.symbol}:"
                    )
                    splits = bid.get('splits', 'N/A')
                    qty = bid.get('qty', 'N/A')
                    price = bid.get('price', 'N/A')
                    logger.info(f"[{self.fetch_client.user_id}] Price={price}, Qty={qty}, Splits={splits}")

            except KeyboardInterrupt:
                logger.info(f"[{self.fetch_client.user_id}] Market details loop interrupted by user")
                break
            except Exception as e:
                logger.error(
                    f"[{self.fetch_client.user_id}] Error in market details loop: {str(e)}"
                )

            # Sleep for the configured interval
            try:
                time.sleep(sleep_duration)
            except KeyboardInterrupt:
                logger.info(f"[{self.fetch_client.user_id}] Market details loop interrupted by user")
                break

        logger.info(f"[{self.fetch_client.user_id}] Market details loop ended")

    def _fetch_loop(self):
        """Main loop for fetching LTP at regular intervals."""
        logger.info(
            f"[{self.fetch_client.user_id}] Starting fetch loop "
            f"(interval={self.poll_interval_ms}ms)"
        )

        # Set timeout to 4x poll interval to prevent blocking
        timeout = max(min(self.poll_interval_seconds * 4, 0.05), 0.02)

        while self._running:
            try:
                # Check if paused
                with self._lock:
                    is_paused = self._paused

                if not is_paused:
                    # Fetch LTP with timeout
                    ltp = self.fetch_client.get_ltp(self.symbol, timeout=timeout)

                    # Update latest value
                    if ltp is not None:
                        with self._lock:
                            self._latest_ltp = ltp
                    else:
                        logger.debug(
                            f"[{self.fetch_client.user_id}] LTP fetch returned None"
                        )

            except KeyboardInterrupt:
                logger.info(f"[{self.fetch_client.user_id}] Fetch loop interrupted by user")
                break
            except Exception as e:
                logger.error(
                    f"[{self.fetch_client.user_id}] Error in fetch loop: {str(e)}"
                )

            # Sleep for the configured interval
            try:
                time.sleep(self.poll_interval_seconds)
            except KeyboardInterrupt:
                logger.info(f"[{self.fetch_client.user_id}] Fetch loop interrupted by user")
                break

        logger.info(f"[{self.fetch_client.user_id}] Fetch loop ended")


class ATRADMultiUserPriceFetcher:
    """
    Service for continuously monitoring LTP using multiple fetch users with rotation.
    Rotates between users every N requests to avoid rate limiting while maintaining time coverage.
    Each fetch user can have a different symbol based on their host.
    """

    def __init__(self, fetch_users: List[ATRADFetchUser],
                 poll_interval_ms: int = 100, requests_per_user: int = 10,
                 enable_cooldown: bool = True):
        """
        Initialize multi-user price fetcher.

        Args:
            fetch_users: List of ATRADFetchUser instances (each with their own symbol)
            poll_interval_ms: Polling interval in milliseconds
            requests_per_user: Number of requests per user before rotating
            enable_cooldown: Whether to enable cooldown delays every 5 rotation cycles (default: True)
        """
        if not fetch_users:
            raise ValueError("At least one fetch user is required")

        self.fetch_users = fetch_users
        self._len_fetch_users = len(fetch_users)
        self.poll_interval_ms = poll_interval_ms
        self.poll_interval_seconds = poll_interval_ms / 1000.0
        self.delay = max(0.005, self.poll_interval_seconds / 2) 
        self.requests_per_user = requests_per_user
        self.enable_cooldown = enable_cooldown

        self._latest_ltp: Optional[float] = None
        self._running = False
        self._paused = False
        self._lock = threading.Lock()
        self._fetch_thread: Optional[threading.Thread] = None

        # User rotation state
        self._current_user_index = 0
        self._requests_with_current_user = 0
        self._rotation_cycles_completed = 0

        # Market details monitoring
        self._market_details_running = False
        self._market_details_thread: Optional[threading.Thread] = None

        user_info = ', '.join(f"{u.name}(sid={u.symbol})" for u in self.fetch_users)
        logger.info(
            f"ATRADMultiUserPriceFetcher initialized with {len(self.fetch_users)} users: {user_info}, "
            f"poll_interval={poll_interval_ms}ms, rotation={requests_per_user} requests/user"
        )

    def _get_next_user(self) -> ATRADFetchUser:
        """
        Get the next user in rotation.

        Returns:
            ATRADFetchUser object to use for the next request
        """
        # Check if we should rotate to next user
        if self._requests_with_current_user >= self.requests_per_user:
            self._current_user_index = (self._current_user_index + 1) % self._len_fetch_users
            self._requests_with_current_user = 0

            # Track when we complete a full rotation cycle (back to first user)
            if self._current_user_index == 0:
                self._rotation_cycles_completed += 1

        self._requests_with_current_user += 1
        return self.fetch_users[self._current_user_index]

    def _should_add_cooldown_delay(self) -> bool:
        """Check if we should add cooldown delay after every 5 rotation cycles."""
        return self._rotation_cycles_completed > (self._len_fetch_users * 4)

    def start(self):
        """Start the price fetching thread."""
        if self._running:
            logger.warning("ATRADMultiUserPriceFetcher already running")
            return

        self._running = True
        self._fetch_thread = threading.Thread(
            target=self._fetch_loop,
            name="ATRADMultiUserPriceFetcher",
            daemon=True
        )
        self._fetch_thread.start()
        logger.info("ATRADMultiUserPriceFetcher started")

    def stop(self):
        """Stop the price fetching thread."""
        if not self._running:
            return

        self._running = False
        if self._fetch_thread:
            self._fetch_thread.join(timeout=5.0)
        logger.info("ATRADMultiUserPriceFetcher stopped")

    def get_latest_ltp(self) -> Optional[float]:
        """
        Get the latest LTP value (thread-safe).

        Returns:
            Latest LTP or None if not yet fetched
        """
        with self._lock:
            return self._latest_ltp

    def update_poll_settings(self, poll_interval_ms: int, enable_cooldown: bool):
        """
        Update polling interval and cooldown setting dynamically (thread-safe).
        Used for dynamic polling optimization in no_ladder mode.

        Args:
            poll_interval_ms: New polling interval in milliseconds
            enable_cooldown: Whether to enable cooldown delays
        """
        with self._lock:
            self.poll_interval_ms = poll_interval_ms
            self.poll_interval_seconds = poll_interval_ms / 1000.0
            self.enable_cooldown = False
            self.delay = max(0.005, self.poll_interval_seconds / 2)

    def pause(self):
        """
        Pause LTP fetching (thread-safe).
        Fetch loop will stop fetching but continue running.
        """
        with self._lock:
            if not self._paused:
                self._paused = True
                logger.info("ATRADMultiUserPriceFetcher paused")

    def resume(self):
        """
        Resume LTP fetching (thread-safe).
        Fetch loop will continue fetching LTP.
        """
        with self._lock:
            if self._paused:
                self._paused = False
                logger.info("ATRADMultiUserPriceFetcher resumed")

    def start_market_details(self):
        """
        Start market details monitoring.
        Pauses LTP fetching and starts fetching market details (bid/ask data).
        """
        if self._market_details_running:
            logger.warning("ATRADMultiUserPriceFetcher market details monitoring already running")
            return

        # Pause LTP fetching
        self.pause()

        # Start market details thread
        self._market_details_running = True
        self._market_details_thread = threading.Thread(
            target=self._market_details_loop,
            name="ATRADMultiUserMarketDetails",
            daemon=True
        )
        self._market_details_thread.start()
        logger.info("ATRADMultiUserPriceFetcher market details monitoring started")

    def stop_market_details(self):
        """
        Stop market details monitoring.
        Stops fetching market details and resumes LTP fetching.
        """
        if not self._market_details_running:
            return

        # Stop market details thread
        self._market_details_running = False
        if self._market_details_thread:
            self._market_details_thread.join(timeout=2.0)

        # Resume LTP fetching
        self.resume()
        logger.info("ATRADMultiUserPriceFetcher market details monitoring stopped")

    def _market_details_loop(self):
        """Main loop for fetching market details at regular intervals with user rotation."""
        logger.info(
            f"Starting multi-user market details loop (interval={self.poll_interval_ms}ms, "
            f"rotation={self.requests_per_user} requests/user)"
        )

        timeout = max(min(self.poll_interval_seconds * 4, 0.05), 0.02)
        sleep_duration = min((self.poll_interval_seconds * 2), 0.005)

        while self._market_details_running:
            try:
                # Get next user in rotation
                current_user = self._get_next_user()

                # Fetch market details from client
                bid = current_user.client.get_market_details(current_user.symbol, timeout=timeout)
                if not bid:
                    logger.info(f"[{current_user.name}] Market Details for {current_user.symbol}: No data available")
                else:    
                    splits = bid.get('splits', 'N/A')
                    qty = bid.get('qty', 'N/A')
                    price = bid.get('price', 'N/A')
                    logger.info(f"[{current_user.name}] Price={price}, Qty={qty}, Splits={splits}")

            except KeyboardInterrupt:
                logger.info("Multi-user market details loop interrupted by user")
                break
            except Exception as e:
                logger.error(f"Error in multi-user market details loop: {str(e)}")

            # Sleep for the configured interval
            try:
                time.sleep(sleep_duration)
            except KeyboardInterrupt:
                logger.info("Multi-user market details loop interrupted by user")
                break

        logger.info("Multi-user market details loop ended")

    def _fetch_loop(self):
        """Main loop for fetching LTP at regular intervals with user rotation."""
        logger.info(
            f"Starting multi-user fetch loop (interval={self.poll_interval_ms}ms, "
            f"rotation={self.requests_per_user} requests/user)"
        )

        # Set timeout to 4x poll interval to prevent blocking
        timeout = max(min(self.poll_interval_seconds * 4, 0.05), 0.02)

        fetch_count = 0
        while self._running:
            try:
                # Check if paused
                with self._lock:
                    is_paused = self._paused

                if not is_paused:
                    fetch_count += 1

                    # Get the user for this request
                    current_user = self._get_next_user()

                    # Fetch LTP using the user's specific symbol with timeout
                    ltp = current_user.client.get_ltp(current_user.symbol, timeout=timeout)

                    # Update latest value
                    if ltp is not None:
                        with self._lock:
                            self._latest_ltp = ltp
                    else:
                        logger.debug(
                            f"[{current_user.name}] Fetch #{fetch_count}: LTP returned None (sid={current_user.symbol})"
                        )
                        time.sleep(self.delay)
                        continue

            except KeyboardInterrupt:
                logger.info("Multi-user fetch loop interrupted by user")
                break
            except Exception as e:
                logger.error(
                    f"[{current_user.name}] Error in fetch loop (fetch #{fetch_count}): {str(e)}"
                )
                time.sleep(self.delay)
                continue

            # Sleep for the configured interval
            try:
                time.sleep(self.poll_interval_seconds)

                # Add cooldown delay every 5 rotation cycles
                if self.enable_cooldown and self._should_add_cooldown_delay():
                    logger.debug(
                        f"Cooldown delay after {self._rotation_cycles_completed} rotation cycles"
                    )
                    time.sleep(self.poll_interval_seconds + self.delay)
                    if self._rotation_cycles_completed > (self._len_fetch_users * 5):
                        self._rotation_cycles_completed = 0
            except KeyboardInterrupt:
                logger.info("Multi-user fetch loop interrupted by user")
                break

        logger.info(f"Multi-user fetch loop ended (total fetches: {fetch_count})")
