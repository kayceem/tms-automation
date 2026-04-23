"""Factories and resolution helpers for application orchestration."""

import logging
from typing import Any, Optional

from api import ATRADClient, TMSClient
from config import ATRADUserConfig
from services.orders import ATRADOrderService, OrderService
from utils import get_ticker_store

from app.models import PlatformBundle, ResolvedTicker


logger = logging.getLogger("main")


def create_fetch_clients(fetch_user_configs=None, is_atrad_fetch: bool = False):
    """Create platform-specific fetch clients."""
    if not fetch_user_configs:
        return None
    client_cls = ATRADClient if is_atrad_fetch else TMSClient
    return [client_cls(cfg) for cfg in fetch_user_configs]


def log_fetch_client_summary(user_id: str, fetch_user_configs, fetch_clients, is_atrad_fetch: bool) -> None:
    """Emit a consistent fetch-client initialization summary."""
    if not fetch_clients:
        return

    platform = "ATRAD" if is_atrad_fetch else "TMS"
    if len(fetch_clients) == 1:
        logger.info(f"[{user_id}] {platform} fetch client initialized: {fetch_user_configs[0].user_id}")
    else:
        user_ids = ', '.join(cfg.user_id for cfg in fetch_user_configs)
        logger.info(f"[{user_id}] Multi-user {platform} fetch initialized: {len(fetch_clients)} users ({user_ids})")


def create_order_client_and_service(user_config, quantity_override: Optional[int] = None) -> PlatformBundle:
    """Create the main order client and service for a user config."""
    is_atrad = isinstance(user_config, ATRADUserConfig)
    if is_atrad:
        logger.info(f"[{user_config.user_id}] Using ATRAD system")
        client = ATRADClient(user_config)
        service = ATRADOrderService(client)
    else:
        logger.info(f"[{user_config.user_id}] Using TMS system")
        client = TMSClient(user_config)
        service = OrderService(client)
    return PlatformBundle(
        client=client,
        service=service,
        is_atrad=is_atrad,
        quantity_override=quantity_override,
    )


def create_order_bundles(user_configs=None):
    """Create order client/service bundles for a list of user configs."""
    if not user_configs:
        return []
    bundles = []
    for entry in user_configs:
        if isinstance(entry, dict) and "user_config" in entry:
            bundles.append(
                create_order_client_and_service(
                    entry["user_config"],
                    quantity_override=entry.get("quantity_override"),
                )
            )
        else:
            bundles.append(create_order_client_and_service(entry))
    return bundles


def lookup_ticker_name(ticker: str) -> Optional[str]:
    """Look up the display name for a ticker."""
    return get_ticker_store().get_name(ticker)


def resolve_ticker(ticker: str, fetch_user_configs=None, is_atrad_fetch: bool = False) -> ResolvedTicker:
    """Resolve ticker identifiers and host-specific fetch ID."""
    ticker_store = get_ticker_store()
    security_id, exchange_security_id = ticker_store.lookup(ticker)

    fetch_host: Optional[str] = None
    if fetch_user_configs and not is_atrad_fetch:
        fetch_host = fetch_user_configs[0].tms_host

    fetch_id = ticker_store.get_fetch_id(ticker, host=fetch_host)
    ticker_name = None
    get_name = getattr(ticker_store, "get_name", None)
    if callable(get_name):
        try:
            ticker_name = get_name(ticker)
        except Exception:
            ticker_name = None

    return ResolvedTicker(
        ticker=ticker,
        security_id=security_id,
        exchange_security_id=exchange_security_id,
        fetch_id=fetch_id,
        symbol=ticker.upper(),
        name=ticker_name,
        fetch_host=fetch_host,
    )
