"""MeroShare user configuration management."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

from config.loaders.file_utils import load_json_file, save_json_file


@dataclass
class MeroShareUserConfig:
    """Configuration for a single MeroShare user."""

    user_id: str
    meroshare_base_url: str
    meroshare_host_url: str
    demat: str
    dp: str
    client_id: int | str
    username: str
    password: str
    crn_number: Optional[str] = None
    pin: Optional[str] = None

    meroshare_login_endpoint: str = "/api/meroShare/auth/"
    meroshare_wacc_endpoint: str = "/api/myPurchase/waccReport/"
    meroshare_portfolio_endpoint: str = "/api/meroShareView/myPortfolio/"
    meroshare_details_endpoint: str = "/api/meroShareView/myDetail/"
    meroshare_applicable_issue_endpoint: str = "/api/meroShare/companyShare/applicableIssue/"
    meroshare_application_report_endpoint: str = "/api/meroShare/applicantForm/active/search/"
    meroshare_check_edis_endpoint: str = "/api/EDIS/check/"
    meroshare_pending_shares_endpoint: str = "/api/myPurchase/share/"

    _headers: Dict[str, str] = field(default_factory=dict)
    _config_file_path: Optional[str] = None

    def __post_init__(self) -> None:
        required = [
            "user_id",
            "meroshare_base_url",
            "meroshare_host_url",
            "demat",
            "dp",
            "client_id",
            "username",
            "password",
        ]
        missing = [key for key in required if getattr(self, key) in (None, "")]
        if missing:
            raise ValueError(
                f"Missing required MeroShare configuration for user {self.user_id}: {', '.join(missing)}"
            )

        self.meroshare_base_url = self.meroshare_base_url.rstrip("/")
        self.meroshare_login_endpoint = self._normalize_endpoint(self.meroshare_login_endpoint)
        self.meroshare_wacc_endpoint = self._normalize_endpoint(self.meroshare_wacc_endpoint)
        self.meroshare_portfolio_endpoint = self._normalize_endpoint(self.meroshare_portfolio_endpoint)
        self.meroshare_details_endpoint = self._normalize_endpoint(self.meroshare_details_endpoint)
        self.meroshare_applicable_issue_endpoint = self._normalize_endpoint(self.meroshare_applicable_issue_endpoint)
        self.meroshare_application_report_endpoint = self._normalize_endpoint(self.meroshare_application_report_endpoint)
        self.meroshare_check_edis_endpoint = self._normalize_endpoint(self.meroshare_check_edis_endpoint)
        self.meroshare_pending_shares_endpoint = self._normalize_endpoint(self.meroshare_pending_shares_endpoint)
        self._headers = {str(key): str(value) for key, value in (self._headers or {}).items()}

    @staticmethod
    def _normalize_endpoint(endpoint: str) -> str:
        return endpoint if endpoint.startswith("/") else f"/{endpoint}"

    @property
    def client_id_int(self) -> int:
        return int(self.client_id)

    @property
    def client_code(self) -> str:
        return str(self.dp)

    @property
    def authorization(self) -> Optional[str]:
        value = self._headers.get("authorization") or self._headers.get("Authorization")
        return value or None

    def update_authorization(self, authorization: str) -> None:
        self._headers["authorization"] = authorization

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "meroshare_base_url": self.meroshare_base_url,
            "meroshare_host_url": self.meroshare_host_url,
            "demat": self.demat,
            "dp": self.dp,
            "client_id": self.client_id,
            "username": self.username,
            "password": self.password,
            "crn_number": self.crn_number or "",
            "pin": self.pin or "",
            "_headers": dict(self._headers),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MeroShareUserConfig":
        return cls(**data)

    @classmethod
    def from_file(cls, file_path: str) -> "MeroShareUserConfig":
        path = Path(file_path)
        data = load_json_file(file_path, "MeroShare user configuration file not found: {file_path}")
        config = cls.from_dict(data)
        config._config_file_path = str(path.resolve())
        return config

    def save_to_file(self, file_path: str) -> None:
        save_json_file(file_path, self.to_dict())

    def save_session(self) -> None:
        if self._config_file_path:
            self.save_to_file(self._config_file_path)
