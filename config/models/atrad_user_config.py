"""ATRAD-specific user configuration management."""

from pathlib import Path
from typing import Dict, Any, Optional
from dataclasses import dataclass, field

from config.loaders import apply_inherited_defaults
from config.loaders.file_utils import load_json_file, save_json_file


@dataclass
class ATRADUserConfig:
    """Configuration for a single ATRAD user."""

    user_id: str
    atrad_base_url: str
    atrad_host: str
    username: str
    password: str
    account_id: str  # UCC/Account ID for order placement

    # Additional account information
    client_account: Optional[str] = None  # Client account display string
    broker_code: Optional[str] = None  # Broker code (e.g., "NSH")
    contra_broker: Optional[str] = None

    # Client data (user's broker account information) - for compatibility
    client_data: Optional[Dict[str, Any]] = None

    # Order defaults
    default_asset_select: str = '1'  # 1=EQUITY
    default_board: str = '1'  # 1=Regular board
    default_order_type: str = '16'  # 16=Day order
    default_type_of_order: str = '1'  # 1 Regular, 7 Pre Open
    default_product: str = 'web'

    # Trigger mode settings (same as TMS for consistency)
    trigger_mode_poll_interval_ms: int = 100
    multi_fetch_poll_interval_ms: int = 100
    trigger_mode_refresh_interval_seconds: int = 60
    trigger_sell_poll_interval_ms: int = 500
    trigger_mode_slow_poll_interval_ms: int = 500
    trigger_mode_requests_per_fetch_user: int = 5
    trigger_mode_parallel_fetch_enabled: bool = True
    trigger_mode_parallel_spawn_interval_ms: int = 10
    trigger_mode_parallel_cycle_timeout_ms: int = 20
    trigger_mode_parallel_wait: bool = False

    # ATRAD API endpoints
    atrad_login_endpoint: str = '/atsweb/login'
    atrad_market_status_endpoint: str = '/atsweb/home?action=marketStatus'
    atrad_order_endpoint: str = '/atsweb/order'
    atrad_watch_endpoint: str = '/atsweb/watch?action=getWatchForSecurity&format=json&exchange=NEPSE&bookDefId=1'
    atrad_market_details_endpoint: str = '/atsweb/marketdetails?action=getOrderBook&format=json&board=1'
    atrad_order_book_endpoint: str = '/atsweb/order?action=getUCCActiveBlotterData&format=json&clientAcc=ALL&securityId=all&exchange=all&ordStatus=all&ordType=all&assetClass=all'
    atrad_completed_order_book_endpoint: str = '/atsweb/order?action=getUCCInactiveBlotterData&format=json&clientAcc=ALL&securityId=all&exchange=all&ordStatus=all&ordType=all&assetClass=all'
    atrad_cancel_order_endpoint: str = '/atsweb/order?action=cancelOrder&format=json'
    atrad_quick_watch_endpoint: str = '/atsweb/watch?action=getQuickWatch&format=json&exchange=NEPSE&bookDefId=1&isquickwatchsecurity=true&lastUpdatedId=undefined'
    atrad_custom_watchlists_endpoint: str = '/atsweb/watch?action=getCustomWatches&format=json&exchange=NEPSE'
    atrad_watchlist_endpoint: str = '/atsweb/watch?action=userWatch&format=json&exchange=NEPSE&bookDefId=1'
    atrad_add_security_watchlist_endpoint: str = '/atsweb/watch?action=addUserSecurity&format=json&exchange=NEPSE&bookDefId=1&isquickwatchsecurity=false'
    atrad_top_gainers_losers_endpoint: str = '/atsweb/watch?action=place_holder&format=json&size=10&exchange=NEPSE&bookDefId=1&lastUpdatedId=0'
    atrad_ohlc_endpoint: str = '/atsweb/marketdetails?action=getOHLC&format=json&asset=Equity&board=All&pageNumber=1'
    atrad_account_summary_endpoint: str = '/atsweb/client?action=getClientAccountSummary&format=json&exchange=NEPSE'
    # Session management (populated after login)
    _session_id: Optional[str] = None  # JSESSIONID
    _role: Optional[str] = None  # OnlineUser, Manager, etc.
    _broker_code: Optional[str] = None  # NSH, etc.
    _max_basket_limit: Optional[int] = None  # Max orders per basket (if applicable)
    _watch_id: Optional[int] = None  # For order status tracking (if applicable)
    _is_dvp_enabled: Optional[str] = None  # Whether DVP settlement is enabled
    _theme: Optional[str] = None  # User's selected theme (e.g., "black")
    _cookies: Optional[Dict[str, str]] = None  # All session cookies for persistence

    # Internal: file path for auto-saving
    _config_file_path: Optional[str] = None
    _inherited_default_keys: set[str] = field(default_factory=set)

    def __post_init__(self):
        """Validate required fields."""
        required = ['user_id', 'atrad_base_url', 'atrad_host','username', 'password', 'account_id']
        missing = [field for field in required if not getattr(self, field)]
        if missing:
            raise ValueError(
                f"Missing required ATRAD configuration for user {self.user_id}: {', '.join(missing)}"
            )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        data = {
            'user_id': self.user_id,
            'atrad_base_url': self.atrad_base_url,
            'atrad_host': self.atrad_host,
            'username': self.username,
            'password': self.password,
            'account_id': self.account_id,
            'client_account': self.client_account,
            'broker_code': self.broker_code,
            'contra_broker': self.contra_broker,
            'client_data': self.client_data,
            'default_asset_select': self.default_asset_select,
            'default_board': self.default_board,
            'default_order_type': self.default_order_type,
            'default_type_of_order': self.default_type_of_order,
            'default_product': self.default_product,
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

        # Include cookies if available (for session persistence)
        if self._cookies:
            data['_cookies'] = self._cookies

        return data

    @property
    def client_account_number(self) -> Optional[str]:
        """Extract client account number from client_account string."""
        if self.client_account:
            return self.client_account.split(' ')[0].strip()
        return None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ATRADUserConfig':
        """Create ATRADUserConfig from dictionary."""
        # Extract cookies if present
        cookies = data.get('_cookies')

        # Filter out internal fields (starting with _) and 'system' field from constructor args
        filtered_data = {k: v for k, v in data.items() if not k.startswith('_') and k != 'system'}
        config = cls(**filtered_data)

        # Restore cookies if available
        if cookies:
            config._cookies = cookies

        return config

    @classmethod
    def from_file(cls, file_path: str) -> 'ATRADUserConfig':
        """Load ATRAD user configuration from JSON file."""
        path = Path(file_path)
        data = load_json_file(file_path, "ATRAD user configuration file not found: {file_path}")
        data, inherited_keys = apply_inherited_defaults(file_path, data)

        config = cls.from_dict(data)
        # Store the file path for auto-saving
        config._config_file_path = str(path.resolve())
        config._inherited_default_keys = inherited_keys
        return config

    def save_to_file(self, file_path: str):
        """Save ATRAD user configuration to JSON file."""
        save_json_file(file_path, self.to_dict())

    def update_session(self, session_id: str = None, role: str = None, broker_code: str = None,
                      max_basket_limit: int = None, watch_id: int = None, is_dvp_enabled: str = None,
                      theme: str = None, cookies: Dict[str, str] = None):
        """
        Update session information after login.

        Args:
            session_id: JSESSIONID from login response
            role: User role (OnlineUser, Manager, etc.)
            broker_code: Broker code (NSH, etc.)
            max_basket_limit: Max orders per basket (if applicable)
            watch_id: Watch ID for order status tracking (if applicable)
            is_dvp_enabled: Whether DVP settlement is enabled
            theme: User's selected theme (e.g., "black") - for compatibility with ATRAD web UI
            cookies: All session cookies for persistence
        """
        if session_id:
            self._session_id = session_id
        if role:
            self._role = role
        if broker_code:
            self._broker_code = broker_code
        if max_basket_limit is not None:
            self._max_basket_limit = max_basket_limit
        if watch_id is not None:
            self._watch_id = watch_id
        if is_dvp_enabled is not None:
            self._is_dvp_enabled = is_dvp_enabled
        if theme:
            self._theme = theme
        if cookies is not None:
            self._cookies = cookies

    def save_session(self):
        """
        Save session cookies to the config file for persistence.

        This allows reusing the session on next run without re-logging in.
        """
        if self._config_file_path:
            self.save_to_file(self._config_file_path)
