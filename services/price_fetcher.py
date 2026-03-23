"""Price fetcher service for monitoring LTP in trigger mode."""

import time
import threading
from typing import Optional
from api import TMSClient
from utils.logger import get_logger

logger = get_logger(__name__)


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
