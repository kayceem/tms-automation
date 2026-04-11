"""NEPSE TMS API client for order placement."""

import json
import threading
from pathlib import Path
from typing import Dict, Any, Optional

import requests

from api.network import enable_ipv4_only_requests
from config.models.user_config import UserConfig
from utils.logger import get_logger

logger = get_logger(__name__)

enable_ipv4_only_requests()


class TMSClient:
    """Thread-safe client for interacting with NEPSE TMS API."""

    def __init__(self, user_config: UserConfig):
        """
        Initialize TMS client with user-specific configuration.

        Args:
            user_config: UserConfig instance for this user
        """
        self.user_config = user_config
        self.user_id = user_config.user_id
        self.base_url = user_config.tms_base_url
        self.order_endpoint = f"{self.base_url}{user_config.tms_order_endpoint}"
        self.refresh_endpoint = f"{self.base_url}/tmsapi/authApi/authenticate/refresh"
        self.quote_endpoint = f"{self.base_url}{user_config.tms_quote_endpoint}"

        # Thread-safe session
        self.session = requests.Session()
        self._refresh_lock = threading.Lock()
        self._request_lock = threading.Lock()

        self._setup_headers()

        logger.info(f"[{self.user_id}] TMSClient initialized for {self.base_url}")

    def _setup_headers(self):
        """Set up default headers for API requests."""
        self.session.headers.update({
            'Host': self.user_config.tms_host,
            'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64; rv:147.0) Gecko/20100101 Firefox/147.0',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'X-Xsrf-Token': self.user_config.xsrf_token,
            'Request-Owner': self.user_config.request_owner,
            'Membercode': self.user_config.member_code,
            'Host-Session-Id': self.user_config.host_session_id,
            'Content-Type': 'application/json',
            'Origin': self.user_config.tms_base_url,
            'Sec-Gpc': '1',
            'Referer': f'{self.user_config.tms_base_url}/tms/me/memberclientorderentry',
            'Sec-Fetch-Dest': 'empty',
            'Sec-Fetch-Mode': 'cors',
            'Sec-Fetch-Site': 'same-origin',
            'Te': 'trailers',
        })

        # Set cookies (remove any ellipsis characters)
        rid_cookie = self.user_config.rid_cookie.replace('…', '')
        aid_cookie = self.user_config.access_token.replace('…', '')

        self.session.cookies.set('_rid', rid_cookie)
        self.session.cookies.set('_aid', aid_cookie)
        self.session.cookies.set('XSRF-TOKEN', self.user_config.xsrf_token)

        logger.debug(f"[{self.user_id}] Headers configured")

    def place_order(
        self,
        security_id: int,
        exchange_security_id: int,
        order_price: float,
        order_quantity: int,
        buy_or_sell: int = None,
        order_type: str = None,
        order_validity: str = None,
        product_code: str = None
    ) -> Dict[str, Any]:
        """
        Place an order on NEPSE TMS (thread-safe).

        Args:
            security_id: Security ID
            exchange_security_id: Exchange security ID
            order_price: Price per unit
            order_quantity: Number of units
            buy_or_sell: 1 for buy, 2 for sell
            order_type: Order type code (default: LMT)
            order_validity: Order validity code (default: DAY)
            product_code: Product code (default: CNC)

        Returns:
            API response as dictionary

        Raises:
            requests.HTTPError: If API request fails
        """
        # Use defaults from user config if not provided
        buy_or_sell = buy_or_sell or self.user_config.default_buy_or_sell
        order_type = order_type or self.user_config.default_order_type
        order_validity = order_validity or self.user_config.default_order_validity
        product_code = product_code or self.user_config.default_product_code

        logger.info(
            f"[{self.user_id}] Placing {'BUY' if buy_or_sell == 1 else 'SELL'} order: "
            f"Security={security_id}, Price={order_price}, Qty={order_quantity}"
        )

        # Build request payload
        payload = self._build_order_payload(
            security_id=security_id,
            exchange_security_id=exchange_security_id,
            order_price=order_price,
            order_quantity=order_quantity,
            buy_or_sell=buy_or_sell,
            order_type=order_type,
            order_validity=order_validity,
            product_code=product_code
        )

        # Make thread-safe API request
        with self._request_lock:
            response = self.session.post(self.order_endpoint, json=payload)
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

            # If we get 401, try to refresh tokens and retry once
            if response.status_code == 401:
                logger.warning(f"[{self.user_id}] Session expired, attempting token refresh")

                if self._refresh_tokens():
                    logger.info(f"[{self.user_id}] Tokens refreshed, retrying order")

                    # Retry the request with new tokens
                    response = self.session.post(self.order_endpoint, json=payload)
                    response.encoding = 'utf-8'

                    logger.debug(
                        f"[{self.user_id}] Retry response status: {response.status_code}"
                    )
                else:
                    logger.error(f"[{self.user_id}] Token refresh failed")
                    logger.debug(f"[{self.user_id}] Response: {response.text}")


            response.raise_for_status()

            result = response.json()
            logger.info(f"[{self.user_id}] Order placed successfully")
            return result

    def refresh_tokens(self) -> bool:
        """
        Public method to manually refresh authentication tokens (thread-safe).

        Returns:
            True if refresh was successful, False otherwise
        """
        with self._refresh_lock:
            return self._refresh_tokens()

    def _refresh_tokens(self) -> bool:
        """
        Refresh authentication tokens by calling the refresh endpoint.

        Returns:
            True if refresh was successful, False otherwise
        """
        try:
            logger.info(f"[{self.user_id}] Refreshing authentication tokens")
            logger.debug(f"[{self.user_id}] Refresh URL: {self.refresh_endpoint}")

            # Make refresh request
            response = self.session.post(self.refresh_endpoint)
            response.encoding = 'utf-8'

            if response.status_code == 200:
                logger.info(f"[{self.user_id}] Token refresh successful")

                # Log new cookies
                for cookie in response.cookies:
                    logger.debug(
                        f"[{self.user_id}] New cookie: {cookie.name}={cookie.value[:20]}..."
                    )

                # Save updated cookies
                self._save_cookies()

                return True
            else:
                logger.error(
                    f"[{self.user_id}] Token refresh failed: "
                    f"{response.status_code} {response.reason}"
                )
                logger.debug(f"[{self.user_id}] Response: {response.text}")
                return False

        except Exception as e:
            logger.error(
                f"[{self.user_id}] Error during token refresh: {str(e)}",
                exc_info=True
            )
            return False

    def _save_cookies(self):
        """Save current session cookies to user's config file."""
        try:
            # Extract cookies from session
            rid_cookie = ''
            aid_cookie = ''
            for cookie in self.session.cookies:
                if cookie.name == '_rid' and cookie.domain == '.' + self.user_config.tms_base_url.split('//')[1]:
                    rid_cookie = cookie.value
                elif cookie.name == '_aid' and cookie.domain == '.' + self.user_config.tms_base_url.split('//')[1]:
                    aid_cookie = cookie.value

            # Update user config
            self.user_config.update_cookies(
                rid_cookie=rid_cookie if rid_cookie else None,
                access_token=aid_cookie if aid_cookie else None
            )

            logger.info(f"[{self.user_id}] Cookies updated in configuration")
            logger.debug(
                f"[{self.user_id}] _rid: {rid_cookie[:30] if rid_cookie else '(empty)'}..."
            )
            logger.debug(
                f"[{self.user_id}] _aid: {aid_cookie[:30] if aid_cookie else '(empty)'}..."
            )

        except Exception as e:
            logger.warning(
                f"[{self.user_id}] Could not save cookies: {str(e)}"
            )

    def get_ltp(self, security_id: int, timeout: float = 0.1) -> Optional[float]:
        """
        Fetch the Last Traded Price (LTP) for a security (thread-safe).

        Args:
            security_id: Security ID to fetch LTP for
            timeout: Request timeout in seconds (default: 5.0)

        Returns:
            LTP as float, or None if fetch fails or times out

        Raises:
            requests.HTTPError: If API request fails with non-401 error
        """
        logger.debug(f"[{self.user_id}] Fetching LTP for security_id={security_id}")

        endpoint = f"{self.quote_endpoint}{security_id}"

        # Make thread-safe API request with timeout
        with self._request_lock:
            try:
                response = self.session.get(endpoint, timeout=timeout)
                response.encoding = 'utf-8'

                logger.debug(
                    f"[{self.user_id}] LTP fetch response status: {response.status_code}"
                )
            except requests.exceptions.Timeout:
                logger.warning(f"[{self.user_id}] LTP fetch timed out after {timeout}s")
                return None
            except requests.exceptions.RequestException as e:
                logger.warning(f"[{self.user_id}] LTP fetch failed: {e}")
                return None

            # If we get 401, try to refresh tokens and retry once
            if response.status_code == 401:
                logger.debug(f"[{self.user_id}] Session expired, attempting token refresh")

                if self._refresh_tokens():
                    logger.debug(f"[{self.user_id}] Tokens refreshed, retrying LTP fetch")

                    # Retry the request with new tokens
                    try:
                        response = self.session.get(endpoint, timeout=timeout)
                        response.encoding = 'utf-8'

                        logger.debug(
                            f"[{self.user_id}] Retry LTP response status: {response.status_code}"
                        )
                    except requests.exceptions.Timeout:
                        logger.warning(f"[{self.user_id}] Retry LTP fetch timed out after {timeout}s")
                        return None
                    except requests.exceptions.RequestException as e:
                        logger.warning(f"[{self.user_id}] Retry LTP fetch failed: {e}")
                        return None
                else:
                    logger.error(f"[{self.user_id}] Token refresh failed for LTP fetch")
                    return None

            if response.status_code == 200:
                try:
                    data = response.json()
                    security = data.get('payload', {}).get('data', [None])[0]
                    ltp = security.get('ltp') if security else None
                    if ltp is not None:
                        logger.debug(f"[{self.user_id}] LTP={ltp}")
                        return float(ltp)
                    else:
                        logger.warning(f"[{self.user_id}] No LTP in response: {data}")
                        return None
                except Exception as e:
                    logger.error(
                        f"[{self.user_id}] Error parsing LTP response: {str(e)}"
                    )
                    return None
            else:
                logger.warning(
                    f"[{self.user_id}] LTP fetch failed: "
                    f"{response.status_code} {response.reason}"
                )
                return None

    def _build_order_payload(
        self,
        security_id: int,
        exchange_security_id: int,
        order_price: float,
        order_quantity: int,
        buy_or_sell: int,
        order_type: str,
        order_validity: str,
        product_code: str
    ) -> Dict[str, Any]:
        """Build the order payload matching the API structure."""
        return {
            "orderBook": {
                "orderBookExtensions": [
                    {
                        "orderTypes": {
                            "id": 1,
                            "orderTypeCode": order_type
                        },
                        "disclosedQuantity": 0,
                        "orderValidity": {
                            "id": 1,
                            "orderValidityCode": order_validity
                        },
                        "triggerPrice": 0,
                        "orderPrice": order_price,
                        "orderQuantity": order_quantity,
                        "remainingOrderQuantity": order_quantity,
                        "marketType": {
                            "id": 2,
                            "marketType": "Continuous"
                        }
                    }
                ],
                "exchange": {
                    "id": 1
                },
                "dnaConnection": {},
                "dealer": {},
                "member": {},
                "productType": {
                    "id": 1,
                    "productCode": product_code
                },
                "instrumentType": {
                    "id": 1,
                    "code": self.user_config.default_instrument_type
                },
                "client": self.user_config.client_data,
                "security": {
                    "id": security_id,
                    "exchangeSecurityId": exchange_security_id,
                    "marketProtectionPercentage": 0,
                    "divisor": 100,
                    "boardLotQuantity": 1,
                    "tickSize": 0.1
                },
                "accountType": 1,
                "cpMemberId": 0,
                "buyOrSell": buy_or_sell
            },
            "orderPlacedBy": 2,
            "exchangeOrderId": None
        }
