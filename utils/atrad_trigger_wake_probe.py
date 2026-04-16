#!/usr/bin/env python3
"""Measure local ATRAD fetcher publish/wake overhead around trigger detection."""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).parent.parent))

from api import ATRADClient
from config.models import ATRADUserConfig
from services.orders.atrad_order_service import ATRADOrderService


@dataclass(frozen=True)
class MetricStats:
    count: int
    median_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float


class TriggerController:
    """Control when the patched get_ltp methods flip into the triggered state."""

    def __init__(self, trigger_price: float, trigger_after_ms: float) -> None:
        self.trigger_price = trigger_price
        self.below_price = trigger_price - 10.0
        self.trigger_after_ms = trigger_after_ms
        self.started_at: float | None = None
        self._lock = threading.Lock()
        self._trigger_return_recorded = False
        self.trigger_return_time: float | None = None

    def arm(self) -> None:
        self.started_at = time.perf_counter()

    def should_trigger(self) -> bool:
        if self.started_at is None:
            return False
        return (time.perf_counter() - self.started_at) * 1000.0 >= self.trigger_after_ms

    def mark_trigger_return(self) -> None:
        with self._lock:
            if not self._trigger_return_recorded:
                self._trigger_return_recorded = True
                self.trigger_return_time = time.perf_counter()

    def make_get_ltp(self, *, can_trigger: bool) -> Callable[..., float]:
        def fake_get_ltp(_symbol: str, timeout: float = 0.0) -> float:
            if can_trigger and self.should_trigger():
                self.mark_trigger_return()
                return self.trigger_price
            return self.below_price

        return fake_get_ltp


@contextmanager
def patched_method(obj: Any, attr: str, replacement: Callable[..., Any]):
    original = getattr(obj, attr)
    setattr(obj, attr, replacement)
    try:
        yield
    finally:
        setattr(obj, attr, original)


def summarize(values: list[float]) -> MetricStats:
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return MetricStats(
        count=len(ordered),
        median_ms=statistics.median(ordered) * 1000,
        p95_ms=ordered[p95_index] * 1000,
        min_ms=ordered[0] * 1000,
        max_ms=ordered[-1] * 1000,
    )


def default_output_path() -> Path:
    day_dir = Path("logs") / "latency" / datetime.now().strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"atrad_trigger_wake_probe_{datetime.now().strftime('%H%M%S')}.txt"


def load_clients(user_paths: list[str]) -> list[ATRADClient]:
    clients: list[ATRADClient] = []
    for user_path in user_paths:
        user_config = ATRADUserConfig.from_file(user_path)
        client = ATRADClient(user_config)
        if not client.ensure_authenticated():
            raise RuntimeError(f"[{user_config.user_id}] authentication failed")
        clients.append(client)
    return clients


def measure_real_fetcher_trigger_wake(
    clients: list[ATRADClient],
    *,
    symbol: str,
    trigger_price: float,
    poll_interval_ms: int,
    trigger_after_ms: float,
    iterations: int,
) -> tuple[MetricStats, MetricStats, MetricStats]:
    if not clients:
        raise ValueError("At least one ATRAD user config is required")

    service = ATRADOrderService(clients[0])
    service.client.user_config.trigger_mode_parallel_fetch_enabled = False

    get_return_to_publish_values: list[float] = []
    publish_to_waiter_return_values: list[float] = []
    get_return_to_waiter_return_values: list[float] = []

    for _ in range(iterations):
        controller = TriggerController(trigger_price=trigger_price, trigger_after_ms=trigger_after_ms)
        publish_time: float | None = None

        fetcher = service._setup_atrad_price_fetcher(
            fetch_clients=clients,
            symbol=symbol,
            poll_interval_ms=poll_interval_ms,
        )

        original_publish_ltp = fetcher._publish_ltp

        def wrapped_publish_ltp(ltp: float) -> None:
            nonlocal publish_time
            if ltp >= trigger_price and publish_time is None:
                publish_time = time.perf_counter()
            return original_publish_ltp(ltp)

        with ExitStack() as stack:
            for index, client in enumerate(clients):
                stack.enter_context(
                    patched_method(client, "get_ltp", controller.make_get_ltp(can_trigger=index == 0))
                )
            stack.enter_context(patched_method(fetcher, "_publish_ltp", wrapped_publish_ltp))

            try:
                fetcher.start()
                controller.arm()
                triggered, response, ltp = service._wait_for_no_ladder_trigger(
                    price_fetcher=fetcher,
                    trigger_price=trigger_price,
                    final_price=trigger_price + 10.0,
                    switch_threshold=trigger_price - 20.0,
                    fast_poll_ms=poll_interval_ms,
                    slow_poll_ms=max(poll_interval_ms, 500),
                    just_buy=False,
                    just_buy_params={
                        "order_quantity": 10,
                        "interval_ms": 100,
                        "timeout": 5,
                        "pre_wait_ms": 0,
                        "max_requests": None,
                        "fade_interval_ms": None,
                        "fade_timeout": None,
                    },
                    platform_params={"symbol": symbol, "side": "BUY"},
                )
                waiter_return_time = time.perf_counter()
            finally:
                fetcher.stop()

        if not triggered or response is not None or ltp != trigger_price:
            raise RuntimeError("Trigger wake probe did not complete the simulated trigger path")
        if controller.trigger_return_time is None or publish_time is None:
            raise RuntimeError("Trigger wake probe did not capture all timestamps")

        get_return_to_publish_values.append(publish_time - controller.trigger_return_time)
        publish_to_waiter_return_values.append(waiter_return_time - publish_time)
        get_return_to_waiter_return_values.append(waiter_return_time - controller.trigger_return_time)

    return (
        summarize(get_return_to_publish_values),
        summarize(publish_to_waiter_return_values),
        summarize(get_return_to_waiter_return_values),
    )


def render_report(
    *,
    user_ids: list[str],
    symbol: str,
    trigger_price: float,
    poll_interval_ms: int,
    trigger_after_ms: float,
    iterations: int,
    get_return_to_publish: MetricStats,
    publish_to_waiter_return: MetricStats,
    get_return_to_waiter_return: MetricStats,
) -> str:
    lines = [
        "ATRAD Trigger Wake Probe",
        "=" * 72,
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        f"Users: {', '.join(user_ids)}",
        f"Symbol: {symbol}",
        f"Trigger Price: {trigger_price}",
        f"Poll Interval: {poll_interval_ms}ms",
        f"Trigger Flip Delay: {trigger_after_ms}ms",
        f"Iterations: {iterations}",
        "Mode: live-authenticated fetchers, patched get_ltp values, real threaded fetcher/waiter path",
        "=" * 72,
        f"{'metric':<32} {'median':>12} {'p95':>12} {'min':>12} {'max':>12}",
        "-" * 72,
        (
            f"{'get_ltp_return_to_publish':<32} "
            f"{get_return_to_publish.median_ms:>10.4f}ms "
            f"{get_return_to_publish.p95_ms:>10.4f}ms "
            f"{get_return_to_publish.min_ms:>10.4f}ms "
            f"{get_return_to_publish.max_ms:>10.4f}ms"
        ),
        (
            f"{'publish_to_waiter_return':<32} "
            f"{publish_to_waiter_return.median_ms:>10.4f}ms "
            f"{publish_to_waiter_return.p95_ms:>10.4f}ms "
            f"{publish_to_waiter_return.min_ms:>10.4f}ms "
            f"{publish_to_waiter_return.max_ms:>10.4f}ms"
        ),
        (
            f"{'get_ltp_return_to_waiter_return':<32} "
            f"{get_return_to_waiter_return.median_ms:>10.4f}ms "
            f"{get_return_to_waiter_return.p95_ms:>10.4f}ms "
            f"{get_return_to_waiter_return.min_ms:>10.4f}ms "
            f"{get_return_to_waiter_return.max_ms:>10.4f}ms"
        ),
        "=" * 72,
        "Definitions",
        "- get_ltp_return_to_publish: from patched client.get_ltp() returning the triggered value to entering fetcher._publish_ltp()",
        "- publish_to_waiter_return: from entering fetcher._publish_ltp() to wait_for_no_ladder_trigger() returning triggered",
        "- get_ltp_return_to_waiter_return: combined local overhead from get_ltp() return to trigger waiter completion",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure local ATRAD fetcher publish/wake overhead around trigger detection.",
    )
    parser.add_argument(
        "user_configs",
        nargs="+",
        help="One or more ATRAD user config JSON files used to authenticate the fetchers",
    )
    parser.add_argument("--symbol", default="NABIL", help="Symbol used in the simulated trigger path")
    parser.add_argument("--trigger-price", type=float, default=110.0, help="Triggered LTP value")
    parser.add_argument("--poll-interval-ms", type=int, default=5, help="Fetcher poll interval in milliseconds")
    parser.add_argument("--trigger-after-ms", type=float, default=20.0, help="Delay before patched get_ltp starts returning the triggered LTP")
    parser.add_argument("--iterations", type=int, default=200, help="Number of measurements to collect")
    parser.add_argument("--output", help="Optional output path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.iterations <= 0:
        raise SystemExit("--iterations must be greater than 0")
    if args.poll_interval_ms <= 0:
        raise SystemExit("--poll-interval-ms must be greater than 0")

    clients = load_clients(args.user_configs)
    stats = measure_real_fetcher_trigger_wake(
        clients,
        symbol=args.symbol,
        trigger_price=args.trigger_price,
        poll_interval_ms=args.poll_interval_ms,
        trigger_after_ms=args.trigger_after_ms,
        iterations=args.iterations,
    )
    report = render_report(
        user_ids=[client.user_id for client in clients],
        symbol=args.symbol,
        trigger_price=args.trigger_price,
        poll_interval_ms=args.poll_interval_ms,
        trigger_after_ms=args.trigger_after_ms,
        iterations=args.iterations,
        get_return_to_publish=stats[0],
        publish_to_waiter_return=stats[1],
        get_return_to_waiter_return=stats[2],
    )
    output_path = Path(args.output) if args.output else default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"Report written to {output_path}")


if __name__ == "__main__":
    main()
