"""Price refresh adapter for the TUI."""

from __future__ import annotations

from pathlib import Path
import time

from utils.config.atrad_config_actions import iter_atrad_user_paths
from utils.config.update_order_prices import PriceUpdateResult, update_order_store


class OrderPriceRefreshService:
    """Refresh order prices using the existing ATRAD quote updater."""

    def __init__(
        self,
        order_store_path: str | Path = "stores/order_store.json",
        users_dir: str | Path = "users",
    ) -> None:
        self.order_store_path = Path(order_store_path)
        self.users_dir = Path(users_dir)

    def _default_atrad_user_path(self) -> Path:
        user_paths = iter_atrad_user_paths(self.users_dir)
        if not user_paths:
            raise ValueError("No ATRAD user config files found in users/")
        return user_paths[0]

    def refresh_all(self) -> PriceUpdateResult:
        atrad_user_path = self._default_atrad_user_path()
        if time.localtime().tm_hour >= 11 and time.localtime().tm_hour < 15:
            return PriceUpdateResult(
                updated={},
                skipped_count=0,
                failed_count=0,
                message="Warning: Cannot refresh prices during market hours."
            )
        return update_order_store(
            order_store_path=str(self.order_store_path),
            atrad_user_path=str(atrad_user_path),
            dry_run=False,
            ticker_filter=None,
        )
