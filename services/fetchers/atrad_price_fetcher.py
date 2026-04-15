"""Price fetcher service for monitoring LTP in trigger mode."""

from collections import deque
import json
import time
import threading
from typing import Literal, Optional, List
from dataclasses import dataclass
from api import ATRADClient
from services.fetchers.fetcher_timing import calculate_request_timeout, calculate_rotation_delay
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
            name=f"APfThread-{self.fetch_client.user_id}",
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
            name=f"AMdThread-{self.fetch_client.user_id}",
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

        timeout = calculate_request_timeout(self.poll_interval_seconds)
        sleep_duration = min((self.poll_interval_seconds * 2), 0.005)
        while self._market_details_running:
            try:
                # Fetch market details from client
                bid = self.fetch_client.get_market_details(self.symbol, timeout=timeout)

                if not bid:
                    logger.warning(f"[{self.fetch_client.user_id}] Market Details for {self.symbol}: No data available")
                else:
                    splits = bid.get('splits', 'N/A')
                    qty = bid.get('qty', 'N/A')
                    price = bid.get('price', 'N/A')
                    logger.debug(f"[{self.fetch_client.user_id}] Price={price}, Qty={qty}, Splits={splits}")

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
        timeout = calculate_request_timeout(self.poll_interval_seconds)

        while self._running:
            try:
                # Check if paused
                with self._lock:
                    is_paused = self._paused

                if not is_paused:
                    # Fetch LTP with timeout
                    ltp = self.fetch_client.get_ltp(self.symbol, timeout=timeout)

                    # Update latest value
                    if not ltp:
                        logger.warning(f"[{self.fetch_client.user_id}] LTP fetch returned None")
                    else:
                        with self._lock:
                            self._latest_ltp = ltp
                        logger.debug(f"[{self.fetch_client.user_id}] LTP={ltp})")

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
                 enable_cooldown: bool = True,
                 scheduler_mode: Literal["sequential", "parallel"] = "sequential",
                 parallel_fetch_enabled: bool = False,
                 parallel_spawn_interval_ms: int = 10,
                 parallel_cycle_timeout_ms: int = 20,
                 parallel_wait: bool = False):
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
        self.delay = calculate_rotation_delay(self.poll_interval_seconds, 0.005)
        self.requests_per_user = requests_per_user
        self.enable_cooldown = enable_cooldown
        self.scheduler_mode: Literal["sequential", "parallel"] = scheduler_mode
        self.parallel_fetch_enabled = parallel_fetch_enabled
        self.parallel_spawn_interval_ms = parallel_spawn_interval_ms
        self.parallel_cycle_timeout_ms = parallel_cycle_timeout_ms
        self.parallel_wait = parallel_wait

        self._latest_ltp: Optional[float] = None
        self._running = False
        self._paused = False
        self._lock = threading.RLock()
        self._fetch_thread: Optional[threading.Thread] = None
        self._parallel_completion_queue: deque[str] = deque()
        self._parallel_pending_users: deque[str] = deque()
        self._parallel_dispatch_threads: list[threading.Thread] = []
        self._parallel_last_dispatch_ms = {user.name: 0.0 for user in self.fetch_users}
        self._parallel_last_dispatch_any_ms = 0.0
        self._parallel_seeded = False
        self._parallel_fetch_count = 0

        # User rotation state
        self._current_user_index = 0
        self._requests_with_current_user = 0
        self._rotation_cycles_completed = 0

        # Market details monitoring
        self._market_details_running = False
        self._market_details_thread: Optional[threading.Thread] = None
        self._market_details: Optional[List[dict]] = []

        user_info = ', '.join(f"{u.name}(sid={u.symbol})" for u in self.fetch_users)
        logger.info(
            f"ATRADMultiUserPriceFetcher initialized with {len(self.fetch_users)} users: {user_info}, "
            f"poll_interval={poll_interval_ms}ms, rotation={requests_per_user} requests/user, "
            f"scheduler_mode={scheduler_mode}, parallel_enabled={parallel_fetch_enabled}"
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
            name="AmuPfThread",
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
        for thread in list(self._parallel_dispatch_threads):
            thread.join(timeout=0.1)
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
            self.delay = calculate_rotation_delay(self.poll_interval_seconds, 0.005)

    def update_scheduler_settings(
        self,
        scheduler_mode: Optional[Literal["sequential", "parallel"]] = None,
        parallel_fetch_enabled: Optional[bool] = None,
        parallel_spawn_interval_ms: Optional[int] = None,
        parallel_cycle_timeout_ms: Optional[int] = None,
        parallel_wait: Optional[bool] = None,
    ):
        """Update scheduler behavior without recreating the fetcher."""
        with self._lock:
            if scheduler_mode is not None:
                self.scheduler_mode = scheduler_mode
            if parallel_fetch_enabled is not None:
                self.parallel_fetch_enabled = parallel_fetch_enabled
            if parallel_spawn_interval_ms is not None:
                self.parallel_spawn_interval_ms = parallel_spawn_interval_ms
            if parallel_cycle_timeout_ms is not None:
                self.parallel_cycle_timeout_ms = parallel_cycle_timeout_ms
            if parallel_wait is not None:
                self.parallel_wait = parallel_wait

    def update_scheduler_mode(self, scheduler_mode: Literal["sequential", "parallel"]):
        """Convenience wrapper for switching scheduler modes at runtime."""
        self.update_scheduler_settings(scheduler_mode=scheduler_mode)

    def _current_scheduler_mode(self) -> Literal["sequential", "parallel"]:
        """Return the effective scheduler mode for the current settings."""
        with self._lock:
            if self.parallel_fetch_enabled and self.scheduler_mode == "parallel":
                return "parallel"
            return "sequential"

    def _reset_parallel_state(self):
        """Reset transient scheduler state when entering or leaving parallel mode."""
        with self._lock:
            self._parallel_completion_queue.clear()
            self._parallel_pending_users.clear()
            self._parallel_last_dispatch_ms = {user.name: 0.0 for user in self.fetch_users}
            self._parallel_last_dispatch_any_ms = 0.0
            self._parallel_seeded = False

    def _get_fetch_user_by_name(self, user_name: str) -> Optional[ATRADFetchUser]:
        """Look up a configured fetch user by its scheduler name."""
        for user in self.fetch_users:
            if user.name == user_name:
                return user
        return None

    def _prune_parallel_threads(self):
        """Drop completed worker threads from the tracked thread list."""
        with self._lock:
            self._parallel_dispatch_threads = [
                thread for thread in self._parallel_dispatch_threads if thread.is_alive()
            ]

    def _can_dispatch_parallel(self, now_ms: float) -> bool:
        """Check whether the next dispatch is allowed under strict-wait rules."""
        with self._lock:
            if not self.parallel_wait:
                return True
            if not self._parallel_last_dispatch_any_ms:
                return True
            return (now_ms - self._parallel_last_dispatch_any_ms) >= self.parallel_spawn_interval_ms

    def _spawn_parallel_fetch(self, current_user: ATRADFetchUser, timeout: float) -> bool:
        """Spawn a single parallel LTP fetch for the given user."""
        now_ms = time.perf_counter() * 1000
        if not self._can_dispatch_parallel(now_ms):
            return False

        with self._lock:
            if (
                not self._running
                or self._paused
                or self._market_details_running
                or self._current_scheduler_mode() != "parallel"
            ):
                return False
            self._parallel_fetch_count += 1
            fetch_index = self._parallel_fetch_count
            self._parallel_last_dispatch_ms[current_user.name] = now_ms
            self._parallel_last_dispatch_any_ms = now_ms

        def run_fetch() -> None:
            try:
                ltp = current_user.client.get_ltp(current_user.symbol, timeout=timeout)
                with self._lock:
                    can_publish = (
                        self._running
                        and not self._paused
                        and not self._market_details_running
                        and self._current_scheduler_mode() == "parallel"
                    )
                    if ltp is not None and can_publish:
                        self._latest_ltp = ltp
                        logger.debug(f"[{current_user.name}] Parallel fetch #{fetch_index}: LTP={ltp} ({current_user.symbol})")
                    elif ltp is None:
                        logger.warning(
                            f"[{current_user.name}] Parallel fetch #{fetch_index}: "
                            f"LTP returned None ({current_user.symbol})"
                        )
                    self._parallel_completion_queue.append(current_user.name)
            except Exception as e:
                logger.error(
                    f"[{current_user.name}] Error in parallel fetch loop (fetch #{fetch_index}): {str(e)}"
                )
                with self._lock:
                    self._parallel_completion_queue.append(current_user.name)

        thread = threading.Thread(
            target=run_fetch,
            name=f"AmuPf-{current_user.name}-{fetch_index}",
            daemon=True,
        )
        with self._lock:
            self._parallel_dispatch_threads.append(thread)
        thread.start()
        return True

    def _seed_parallel_fetches(self) -> bool:
        """Seed one request per user when parallel mode begins."""
        timeout = calculate_request_timeout(self.poll_interval_seconds)
        for index, current_user in enumerate(self.fetch_users):
            if not self._running or self._current_scheduler_mode() != "parallel":
                return False
            while self._running and self._current_scheduler_mode() == "parallel":
                if self._spawn_parallel_fetch(current_user, timeout):
                    break
                time.sleep(0.001)
            if index < (len(self.fetch_users) - 1) and self.parallel_spawn_interval_ms > 0:
                time.sleep(self.parallel_spawn_interval_ms / 1000.0)

        with self._lock:
            self._parallel_seeded = True
        return True

    def _dispatch_next_parallel_fetch(self) -> bool:
        """Dispatch the next parallel fetch based on completions or oldest-user fallback."""
        timeout = calculate_request_timeout(self.poll_interval_seconds)

        with self._lock:
            if self._parallel_completion_queue:
                self._parallel_pending_users.append(self._parallel_completion_queue.popleft())

        with self._lock:
            pending_user_name = self._parallel_pending_users[0] if self._parallel_pending_users else None
        if pending_user_name:
            current_user = self._get_fetch_user_by_name(pending_user_name)
            if current_user and self._spawn_parallel_fetch(current_user, timeout):
                with self._lock:
                    if self._parallel_pending_users and self._parallel_pending_users[0] == pending_user_name:
                        self._parallel_pending_users.popleft()
                return True

        now_ms = time.perf_counter() * 1000
        with self._lock:
            if self._parallel_last_dispatch_any_ms:
                ready_for_fallback = (
                    now_ms - self._parallel_last_dispatch_any_ms
                ) >= self.parallel_cycle_timeout_ms
            else:
                ready_for_fallback = True
            oldest_user_name = None
            if ready_for_fallback and self.fetch_users:
                oldest_user_name = min(
                    self.fetch_users,
                    key=lambda user: self._parallel_last_dispatch_ms.get(user.name, 0.0),
                ).name

        if oldest_user_name:
            current_user = self._get_fetch_user_by_name(oldest_user_name)
            if current_user and self._spawn_parallel_fetch(current_user, timeout):
                return True

        return False

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
            name="AmuMdThread",
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

        if len(self._market_details) > 0:
            logger.info(f"Market Details:: {json.dumps(self._market_details, indent=2)}")
            self._market_details = []

        # Resume LTP fetching
        self.resume()
        logger.info("ATRADMultiUserPriceFetcher market details monitoring stopped")

    def _market_details_loop(self):
        """Main loop for fetching market details at regular intervals with user rotation."""
        logger.info(
            f"Starting multi-user market details loop (interval={self.poll_interval_ms}ms, "
            f"rotation={self.requests_per_user} requests/user)"
        )

        timeout = calculate_request_timeout(self.poll_interval_seconds)
        sleep_duration = self.poll_interval_seconds

        while self._market_details_running:
            try:
                # Get next user in rotation
                current_user = self._get_next_user()

                # Fetch market details from client
                bid = current_user.client.get_market_details(current_user.symbol, timeout=timeout)

                if not bid:
                    logger.warning(f"[{current_user.name}] Market Details for {current_user.symbol}: No data available")
                    time.sleep(self.delay)
                    continue
                else:    
                    bid['fetched_time_ms'] = int(time.time() * 1000)
                    bid['symbol'] = current_user.symbol
                    self._market_details.append(bid)
                    splits = bid.get('splits', 'N/A')
                    qty = bid.get('qty', 'N/A')
                    price = bid.get('price', 'N/A')
                    logger.debug(f"[{current_user.name}] Price={price}, Qty={qty}, Splits={splits}")

            except KeyboardInterrupt:
                logger.info("Multi-user market details loop interrupted by user")
                break
            except Exception as e:
                logger.error(f"Error in multi-user market details loop: {str(e)}")
                time.sleep(self.delay)
                continue

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

        active_mode: Optional[Literal["sequential", "parallel"]] = None
        fetch_count = 0
        while self._running:
            current_user_name = "unknown"
            try:
                with self._lock:
                    is_paused = self._paused
                    market_details_running = self._market_details_running
                    timeout = calculate_request_timeout(self.poll_interval_seconds)
                    poll_interval_seconds = self.poll_interval_seconds
                    enable_cooldown = self.enable_cooldown
                    delay = self.delay
                current_mode = self._current_scheduler_mode()

                if current_mode != active_mode:
                    self._reset_parallel_state()
                    active_mode = current_mode
                    logger.info(f"ATRADMultiUserPriceFetcher scheduler mode switched to {current_mode}")

                if not is_paused and not market_details_running:
                    if current_mode == "parallel":
                        with self._lock:
                            seeded = self._parallel_seeded
                        if not seeded:
                            if not self._seed_parallel_fetches():
                                continue
                        else:
                            self._dispatch_next_parallel_fetch()
                        self._prune_parallel_threads()
                        time.sleep(0.001)
                        continue
                    else:
                        fetch_count += 1
                        current_user = self._get_next_user()
                        current_user_name = current_user.name
                        ltp = current_user.client.get_ltp(current_user.symbol, timeout=timeout)
                        if ltp is None:
                            logger.warning(
                                f"[{current_user.name}] Fetch #{fetch_count}: "
                                f"LTP returned None (sid={current_user.symbol})"
                            )
                            time.sleep(delay)
                            continue
                        with self._lock:
                            self._latest_ltp = ltp
                        logger.debug(f"[{current_user.name}] LTP={ltp})")
                else:
                    time.sleep(0.001)
                    continue

            except KeyboardInterrupt:
                logger.info("Multi-user fetch loop interrupted by user")
                break
            except Exception as e:
                logger.error(
                    f"[{current_user_name}] Error in fetch loop (fetch #{fetch_count}): {str(e)}"
                )
                time.sleep(delay)
                continue

            try:
                time.sleep(poll_interval_seconds)

                if enable_cooldown and self._should_add_cooldown_delay():
                    logger.debug(
                        f"Cooldown delay after {self._rotation_cycles_completed} rotation cycles"
                    )
                    time.sleep(poll_interval_seconds + delay)
                    if self._rotation_cycles_completed > (self._len_fetch_users * 5):
                        self._rotation_cycles_completed = 0
            except KeyboardInterrupt:
                logger.info("Multi-user fetch loop interrupted by user")
                break

        logger.info(f"Multi-user fetch loop ended (total fetches: {fetch_count})")
