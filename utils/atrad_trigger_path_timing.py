"""Low-overhead trigger-to-order timing for ATRAD workflows."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from typing import Optional

from utils.logger import get_logger

logger = get_logger(__name__)


def _is_enabled() -> bool:
    value = os.getenv("ATRAD_TRIGGER_PATH_TIMING", "")
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass
class _Probe:
    user_id: str
    symbol: str
    trigger_ltp: float
    trigger_price: float
    trigger_perf_ns: int
    trigger_epoch_ms: float


class _TriggerPathState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[tuple[str, str], _Probe] = {}

    def mark_trigger(
        self,
        *,
        user_id: str,
        symbol: str,
        trigger_ltp: float,
        trigger_price: float,
    ) -> None:
        if not _is_enabled() or not symbol:
            return
        key = (user_id, symbol.upper())
        probe = _Probe(
            user_id=user_id,
            symbol=symbol.upper(),
            trigger_ltp=trigger_ltp,
            trigger_price=trigger_price,
            trigger_perf_ns=time.perf_counter_ns(),
            trigger_epoch_ms=time.time() * 1000.0,
        )
        with self._lock:
            self._active[key] = probe

    def mark_place_start(
        self,
        *,
        user_id: str,
        symbol: str,
        order_price: float,
        market_price: float,
    ) -> None:
        if not _is_enabled() or not symbol:
            return
        key = (user_id, symbol.upper())
        with self._lock:
            probe = self._active.pop(key, None)
        if probe is None:
            return

        place_perf_ns = time.perf_counter_ns()
        place_epoch_ms = time.time() * 1000.0
        trigger_to_place_ms = (place_perf_ns - probe.trigger_perf_ns) / 1_000_000.0
        epoch_gap_ms = place_epoch_ms - probe.trigger_epoch_ms
        logger.info(
            f"[{user_id}] Trigger path timing: symbol={probe.symbol}, "
            f"trigger_ltp={probe.trigger_ltp:.1f}, trigger_price={probe.trigger_price:.1f}, "
            f"order_price={order_price:.1f}, market_price={market_price:.1f}, "
            f"trigger_epoch_ms={probe.trigger_epoch_ms:.3f}, place_epoch_ms={place_epoch_ms:.3f}, "
            f"trigger_to_place_start_ms={trigger_to_place_ms:.4f}, epoch_gap_ms={epoch_gap_ms:.4f}"
        )


_STATE = _TriggerPathState()


def mark_trigger_detected(
    *,
    user_id: str,
    symbol: Optional[str],
    trigger_ltp: float,
    trigger_price: float,
) -> None:
    if symbol is None:
        return
    _STATE.mark_trigger(
        user_id=user_id,
        symbol=symbol,
        trigger_ltp=trigger_ltp,
        trigger_price=trigger_price,
    )


def mark_order_place_start(
    *,
    user_id: str,
    symbol: Optional[str],
    order_price: float,
    market_price: float,
) -> None:
    if symbol is None:
        return
    _STATE.mark_place_start(
        user_id=user_id,
        symbol=symbol,
        order_price=order_price,
        market_price=market_price,
    )
