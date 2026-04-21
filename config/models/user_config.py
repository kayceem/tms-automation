"""User-specific configuration management for multi-user support."""

import threading
from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from config.loaders import DEFAULT_CONFIG_FILENAME, apply_inherited_defaults
from config.loaders.file_utils import load_json_file, save_json_file


@dataclass
class UserConfig:
    """Configuration for a single user."""

    user_id: str
    tms_host: str
    tms_base_url: str
    xsrf_token: str
    rid_cookie: str
    host_session_id: str
    access_token: str
    request_owner: str
    member_code: str
    member_id: Optional[str] = None

    # System identifier: 'tms' or 'atrad' (only for main order user, NOT for fetch users)
    system: str = 'tms'  # Default to TMS for backward compatibility

    # Client data (user's broker account information)
    client_data: Optional[Dict[str, Any]] = None

    # Order defaults
    default_order_type: str = 'LMT'
    default_order_validity: str = 'DAY'
    default_product_code: str = 'CNC'
    default_instrument_type: str = 'EQ'
    default_buy_or_sell: int = 1

    # Trigger mode settings
    trigger_mode_poll_interval_ms: int = 100  # Polling interval in milliseconds for fetching LTP (buy trigger)
    multi_fetch_poll_interval_ms: int = 100  # Polling interval in milliseconds for multi-queue symbol fetching
    trigger_mode_refresh_interval_seconds: int = 60  # Token refresh interval to keep main user ready
    trigger_sell_poll_interval_ms: int = 500  # Polling interval in milliseconds for sell trigger (less aggressive)
    trigger_mode_slow_poll_interval_ms: int = 500  # Slower polling when LTP is far from trigger (no_ladder mode only)
    trigger_mode_requests_per_fetch_user : int = 5  # Number of requests to fetch LTP for multiple users in trigger mode
    trigger_mode_parallel_fetch_enabled: bool = True
    trigger_mode_parallel_spawn_interval_ms: int = 10
    trigger_mode_parallel_cycle_timeout_ms: int = 20
    trigger_mode_parallel_wait: bool = False
    # API endpoints
    tms_order_endpoint: str = '/tmsapi/orderApi/order/'
    tms_refresh_endpoint: str = '/tmsapi/security/'
    tms_quote_endpoint: str = '/tmsapi/rtApi/ws/stockQuote/'  # LTP fetch endpoint

    # Internal: file path for auto-saving (not serialized to JSON)
    _config_file_path: Optional[str] = None
    _inherited_default_keys: set[str] = field(default_factory=set)

    def __post_init__(self):
        """Validate required fields."""
        required = [
            'user_id', 'tms_host', 'tms_base_url',
            'xsrf_token', 'rid_cookie', 'host_session_id',
            'access_token', 'request_owner', 'member_code'
        ]
        missing = [field for field in required if not getattr(self, field)]
        if missing:
            raise ValueError(
                f"Missing required configuration for user {self.user_id}: {', '.join(missing)}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = {
            'user_id': self.user_id,
            'tms_host': self.tms_host,
            'tms_base_url': self.tms_base_url,
            'xsrf_token': self.xsrf_token,
            'rid_cookie': self.rid_cookie,
            'host_session_id': self.host_session_id,
            'access_token': self.access_token,
            'request_owner': self.request_owner,
            'member_code': self.member_code,
            'member_id': self.member_id,
            'system': self.system,
            'client_data': self.client_data,
            'default_order_type': self.default_order_type,
            'default_order_validity': self.default_order_validity,
            'default_product_code': self.default_product_code,
            'default_instrument_type': self.default_instrument_type,
            'default_buy_or_sell': self.default_buy_or_sell,
            'trigger_mode_poll_interval_ms': self.trigger_mode_poll_interval_ms,
            'multi_fetch_poll_interval_ms': self.multi_fetch_poll_interval_ms,
            'trigger_mode_refresh_interval_seconds': self.trigger_mode_refresh_interval_seconds,
            'trigger_sell_poll_interval_ms': self.trigger_sell_poll_interval_ms,
            'trigger_mode_slow_poll_interval_ms': self.trigger_mode_slow_poll_interval_ms,
            'trigger_mode_requests_per_fetch_user': self.trigger_mode_requests_per_fetch_user,
            'trigger_mode_parallel_fetch_enabled': self.trigger_mode_parallel_fetch_enabled,
            'trigger_mode_parallel_spawn_interval_ms': self.trigger_mode_parallel_spawn_interval_ms,
            'trigger_mode_parallel_cycle_timeout_ms': self.trigger_mode_parallel_cycle_timeout_ms,
            'trigger_mode_parallel_wait': self.trigger_mode_parallel_wait,
        }
        for key in self._inherited_default_keys:
            data.pop(key, None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'UserConfig':
        """Create UserConfig from dictionary."""
        # Filter out internal fields (starting with _)
        filtered_data = {k: v for k, v in data.items() if not k.startswith('_')}
        return cls(**filtered_data)

    @classmethod
    def from_file(cls, file_path: str) -> 'UserConfig':
        """Load user configuration from JSON file."""
        path = Path(file_path)
        data = load_json_file(file_path, "User configuration file not found: {file_path}")
        data, inherited_keys = apply_inherited_defaults(file_path, data)

        config = cls.from_dict(data)
        # Store the file path for auto-saving refreshed cookies
        config._config_file_path = str(path.resolve())
        config._inherited_default_keys = inherited_keys
        return config

    def save_to_file(self, file_path: str):
        """Save user configuration to JSON file."""
        save_json_file(file_path, self.to_dict())

    def update_cookies(self, xsrf_token: str = None, rid_cookie: str = None,
                      host_session_id: str = None, access_token: str = None,
                      auto_save: bool = True):
        """
        Update authentication cookies.

        Args:
            xsrf_token: New XSRF token
            rid_cookie: New RID cookie
            host_session_id: New host session ID
            access_token: New access token
            auto_save: If True and config was loaded from file, automatically save to disk
        """
        if xsrf_token:
            self.xsrf_token = xsrf_token
        if rid_cookie:
            self.rid_cookie = rid_cookie
        if host_session_id:
            self.host_session_id = host_session_id
        if access_token:
            self.access_token = access_token

        # Auto-save to file if path is available
        if auto_save and self._config_file_path:
            try:
                self.save_to_file(self._config_file_path)
            except Exception as e:
                # Log error but don't raise - cookie update succeeded even if save failed
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Failed to auto-save updated cookies to {self._config_file_path}: {e}")


class UserConfigManager:
    """Thread-safe manager for multiple user configurations."""

    def __init__(self):
        """Initialize the configuration manager."""
        self._configs: Dict[str, UserConfig] = {}
        self._lock = threading.RLock()

    def add_user(self, user_config: UserConfig):
        """
        Add a user configuration.

        Args:
            user_config: UserConfig instance to add
        """
        with self._lock:
            self._configs[user_config.user_id] = user_config

    def get_user(self, user_id: str) -> Optional[UserConfig]:
        """
        Get user configuration by ID.

        Args:
            user_id: User identifier

        Returns:
            UserConfig instance or None if not found
        """
        with self._lock:
            return self._configs.get(user_id)

    def remove_user(self, user_id: str):
        """
        Remove a user configuration.

        Args:
            user_id: User identifier to remove
        """
        with self._lock:
            self._configs.pop(user_id, None)

    def load_users_from_directory(self, directory: str):
        """
        Load all user configurations from a directory.

        Args:
            directory: Path to directory containing user config JSON files
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            raise FileNotFoundError(f"User configuration directory not found: {directory}")

        with self._lock:
            for config_file in dir_path.glob('*.json'):
                if config_file.name == DEFAULT_CONFIG_FILENAME:
                    continue
                try:
                    user_config = UserConfig.from_file(str(config_file))
                    self._configs[user_config.user_id] = user_config
                except Exception as e:
                    # Skip invalid configuration files
                    print(f"Warning: Failed to load {config_file}: {e}")

    def get_all_users(self) -> Dict[str, UserConfig]:
        """
        Get all user configurations.

        Returns:
            Dictionary mapping user IDs to UserConfig instances
        """
        with self._lock:
            return self._configs.copy()

    def user_count(self) -> int:
        """Get the number of configured users."""
        with self._lock:
            return len(self._configs)
