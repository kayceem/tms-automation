"""NEPSE ATRAD API client for order placement."""

import requests
import json
import threading
import random
from typing import Dict, Any, Optional
from urllib.parse import quote
from config.atrad_user_config import ATRADUserConfig
from utils.logger import get_logger

logger = get_logger(__name__)


class ATRADClient:
    """Thread-safe client for interacting with NEPSE ATRAD API."""

    def __init__(self, user_config: ATRADUserConfig):
        """
        Initialize ATRAD client with user-specific configuration.

        Args:
            user_config: ATRADUserConfig instance for this user
        """
        self.user_config = user_config
        self.user_id = user_config.user_id
        self.base_url = user_config.atrad_base_url
        self.login_endpoint = f"{self.base_url}{user_config.atrad_login_endpoint}"
        self.order_endpoint = f"{self.base_url}{user_config.atrad_order_endpoint}"

        # Thread-safe session
        self.session = requests.Session()
        self._login_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._is_authenticated = False

        self._setup_headers()

        # Pre-build static parts of order payload
        self._build_static_payload()

        # Try to restore session from saved cookies
        self._restore_session_from_cookies()

        logger.info(f"[{self.user_id}] ATRADClient initialized for {self.base_url}")

    def _setup_headers(self):
        """Set up default headers for API requests."""
        self.session.headers.update({
            'Host': self.user_config.atrad_host,
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:147.0) Gecko/20100101 Firefox/147.0',
            'Accept': '*/*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br, zstd',
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-Requested-With': 'XMLHttpRequest',
            'Origin': self.user_config.atrad_base_url,
            'Sec-GPC': '1',
            'Connection': 'keep-alive',
            'Referer': f'{self.user_config.atrad_base_url}/atsweb/home?action=showHome&format=html',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Priority': 'u=0',
            'TE': 'trailers'
        })

    def _build_static_payload(self):
        """Pre-build static parts of the order payload and body for efficiency."""
        # Static fields that don't change per order
        static_fields = {
            "action": "submitOrder",
            "market": "NEPSE",
            "broker": self.user_config.broker_code or "",
            "format": "json",
            "clientOrderId": "",
            "cseOrderId": "",
            "brokerClient": "1",
            "orderStatus": "Open",
            "filledQty": "",
            "acntid": str(self.user_config.account_id),
            "oldPrice": "",
            "oldQty": "",
            "remainder": "",
            "orderplacedate": "",
            "oldDisclose": "",
            "txtContraBroker": self.user_config.contra_broker or "",
            "txtapprovalReason": "",
            "txtsenttoapproval": "no",
            "txtCompId": "",
            "txtOdrStatus": "",
            "product": self.user_config.default_product,
            "clientAcc": self.user_config.client_account or "",
            "assetSelect": self.user_config.default_asset_select,
            "cmbTypeOfOrder": self.user_config.default_type_of_order,
            "cmbTif": self.user_config.default_order_type,
            "cmbTifDays": "1",
            "cmbBoard": self.user_config.default_board,
            "hiddenSpnCseFee": "0.02",
            "txtContraBroker_": str(self.user_config.contra_broker) or "",
            "brokerClientVal": "1",
            "confirm": "1"
        }

        # Pre-encode static body parts
        body_parts = []
        for key, value in static_fields.items():
            if key == "clientAcc":
                # Special encoding for clientAcc: spaces to %20, keep () unencoded
                encoded_value = quote(str(value), safe='()-')
            else:
                # Standard encoding for other fields
                encoded_value = quote(str(value), safe='')
            body_parts.append(f"{key}={encoded_value}")

        # Store pre-encoded static body string
        self._static_body = "&".join(body_parts)


    def _restore_session_from_cookies(self):
        """
        Restore session from saved cookies if available.

        Loads cookies from user config and validates the session.
        If valid, sets _is_authenticated to True.
        """
        if not self.user_config._cookies:
            logger.debug(f"[{self.user_id}] No saved cookies found, will need to login")
            return 

        logger.info(f"[{self.user_id}] Found saved cookies, attempting to restore session...")

        # Restore cookies to session
        for cookie_name, cookie_value in self.user_config._cookies.items():
            self.session.cookies.set(cookie_name, cookie_value)

        # Validate session by making a test request
        if self._validate_session():
            self._is_authenticated = True
            self.user_config.update_session(
                session_id=self.session.cookies.get("JSESSIONID"),
                role=self.session.cookies.get("role"),
                broker_code=self.session.cookies.get("broker_code"),
                max_basket_limit=int(self.session.cookies.get("max_basket_limit", None)),
                watch_id=int(self.session.cookies.get("watchID", None)),
                is_dvp_enabled=self.session.cookies.get("is_dvp_enabled"),
                theme=self.session.cookies.get("theme")
            )
            logger.info(f"[{self.user_id}] Session restored successfully from saved cookies")
        else:
            logger.warning(f"[{self.user_id}] Saved cookies are invalid or expired, will re-login")
            self.session.cookies.clear()
            self.user_config._cookies = None

    def _validate_session(self) -> bool:
        """
        Validate current session by making a test API request.

        Returns:
            True if session is valid, False otherwise
        """
        try:
            # Make a lightweight test request to check session validity
            test_url = f"{self.base_url}/atsweb/home"
            response = self.session.get(test_url, timeout=5)
        
            # If we get redirected to login page or get 401, session is invalid
            if response.status_code == 401 or response.status_code == 302 or 'login' in response.url.lower():
                logger.info(f"[{self.user_id}] {response.url}")
                return False

            return response.status_code == 200

        except Exception as e:
            logger.debug(f"[{self.user_id}] Session validation failed: {e}")
            return False

    def _save_cookies_to_config(self):
        """Save current session cookies to user config for persistence."""
        cookies_dict = {cookie.name: cookie.value for cookie in self.session.cookies}

        if cookies_dict:
            self.user_config.update_session(cookies=cookies_dict)
            self.user_config.save_session()
            logger.debug(f"[{self.user_id}] Saved {len(cookies_dict)} cookies to config file")
        
    def login(self) -> Dict[str, Any]:
        """
        Login to ATRAD system and establish session.

        Returns:
            Login response dictionary

        Raises:
            requests.HTTPError: If login request fails
        """
        if self._is_authenticated and self._validate_session():
            logger.info(f"[{self.user_id}] Already authenticated, skipping login")
            return {"code": "0", "description": "Already authenticated"}

        self._is_authenticated = False

        with self._login_lock:
            logger.info(f"[{self.user_id}] Attempting ATRAD login...")

            # Login payload
            payload = {
                "action": "login",
                "format": "json",
                "txtUserName": self.user_config.username,
                "txtPassword": self.user_config.password,
            }

            try:
                response = self.session.post(
                    self.login_endpoint,
                    data=payload
                )
                
                response.raise_for_status()
                result = response.json()

                if result.get("code") == "0":
                    self._is_authenticated = True

                    # Extract broker_code from response or cookies
                    broker_code = result.get("broker_code") or self.session.cookies.get("broker_code")

                    # Store session information
                    self.user_config.update_session(
                        session_id=self.session.cookies.get("JSESSIONID"),
                        role=result.get("role"),
                        broker_code=broker_code,
                        max_basket_limit=int(result.get("max_basket_limit")) if result.get("max_basket_limit") else None,
                        watch_id=int(result.get("watchID")) if result.get("watchID") else None,
                        is_dvp_enabled=result.get("is_dvp_enabled"),
                        theme="black"
                    )

                    # Update user config broker_code if not already set
                    if broker_code and not self.user_config.broker_code:
                        self.user_config.broker_code = broker_code

                    # Set cookies for subsequent requests
                    self.session.cookies.set("role", result.get("role"))
                    if broker_code:
                        self.session.cookies.set("broker_code", broker_code)
                    self.session.cookies.set("max_basket_limit", str(result.get("max_basket_limit")))
                    self.session.cookies.set("watchID", str(result.get("watchID")))
                    self.session.cookies.set("is_dvp_enabled", result.get("is_dvp_enabled"))
                    self.session.cookies.set("theme", "black")

                    # Save cookies to config file for session persistence
                    self._save_cookies_to_config()

                    logger.info(
                        f"[{self.user_id}] ATRAD login successful! "
                        f"Role: {result.get('role')}, Broker: {broker_code or 'N/A'}"
                    )
                    return result
                else:
                    logger.error(f"[{self.user_id}] ATRAD login failed: {result.get('description')}")
                    raise Exception(f"Login failed: {result.get('description')}")

            except requests.exceptions.RequestException as e:
                logger.error(f"[{self.user_id}] ATRAD login request failed: {e}")
                raise

    def is_authenticated(self) -> bool:
        """Check if session is authenticated."""
        return self._is_authenticated

    def _generate_duplicate_order_id(self) -> str:
        """
        Generate a duplicate order ID matching ATRAD's format.

        Creates a 10-character random string using alphanumeric characters
        (digits 1-9, lowercase a-z, uppercase A-Z) - matching the JavaScript
        implementation in ATRAD's debtOrderWindow.js.

        Returns:
            10-character random alphanumeric string
        """
        chars = "123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
        return ''.join(random.choice(chars) for _ in range(10))

    def place_order(
        self,
        symbol: str,
        quantity: int,
        price: float,
        side: str = 'BUY',  # 'BUY' or 'SELL'
        market_price: float = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Place an order on NEPSE ATRAD (thread-safe).

        Args:
            symbol: Stock symbol/ticker
            quantity: Number of units
            price: Price per unit
            side: 'BUY' or 'SELL'
            market_price: Current market price (LTP)
            contra_broker: Contra broker code (optional)
            **kwargs: Additional ATRAD-specific parameters

        Returns:
            API response as dictionary

        Raises:
            Exception: If not authenticated or API request fails
        """
        if not self._is_authenticated:
            logger.warning(f"[{self.user_id}] Not authenticated, attempting login...")
            self.login()

        # Use price as market_price if not provided
        if market_price is None:
            market_price = price

        # Convert side to actionSelect value
        action_select = "2" if side.upper() == "SELL" else "1"

        logger.info(
            f"[{self.user_id}] Placing {side} order: "
            f"Symbol={symbol}, Price={price}, Qty={quantity}"
        )

        # Generate duplicate order ID
        duplicate_order_id = self._generate_duplicate_order_id()
        logger.debug(f"[{self.user_id}] Generated duplicateOrderId: {duplicate_order_id}")

        dynamic_fields = {
            "marketPrice": f"{market_price:.1f}",
            "duplicateOrderId": duplicate_order_id,
            "actionSelect": action_select,
            "txtSecurity": symbol,
            "spnQuantity": str(quantity),
            "spnPrice": f"{price:.1f}",
        }

        # Encode dynamic fields
        dynamic_parts = []
        for key, value in dynamic_fields.items():
            encoded_value = quote(str(value), safe='')
            dynamic_parts.append(f"{key}={encoded_value}")

        # Combine pre-encoded static body with dynamic parts
        body = self._static_body + "&" + "&".join(dynamic_parts)

        # Make thread-safe API request
        with self._request_lock:
            response = self.session.post(self.order_endpoint, data=body)
            response.encoding = 'utf-8'

            logger.debug(
                f"[{self.user_id}] Response status: {response.status_code}"
            )

            # Log response body
            try:
                response_json = response.json()
                logger.debug(
                    f"[{self.user_id}] Response: {json.dumps(response_json, indent=2)}"
                )
            except Exception:
                logger.debug(f"[{self.user_id}] Response text: {response.text}")

            # Check for session expiry and retry
            if response.status_code == 401 or (response.status_code == 200 and "session" in response.text.lower()):
                logger.warning(f"[{self.user_id}] Session expired, re-authenticating...")
                self._is_authenticated = False
                self.login()

                # Retry order placement with the same encoded body
                response = self.session.post(self.order_endpoint, data=body)
                response.encoding = 'utf-8'
                logger.debug(
                    f"[{self.user_id}] Response status: {response.status_code}"
                )

            response.raise_for_status()

            try:
                result = response.json()

                # Check ATRAD response code
                if result.get("code") == "0" or result.get("code") == 0:
                    logger.info(f"[{self.user_id}] ATRAD order placed successfully")
                    return result
                else:
                    error_msg = result.get("description", "Unknown error")
                    logger.error(f"[{self.user_id}] ATRAD order failed: {error_msg}")
                    raise Exception(f"Order placement failed: {error_msg}")

            except ValueError:
                logger.error(f"[{self.user_id}] Invalid JSON response: {response.text}")
                raise Exception(f"Invalid response from ATRAD server: {response.text}")

    def ensure_authenticated(self):
        """Ensure the client is authenticated, login if necessary."""
        if not self._is_authenticated:
            self.login()

    def refresh_tokens(self) -> bool:
        """
        Returns:
            True if refresh was successful, False otherwise
        """
        self.ensure_authenticated()
        return self._is_authenticated