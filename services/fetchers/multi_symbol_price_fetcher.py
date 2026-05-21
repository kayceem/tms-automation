"""
Multi-Symbol Sequential Price Fetcher

Monitors multiple symbols sequentially (one after another) to detect which one
reaches its switch threshold first. Used for multi_queue IPO trigger mode.
"""

import threading
import time
from typing import List, Dict, Any, Optional
from utils.logger import get_logger

logger = get_logger(__name__)


class SymbolConfig:
    """Configuration for a single symbol to monitor."""

    def __init__(
        self,
        symbol: str,
        switch_threshold: float,
        order_id: str,
        security_id: Optional[int] = None,
        fetch_security_id: Optional[int] = None
    ):
        self.symbol = symbol
        self.switch_threshold = switch_threshold
        self.order_id = order_id
        self.security_id = security_id
        self.fetch_security_id = fetch_security_id


def determine_multi_symbol_poll_interval_ms(
    *,
    latest_ltps: Dict[str, Optional[float]],
    symbols_config: List[SymbolConfig],
    slow_poll_interval_ms: int,
    fast_poll_interval_ms: int,
    near_trigger_ratio: float = 0.94,
) -> int:
    """Choose slow or fast poll based on whether any symbol is near its own trigger."""
    for config in symbols_config:
        ltp = latest_ltps.get(config.symbol)
        if ltp is None:
            continue
        if ltp >= (config.switch_threshold * near_trigger_ratio):
            return fast_poll_interval_ms
    return slow_poll_interval_ms


def sync_multi_symbol_poll_interval_ms(
    *,
    fetcher: Any,
    latest_ltps: Dict[str, Optional[float]],
    symbols_config: List[SymbolConfig],
    current_poll_interval_ms: int,
    slow_poll_interval_ms: int,
    fast_poll_interval_ms: int,
) -> int:
    """Update a fetcher to the correct slow/fast interval and return the active interval."""
    target_poll_interval_ms = determine_multi_symbol_poll_interval_ms(
        latest_ltps=latest_ltps,
        symbols_config=symbols_config,
        slow_poll_interval_ms=slow_poll_interval_ms,
        fast_poll_interval_ms=fast_poll_interval_ms,
    )
    if target_poll_interval_ms != current_poll_interval_ms:
        fetcher.update_poll_interval_ms(target_poll_interval_ms)
    return target_poll_interval_ms


class MultiSymbolSequentialPriceFetcher:
    """
    Price fetcher that monitors multiple symbols sequentially.

    Polls each symbol in order, checking if any has reached its switch threshold.
    Returns the first symbol to reach threshold as the priority symbol.
    """

    def __init__(
        self,
        symbols_config: List[SymbolConfig],
        fetch_clients: List[Any],
        poll_interval_ms: int,
        user_id: str,
        is_atrad: bool = False
    ):
        """
        Initialize multi-symbol sequential price fetcher.

        Args:
            symbols_config: List of SymbolConfig objects to monitor
            fetch_clients: List of fetch clients (TMS or ATRAD)
            poll_interval_ms: Polling interval in milliseconds
            user_id: User ID for logging
            is_atrad: True if using ATRAD clients, False for TMS
        """
        self.symbols_config = symbols_config
        self.fetch_clients = fetch_clients
        self.poll_interval_ms = poll_interval_ms
        self.user_id = user_id
        self.is_atrad = is_atrad

        # State
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

        # Latest LTP for each symbol
        self._latest_ltp: Dict[str, Optional[float]] = {
            config.symbol: None for config in symbols_config
        }

        # Priority symbol (first to reach switch threshold)
        self._priority_symbol: Optional[str] = None

        # Client rotation state (for multi-user fetch)
        self._current_client_index = 0
        self._num_clients = len(fetch_clients)

        client_info = f"{len(fetch_clients)} fetch client(s)" if len(fetch_clients) > 1 else "1 fetch client"
        logger.info(
            f"[{self.user_id}] Multi-symbol fetcher initialized: "
            f"{len(symbols_config)} symbols, interval={poll_interval_ms}ms, {client_info} (rotation enabled)"
        )

    def update_poll_interval_ms(self, poll_interval_ms: int) -> None:
        """Update the polling interval dynamically."""
        with self._lock:
            self.poll_interval_ms = poll_interval_ms

    def start(self):
        """Start monitoring all symbols sequentially."""
        if self._running:
            logger.warning(f"[{self.user_id}] Multi-symbol fetcher already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self._thread.start()

        logger.info(f"[{self.user_id}] Multi-symbol fetcher started")

    def stop(self):
        """Stop monitoring."""
        if not self._running:
            return

        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

        logger.info(f"[{self.user_id}] Multi-symbol fetcher stopped")

    def get_latest_ltp(self, symbol: str) -> Optional[float]:
        """
        Get the latest LTP for a specific symbol.

        Args:
            symbol: Symbol to get LTP for

        Returns:
            Latest LTP or None if not available
        """
        with self._lock:
            return self._latest_ltp.get(symbol)

    def get_all_ltps(self) -> Dict[str, Optional[float]]:
        """
        Get latest LTPs for all symbols.

        Returns:
            Dictionary mapping symbol to LTP
        """
        with self._lock:
            return self._latest_ltp.copy()

    def get_priority_symbol(self) -> Optional[str]:
        """
        Get the symbol that reached switch threshold first.

        Returns:
            Symbol name or None if no symbol reached threshold yet
        """
        with self._lock:
            return self._priority_symbol

    def _monitoring_loop(self):
        """Background thread that monitors all symbols sequentially."""
        while self._running:
            try:
                with self._lock:
                    interval_seconds = self.poll_interval_ms / 1000.0
                # Monitor each symbol sequentially
                for config in self.symbols_config:
                    if not self._running:
                        break

                    # Fetch LTP for this symbol
                    ltp = self._fetch_ltp_for_symbol(config)

                    # Update latest LTP
                    with self._lock:
                        self._latest_ltp[config.symbol] = ltp

                    # Check if this symbol reached switch threshold
                    if ltp and ltp >= config.switch_threshold:
                        with self._lock:
                            if self._priority_symbol is None:
                                self._priority_symbol = config.symbol
                                logger.info(
                                    f"[{self.user_id}] Multi-queue: {config.symbol} reached "
                                    f"switch threshold ({config.switch_threshold}) - "
                                    f"LTP={ltp} - Setting as PRIORITY order"
                                )
                                # Stop monitoring once we have a priority
                                self._running = False
                                break

                    # Sleep between symbol fetches
                    time.sleep(interval_seconds)

                # Log current status (all symbols)
                if self._running and not self._priority_symbol:
                    ltp_parts = []
                    for cfg in self.symbols_config:
                        ltp_val = self._latest_ltp[cfg.symbol]
                        if ltp_val is not None:
                            ltp_parts.append(f"{cfg.symbol}={ltp_val}")
                        else:
                            ltp_parts.append(f"{cfg.symbol}=N/A")
                    ltps_str = ", ".join(ltp_parts)
                    logger.debug(f"[{self.user_id}] Multi-queue monitoring: {ltps_str}")

            except Exception as e:
                logger.error(f"[{self.user_id}] Error in multi-symbol monitoring loop: {e}")
                time.sleep(interval_seconds*2)

    def _get_next_client(self) -> Any:
        """
        Get the next fetch client in rotation.

        Returns:
            Next client to use for fetching
        """
        if self._num_clients == 1:
            return self.fetch_clients[0]

        # Round-robin rotation through clients
        client = self.fetch_clients[self._current_client_index]
        self._current_client_index = (self._current_client_index + 1) % self._num_clients
        return client

    def _fetch_ltp_for_symbol(self, config: SymbolConfig) -> Optional[float]:
        """
        Fetch LTP for a single symbol.

        Args:
            config: Symbol configuration

        Returns:
            LTP or None if fetch failed
        """
        try:
            if self.is_atrad:
                # ATRAD: Use symbol directly
                return self._fetch_atrad_ltp(config.symbol)
            else:
                # TMS: Use fetch_security_id
                fetch_id = config.fetch_security_id or config.security_id
                return self._fetch_tms_ltp(fetch_id)

        except Exception as e:
            logger.debug(
                f"[{self.user_id}] Failed to fetch LTP for {config.symbol}: {e}"
            )
            return None

    def _fetch_tms_ltp(self, security_id: int) -> Optional[float]:
        """Fetch LTP from TMS."""
        # Rotate through fetch clients
        client = self._get_next_client()

        try:
            response = client.get_ltp(security_id)

            if response and isinstance(response, dict) and 'data' in response:
                data = response['data']

                # Try different LTP field names
                if isinstance(data, dict):
                    if 'ltp' in data:
                        return float(data['ltp'])
                    elif 'lastTradedPrice' in data:
                        return float(data['lastTradedPrice'])
                    elif 'last_price' in data:
                        return float(data['last_price'])

            return None

        except Exception as e:
            logger.debug(f"[{self.user_id}] TMS LTP fetch error: {e}")
            return None

    def _fetch_atrad_ltp(self, symbol: str) -> Optional[float]:
        """Fetch LTP from ATRAD."""
        # Rotate through fetch clients
        client = self._get_next_client()

        try:
            return client.get_ltp(symbol)

        except Exception as e:
            logger.debug(f"[{self.user_id}] ATRAD LTP fetch error: {e}")
            return None
