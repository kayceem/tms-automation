"""Ticker store management for looking up security IDs by ticker symbol."""

import json
from typing import Dict, Tuple, Optional
from pathlib import Path


class TickerStore:
    """Manages ticker symbol to security ID mappings."""

    def __init__(self, store_path: str = None):
        """
        Initialize ticker store.

        Args:
            store_path: Path to ticker_store.json file. If None, uses default location.
        """
        if store_path is None:
            # Default to ticker_store.json in project root
            store_path = Path(__file__).parent.parent / 'ticker_store.json'

        self.store_path = Path(store_path)
        self._data: Dict = {}
        self._load_store()

    def _load_store(self):
        """Load ticker store from JSON file."""
        if not self.store_path.exists():
            raise FileNotFoundError(
                f"Ticker store not found: {self.store_path}\n"
                f"Please create a ticker_store.json file with ticker mappings."
            )

        try:
            with open(self.store_path, 'r') as f:
                self._data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in ticker store: {e}")

    def lookup(self, ticker: str) -> Tuple[int, int]:
        """
        Look up security_id and exchange_security_id for a ticker symbol.

        Args:
            ticker: Ticker symbol (case-insensitive)

        Returns:
            Tuple of (security_id, exchange_security_id)

        Raises:
            ValueError: If ticker not found in store
        """
        ticker_upper = ticker.upper()

        if ticker_upper not in self._data:
            available_tickers = [k for k in self._data.keys() if not k.startswith('_')]
            raise ValueError(
                f"Ticker '{ticker}' not found in store.\n"
                f"Available tickers: {', '.join(sorted(available_tickers))}"
            )

        ticker_data = self._data[ticker_upper]

        # Validate required fields
        if 'security_id' not in ticker_data:
            raise ValueError(f"Ticker '{ticker}' is missing 'security_id' field")
        if 'exchange_security_id' not in ticker_data:
            raise ValueError(f"Ticker '{ticker}' is missing 'exchange_security_id' field")

        security_id = int(ticker_data['security_id'])
        exchange_security_id = int(ticker_data['exchange_security_id'])

        return security_id, exchange_security_id

    def get_name(self, ticker: str) -> Optional[str]:
        """
        Get the full name for a ticker symbol.

        Args:
            ticker: Ticker symbol (case-insensitive)

        Returns:
            Company name if available, None otherwise
        """
        ticker_upper = ticker.upper()

        if ticker_upper in self._data:
            return self._data[ticker_upper].get('name')

        return None

    def list_tickers(self) -> Dict[str, Dict]:
        """
        Get all available tickers.

        Returns:
            Dictionary of ticker symbols to their data
        """
        return {k: v for k, v in self._data.items() if not k.startswith('_')}

    def add_ticker(self, ticker: str, security_id: int, exchange_security_id: int, name: str = None):
        """
        Add or update a ticker in the store.

        Args:
            ticker: Ticker symbol
            security_id: Security ID
            exchange_security_id: Exchange security ID
            name: Optional company name
        """
        ticker_upper = ticker.upper()

        self._data[ticker_upper] = {
            'security_id': security_id,
            'exchange_security_id': exchange_security_id
        }

        if name:
            self._data[ticker_upper]['name'] = name

        # Save to file
        with open(self.store_path, 'w') as f:
            json.dump(self._data, f, indent=2)


# Global ticker store instance
_ticker_store: Optional[TickerStore] = None


def get_ticker_store(store_path: str = None) -> TickerStore:
    """
    Get the global ticker store instance (singleton pattern).

    Args:
        store_path: Optional path to ticker store JSON file

    Returns:
        TickerStore instance
    """
    global _ticker_store

    if _ticker_store is None:
        _ticker_store = TickerStore(store_path)

    return _ticker_store


def lookup_ticker(ticker: str, store_path: str = None) -> Tuple[int, int]:
    """
    Convenience function to look up a ticker.

    Args:
        ticker: Ticker symbol
        store_path: Optional path to ticker store JSON file

    Returns:
        Tuple of (security_id, exchange_security_id)
    """
    store = get_ticker_store(store_path)
    return store.lookup(ticker)
