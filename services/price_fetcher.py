"""Price fetcher service for monitoring LTP in trigger mode."""

import time
import threading
from typing import Optional, List
from dataclasses import dataclass
from api import TMSClient
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FetchUser:
    """Represents a fetch user with their own TMS client for LTP monitoring."""
    name: str
    client: TMSClient
    fetch_security_id: int  # Security ID for fetching LTP (can differ per host)

    def __post_init__(self):
        """Validate the client."""
        if not isinstance(self.client, TMSClient):
            raise ValueError(f"client must be a TMSClient instance")


class PriceFetcher:
    """
    Service for continuously monitoring LTP using a dedicated fetch user.
    Handles automatic token refresh for the fetch user.
    """

    def __init__(self, fetch_client: TMSClient, security_id: int, poll_interval_ms: int = 100):
        """
        Initialize price fetcher.

        Args:
            fetch_client: TMSClient instance for the fetch user
            security_id: Security ID to monitor
            poll_interval_ms: Polling interval in milliseconds
        """
        self.fetch_client = fetch_client
        self.security_id = security_id
        self.poll_interval_ms = poll_interval_ms
        self.poll_interval_seconds = poll_interval_ms / 1000.0

        self._latest_ltp: Optional[float] = None
        self._running = False
        self._lock = threading.Lock()
        self._fetch_thread: Optional[threading.Thread] = None

        logger.info(
            f"[{self.fetch_client.user_id}] PriceFetcher initialized for "
            f"security_id={security_id}, poll_interval={poll_interval_ms}ms"
        )

    def start(self):
        """Start the price fetching thread."""
        if self._running:
            logger.warning(f"[{self.fetch_client.user_id}] PriceFetcher already running")
            return

        self._running = True
        self._fetch_thread = threading.Thread(
            target=self._fetch_loop,
            name=f"PriceFetcher-{self.fetch_client.user_id}",
            daemon=True
        )
        self._fetch_thread.start()
        logger.info(f"[{self.fetch_client.user_id}] PriceFetcher started")

    def stop(self):
        """Stop the price fetching thread."""
        if not self._running:
            return

        self._running = False
        if self._fetch_thread:
            self._fetch_thread.join(timeout=5.0)
        logger.info(f"[{self.fetch_client.user_id}] PriceFetcher stopped")

    def get_latest_ltp(self) -> Optional[float]:
        """
        Get the latest LTP value (thread-safe).

        Returns:
            Latest LTP or None if not yet fetched
        """
        with self._lock:
            return self._latest_ltp

    def _fetch_loop(self):
        """Main loop for fetching LTP at regular intervals."""
        logger.info(
            f"[{self.fetch_client.user_id}] Starting fetch loop "
            f"(interval={self.poll_interval_ms}ms)"
        )

        while self._running:
            try:
                # Fetch LTP
                ltp = self.fetch_client.get_ltp(self.security_id)

                # Update latest value
                if ltp is not None:
                    with self._lock:
                        self._latest_ltp = ltp
                    logger.debug(
                        f"[{self.fetch_client.user_id}] Updated LTP: {ltp}"
                    )
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


class TokenRefreshManager:
    """
    Manager for periodically refreshing tokens to keep them active.
    Used in trigger mode to ensure the main user is ready immediately when orders need to be placed.
    """

    def __init__(self, tms_client: TMSClient, refresh_interval_seconds: int = 60):
        """
        Initialize token refresh manager.

        Args:
            tms_client: TMSClient instance to refresh tokens for
            refresh_interval_seconds: How often to refresh tokens
        """
        self.tms_client = tms_client
        self.refresh_interval_seconds = refresh_interval_seconds

        self._running = False
        self._refresh_thread: Optional[threading.Thread] = None

        logger.info(
            f"[{self.tms_client.user_id}] TokenRefreshManager initialized "
            f"(interval={refresh_interval_seconds}s)"
        )

    def start(self):
        """Start the token refresh thread."""
        if self._running:
            logger.warning(f"[{self.tms_client.user_id}] TokenRefreshManager already running")
            return

        self._running = True
        self._refresh_thread = threading.Thread(
            target=self._refresh_loop,
            name=f"TokenRefresh-{self.tms_client.user_id}",
            daemon=True
        )
        self._refresh_thread.start()
        logger.info(f"[{self.tms_client.user_id}] TokenRefreshManager started")

    def stop(self):
        """Stop the token refresh thread."""
        if not self._running:
            return

        self._running = False
        if self._refresh_thread:
            self._refresh_thread.join(timeout=5.0)
        logger.info(f"[{self.tms_client.user_id}] TokenRefreshManager stopped")

    def _refresh_loop(self):
        """Main loop for refreshing tokens at regular intervals."""
        logger.info(
            f"[{self.tms_client.user_id}] Starting token refresh loop "
            f"(interval={self.refresh_interval_seconds}s)"
        )

        while self._running:
            try:
                # Sleep first, then refresh (don't refresh immediately on start)
                time.sleep(self.refresh_interval_seconds)

                if not self._running:
                    break

                # Refresh tokens
                logger.info(f"[{self.tms_client.user_id}] Performing scheduled token refresh")
                success = self.tms_client.refresh_tokens()

                if success:
                    logger.info(
                        f"[{self.tms_client.user_id}] Scheduled token refresh successful"
                    )
                else:
                    logger.warning(
                        f"[{self.tms_client.user_id}] Scheduled token refresh failed"
                    )

            except KeyboardInterrupt:
                logger.info(f"[{self.tms_client.user_id}] Refresh loop interrupted by user")
                break
            except Exception as e:
                logger.error(
                    f"[{self.tms_client.user_id}] Error in refresh loop: {str(e)}"
                )

        logger.info(f"[{self.tms_client.user_id}] Token refresh loop ended")


class MultiUserPriceFetcher:
    """
    Service for continuously monitoring LTP using multiple fetch users with rotation.
    Rotates between users every N requests to avoid rate limiting while maintaining time coverage.
    Each fetch user can have a different fetch_security_id based on their host.
    """

    def __init__(self, fetch_users: List[FetchUser],
                 poll_interval_ms: int = 100, requests_per_user: int = 10):
        """
        Initialize multi-user price fetcher.

        Args:
            fetch_users: List of FetchUser instances (each with their own fetch_security_id)
            poll_interval_ms: Polling interval in milliseconds
            requests_per_user: Number of requests per user before rotating
        """
        if not fetch_users:
            raise ValueError("At least one fetch user is required")

        self.fetch_users = fetch_users
        self.poll_interval_ms = poll_interval_ms
        self.poll_interval_seconds = poll_interval_ms / 1000.0
        self.requests_per_user = requests_per_user

        self._latest_ltp: Optional[float] = None
        self._running = False
        self._lock = threading.Lock()
        self._fetch_thread: Optional[threading.Thread] = None

        # User rotation state
        self._current_user_index = 0
        self._requests_with_current_user = 0
        self._rotation_cycles_completed = 0

        user_info = ', '.join(f"{u.name}(sid={u.fetch_security_id})" for u in self.fetch_users)
        logger.info(
            f"MultiUserPriceFetcher initialized with {len(self.fetch_users)} users: {user_info}, "
            f"poll_interval={poll_interval_ms}ms, rotation={requests_per_user} requests/user"
        )

    def _get_next_user(self) -> FetchUser:
        """
        Get the next user in rotation.

        Returns:
            FetchUser object to use for the next request
        """
        # Check if we should rotate to next user
        if self._requests_with_current_user >= self.requests_per_user:
            self._current_user_index = (self._current_user_index + 1) % len(self.fetch_users)
            self._requests_with_current_user = 0

            # Track when we complete a full rotation cycle (back to first user)
            if self._current_user_index == 0:
                self._rotation_cycles_completed += 1

        self._requests_with_current_user += 1
        return self.fetch_users[self._current_user_index]

    def _should_add_cooldown_delay(self) -> bool:
        """Check if we should add cooldown delay after every 5 rotation cycles."""
        return self._rotation_cycles_completed > 0 and self._rotation_cycles_completed % 2 == 0

    def start(self):
        """Start the price fetching thread."""
        if self._running:
            logger.warning("MultiUserPriceFetcher already running")
            return

        self._running = True
        self._fetch_thread = threading.Thread(
            target=self._fetch_loop,
            name="MultiUserPriceFetcher",
            daemon=True
        )
        self._fetch_thread.start()
        logger.info("MultiUserPriceFetcher started")

    def stop(self):
        """Stop the price fetching thread."""
        if not self._running:
            return

        self._running = False
        if self._fetch_thread:
            self._fetch_thread.join(timeout=5.0)
        logger.info("MultiUserPriceFetcher stopped")

    def get_latest_ltp(self) -> Optional[float]:
        """
        Get the latest LTP value (thread-safe).

        Returns:
            Latest LTP or None if not yet fetched
        """
        with self._lock:
            return self._latest_ltp

    def _fetch_loop(self):
        """Main loop for fetching LTP at regular intervals with user rotation."""
        logger.info(
            f"Starting multi-user fetch loop (interval={self.poll_interval_ms}ms, "
            f"rotation={self.requests_per_user} requests/user)"
        )

        fetch_count = 0
        while self._running:
            try:
                fetch_count += 1

                # Get the user for this request
                current_user = self._get_next_user()

                # Fetch LTP using the user's specific fetch_security_id
                ltp = current_user.client.get_ltp(current_user.fetch_security_id)

                # Update latest value
                if ltp is not None:
                    with self._lock:
                        self._latest_ltp = ltp
                    logger.debug(
                        f"[{current_user.name}] Fetch #{fetch_count}: LTP={ltp} (sid={current_user.fetch_security_id})"
                    )
                else:
                    logger.debug(
                        f"[{current_user.name}] Fetch #{fetch_count}: LTP returned None (sid={current_user.fetch_security_id})"
                    )

            except KeyboardInterrupt:
                logger.info("Multi-user fetch loop interrupted by user")
                break
            except Exception as e:
                logger.error(
                    f"[{current_user.name}] Error in fetch loop (fetch #{fetch_count}): {str(e)}"
                )

            # Sleep for the configured interval
            try:
                time.sleep(self.poll_interval_seconds)

                # Add cooldown delay every 5 rotation cycles
                if self._should_add_cooldown_delay():
                    logger.debug(
                        f"Cooldown delay after {self._rotation_cycles_completed} rotation cycles"
                    )
                    time.sleep(self.poll_interval_seconds / 2)
                    self._rotation_cycles_completed = 0  # Reset counter after cooldown
            except KeyboardInterrupt:
                logger.info("Multi-user fetch loop interrupted by user")
                break

        logger.info(f"Multi-user fetch loop ended (total fetches: {fetch_count})")
