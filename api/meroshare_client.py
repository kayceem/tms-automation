"""MeroShare API client for DP portfolio and WACC data."""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from api.network import enable_ipv4_only_requests
from config.models.meroshare_user_config import MeroShareUserConfig
from utils.logger import get_logger

logger = get_logger(__name__)

enable_ipv4_only_requests()


class MeroShareClient:
    """Thread-safe client for MeroShare portfolio-oriented APIs."""

    def __init__(self, user_config: MeroShareUserConfig):
        self.user_config = user_config
        self.user_id = user_config.user_id
        self.base_url = user_config.meroshare_base_url
        self.login_endpoint = f"{self.base_url}{user_config.meroshare_login_endpoint}"
        self.wacc_endpoint = f"{self.base_url}{user_config.meroshare_wacc_endpoint}"
        self.portfolio_endpoint = f"{self.base_url}{user_config.meroshare_portfolio_endpoint}"
        self.details_endpoint = f"{self.base_url}{user_config.meroshare_details_endpoint}"
        self.applicable_issue_endpoint = f"{self.base_url}{user_config.meroshare_applicable_issue_endpoint}"
        self.application_report_endpoint = f"{self.base_url}{user_config.meroshare_application_report_endpoint}"
        self.check_edis_endpoint = f"{self.base_url}{user_config.meroshare_check_edis_endpoint}"
        self.pending_shares_endpoint = f"{self.base_url}{user_config.meroshare_pending_shares_endpoint}"

        self.session = requests.Session()
        self._login_lock = threading.Lock()
        self._request_lock = threading.Lock()
        self._is_authenticated = False

        self._setup_headers()
        self._restore_authorization()

        logger.info(f"[{self.user_id}] MeroShareClient initialized for {self.base_url}")

    def _setup_headers(self) -> None:
        frontend_origin = self._frontend_origin()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Authorization": "null",
                "Content-Type": "application/json",
                "Origin": frontend_origin,
                "Referer": f"{frontend_origin}/",
                "Sec-GPC": "1",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Site": "same-site",
                "Priority": "u=0",
            }
        )

    def _frontend_origin(self) -> str:
        host = self.user_config.meroshare_host_url.strip().rstrip("/")
        if host.startswith("http://") or host.startswith("https://"):
            return host
        return f"https://{host}"

    def _restore_authorization(self) -> None:
        authorization = self.user_config.authorization
        if not authorization:
            return
        self.session.headers["Authorization"] = authorization
        try:
            response = self.session.get(f"{self.details_endpoint}{self.user_config.demat}", timeout=5.0)
            response.raise_for_status()
            if "<html>" in response.text.lower():
                raise RuntimeError("Invalid response: HTML")
        except Exception:
            logger.warning(f"[{self.user_id}] Failed to restore MeroShare authorization")
            self.session.headers["Authorization"] = "null"
            self._is_authenticated = False
            self._clear_session_cookies()
            return
        self._is_authenticated = True
        self._clear_session_cookies()
        logger.debug(f"[{self.user_id}] Restored MeroShare authorization from config")

    def is_authenticated(self) -> bool:
        return self._is_authenticated

    def login(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Login to MeroShare and store the authorization header."""
        with self._login_lock:
            payload = {
                "clientId": self.user_config.client_id_int,
                "username": self.user_config.username,
                "password": self.user_config.password,
            }
            self.session.headers["Authorization"] = "null"
            response = self.session.post(
                self.login_endpoint,
                json=payload,
                timeout=timeout,
            )
            logger.debug(f"[{self.user_id}] MeroShare login response status: {response.status_code}")
            response.raise_for_status()

            authorization = response.headers.get("authorization") or response.headers.get("Authorization")
            if not authorization:
                raise RuntimeError(response.request.url, response.request.headers, response.request.body, response.text)

            self.session.headers["Authorization"] = authorization
            self.user_config.update_authorization(authorization)
            self.user_config.save_session()
            self._is_authenticated = True
            self._clear_session_cookies()

            try:
                return response.json()
            except ValueError:
                return {}

    def _ensure_authenticated(self) -> None:
        if not self._is_authenticated:
            self.login()

    def _request_with_auth(
        self,
        method: str,
        endpoint: str,
        payload: Optional[Dict[str, Any]],
        timeout: float,
        raise_for_status: bool = True,
    ) -> requests.Response:
        self._ensure_authenticated()
        self._clear_session_cookies()
        kwargs: Dict[str, Any] = {"timeout": timeout}
        if payload is not None:
            kwargs["json"] = payload
        response = getattr(self.session, method.lower())(endpoint, **kwargs)
        if response.status_code == 401:
            logger.warning(f"[{self.user_id}] MeroShare authorization expired, logging in again")
            self._is_authenticated = False
            self.session.headers["Authorization"] = "null"
            self.login(timeout=timeout)
            self._clear_session_cookies()
            response = getattr(self.session, method.lower())(endpoint, **kwargs)
        if raise_for_status:
            response.raise_for_status()
        return response
    
    def _clear_session_cookies(self) -> None:
        # CDSC accepts Authorization-only API calls but rejects login cookies on portfolio/WACC.
        self.session.cookies.clear()

    def calculate_wacc(self) -> bool:
        payload = {"isFilterByAllScript": False}
        with self._request_lock:
            response = self._request_with_auth("POST", self.pending_shares_endpoint, payload, timeout=5.0)
            if response.status_code != 200:
                return False
            if "<html>" in response.text.lower():
                return False
            result = response.json()
            if not isinstance(result, list):
                return False
        return False

    def get_wacc_report(self, timeout: float = 5.0) -> Dict[str, Any]:
        """Fetch the WACC report payload for the configured DEMAT."""
        payload = {"demat": self.user_config.demat}
        with self._request_lock:
            response = self._request_with_auth("POST", self.wacc_endpoint, payload, timeout)
            response.raise_for_status()
            if "<html>" in response.text.lower():
                raise RuntimeError("Invalid response: HTML")
            result = response.json()
            is_wacc_pending = result.get("isWaccPending", False)
            if is_wacc_pending:
                logger.warning(f"[{self.user_id}] MeroShare application report indicates WACC pending")
                return {"waccReportResponse": []}
            if not isinstance(result, dict):
                raise RuntimeError("Invalid MeroShare WACC response")
            return result

    def get_portfolio(self, *, page: int = 1, size: int = 200, timeout: float = 5.0) -> list[Dict[str, Any]]:
        """Fetch MeroShare portfolio rows for the configured DEMAT."""
        payload = {
            "sortBy": "script",
            "demat": [self.user_config.demat],
            "clientCode": self.user_config.client_code,
            "page": page,
            "size": size,
            "sortAsc": True,
        }
        with self._request_lock:
            response = self._request_with_auth("POST", self.portfolio_endpoint, payload, timeout)
            response.raise_for_status()
            if "<html>" in response.text.lower():
                raise RuntimeError("Invalid response: HTML", response.text)
            result = response.json()
            if not isinstance(result, dict):
                raise RuntimeError("Invalid MeroShare portfolio response")
            rows = result.get("meroShareMyPortfolio", [])
            if not isinstance(rows, list):
                raise RuntimeError("Invalid MeroShare portfolio response")
            return rows

    def get_applicable_issues(self, timeout: float = 5.0) -> list[Dict[str, Any]]:
        """Fetch applicable issue rows."""
        payload = {
            "filterFieldParams":[
                    {"key":"companyIssue.companyISIN.script","alias":"Scrip"},
                    {"key":"companyIssue.companyISIN.company.name","alias":"Company Name"},
                    {"key":"companyIssue.assignedToClient.name","value":"","alias":"Issue Manager"}
                ],
                "page":1,
                "size":10,
                "searchRoleViewConstants":"VIEW_APPLICABLE_SHARE",
                "filterDateParams":[
                    {"key":"minIssueOpenDate","condition":"","alias":"","value":""},
                    {"key":"maxIssueCloseDate","condition":"","alias":"","value":""}
                ]
            }
        with self._request_lock:
            response = self._request_with_auth("POST", self.applicable_issue_endpoint, payload, timeout)
            response.raise_for_status()
            if "<html>" in response.text.lower():
                raise RuntimeError("Invalid response: HTML", response.text)
            result = response.json()
            if not isinstance(result, dict):
                raise RuntimeError("Invalid MeroShare applicable issue response")
            rows = result.get("object", [])
            if not isinstance(rows, list):
                raise RuntimeError("Invalid MeroShare applicable issue response")
            return rows

    def get_application_report(self, timeout: float = 5.0) -> list[Dict[str, Any]]:
        """Fetch application report rows."""
        payload = {
            "filterFieldParams": [
                {"key": "companyShare.companyIssue.companyISIN.script", "alias": "Scrip"},
                {"key": "companyShare.companyIssue.companyISIN.company.name", "alias": "Company Name"}
            ],
            "page": 1,
            "size": 200,
            "searchRoleViewConstants": "VIEW_APPLICANT_FORM_COMPLETE",
            "filterDateParams": [
                {"key": "appliedDate", "condition": "", "alias": "", "value": ""},
                {"key": "appliedDate", "condition": "", "alias": "", "value": ""}
            ]
        }
        with self._request_lock:
            response = self._request_with_auth("POST", self.application_report_endpoint, payload, timeout)
            response.raise_for_status()
            if "<html>" in response.text.lower():
                raise RuntimeError("Invalid response: HTML", response.text)
            result = response.json()
            if not isinstance(result, dict):
                raise RuntimeError("Invalid MeroShare application report response")
            rows = result.get("object", [])
            if not isinstance(rows, list):
                raise RuntimeError("Invalid MeroShare application report response")
            return rows

    def check_edis_status(self, timeout: float = 5.0, status: bool = False) -> Dict[str, Any] | bool:
        """Check EDIS status for the configured DEMAT."""
        with self._request_lock:
            response = self._request_with_auth(
                "GET",
                self.check_edis_endpoint,
                None,
                timeout,
                raise_for_status=False,
            )
            if "<html>" in response.text.lower():
                raise RuntimeError("Invalid response: HTML", response.text)
            if status:
                return response.status_code != 409
            if response.status_code == 409:
                return {"message": "No EDIS for today"}
            result = response.json()
            if not isinstance(result, dict):
                raise RuntimeError("Invalid MeroShare EDIS status response")
            return result
