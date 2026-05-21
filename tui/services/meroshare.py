"""MeroShare adapters for the TUI."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from api import MeroShareClient
from config import MeroShareUserConfig
from tui.models import (
    MeroShareApplicationReportRow,
    MeroShareIssueRow,
    MeroSharePortfolioRow,
    MeroShareWaccRow,
)


def _pick_first(payload: dict, *keys: str, default: str = "") -> str:
    for key in keys:
        value = payload.get(key)
        if value not in (None, ""):
            return str(value)
    return default


def _load_json(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


class MeroShareService:
    """TUI-facing service for MeroShare users and portfolio data."""

    def __init__(self, users_dir: str | Path = "users") -> None:
        self.users_dir = Path(users_dir)

    def list_users(self) -> list[Path]:
        if not self.users_dir.exists():
            return []

        paths: dict[Path, None] = {}
        for path in sorted(self.users_dir.glob("meroshare_user*.json")):
            paths[path] = None

        for path in sorted(self.users_dir.glob("*.json")):
            if path in paths or path.name == "default.json":
                continue
            try:
                payload = _load_json(path)
            except (OSError, json.JSONDecodeError):
                continue
            if payload.get("system") == "meroshare" or "meroshare_base_url" in payload:
                paths[path] = None

        return list(paths)

    def load_user_config(self, path: str | Path) -> MeroShareUserConfig:
        return MeroShareUserConfig.from_file(str(path))

    def get_user_label(self, path: str | Path) -> str:
        config = self.load_user_config(path)
        return config.username or config.user_id

    def fetch_portfolio(self, path: str | Path) -> tuple[list[MeroSharePortfolioRow], str]:
        client = MeroShareClient(self.load_user_config(path))
        payload = client.get_portfolio()
        rows = [
            MeroSharePortfolioRow(
                script=_pick_first(item, "script", default="-"),
                script_desc=_pick_first(item, "scriptDesc", default="-"),
                current_balance=_pick_first(item, "currentBalance", default="-"),
                last_transaction_price=_pick_first(item, "lastTransactionPrice", default="-"),
                previous_closing_price=_pick_first(item, "previousClosingPrice", default="-"),
                value_as_of_last_transaction_price=_pick_first(
                    item,
                    "valueAsOfLastTransactionPrice",
                    "valueOfLastTransPrice",
                    default="-",
                ),
                value_as_of_previous_closing_price=_pick_first(
                    item,
                    "valueAsOfPreviousClosingPrice",
                    "valueOfPrevClosingPrice",
                    default="-",
                ),
                raw=item,
            )
            for item in payload
            if isinstance(item, dict)
        ]
        rows.sort(key=lambda row: row.script)
        return rows, datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch_wacc(self, path: str | Path) -> tuple[list[MeroShareWaccRow], dict, str]:
        client = MeroShareClient(self.load_user_config(path))
        payload = client.get_wacc_report()
        raw_rows = payload.get("waccReportResponse", []) if isinstance(payload, dict) else []
        rows = [
            MeroShareWaccRow(
                script=_pick_first(item, "scrip", "script", default="-"),
                demat=_pick_first(item, "demat", default="-"),
                total_quantity=_pick_first(item, "totalQuantity", default="-"),
                average_buy_rate=_pick_first(item, "averageBuyRate", default="-"),
                total_cost=_pick_first(item, "totalCost", default="-"),
                last_modified_date=_pick_first(item, "lastModifiedDate", default="-"),
                raw=item,
            )
            for item in raw_rows
            if isinstance(item, dict)
        ]
        rows.sort(key=lambda row: row.script)
        return rows, payload if isinstance(payload, dict) else {}, datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch_current_issues(self, path: str | Path) -> tuple[list[MeroShareIssueRow], str]:
        client = MeroShareClient(self.load_user_config(path))
        payload = client.get_applicable_issues()
        rows = [
            MeroShareIssueRow(
                script=_pick_first(item, "scrip", "script", default="-"),
                company_name=_pick_first(item, "companyName", "company", default="-"),
                share_type=_pick_first(item, "shareTypeName", "shareType", default="-"),
                share_group=_pick_first(item, "shareGroupName", "shareGroup", default="-"),
                status=_pick_first(item, "statusName", "status", default="-"),
                open_date=_pick_first(item, "issueOpenDate", "openDate", default="-"),
                close_date=_pick_first(item, "issueCloseDate", "closeDate", default="-"),
                raw=item,
            )
            for item in payload
            if isinstance(item, dict)
        ]
        rows.sort(key=lambda row: row.script)
        return rows, datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def fetch_application_report(self, path: str | Path) -> tuple[list[MeroShareApplicationReportRow], str]:
        client = MeroShareClient(self.load_user_config(path))
        payload = client.get_application_report()
        rows = [
            MeroShareApplicationReportRow(
                script=_pick_first(item, "scrip", "script", default="-"),
                company_name=_pick_first(item, "companyName", "company", default="-"),
                share_type=_pick_first(item, "shareTypeName", "shareType", default="-"),
                share_group=_pick_first(item, "shareGroupName", "shareGroup", default="-"),
                status=_pick_first(item, "statusName", "status", default="-"),
                applied_date=_pick_first(item, "appliedDate", default="-"),
                applied_units=_pick_first(item, "appliedKitta", "appliedUnits", "quantity", default="-"),
                amount=_pick_first(item, "amount", "totalAmount", "appliedAmount", default="-"),
                raw=item,
            )
            for item in payload
            if isinstance(item, dict)
        ]
        return rows, datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def check_edis_status(self, path: str | Path) -> bool:
        client = MeroShareClient(self.load_user_config(path))
        return bool(client.check_edis_status(status=True))
