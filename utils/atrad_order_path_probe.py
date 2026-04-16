#!/usr/bin/env python3
"""Measure ATRAD trigger-to-request overhead on the current order path."""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import requests

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


class TriggerPriceFetcher:
    """Synthetic fetcher that timestamps both price availability and trigger detection."""

    def __init__(
        self,
        ltp: float,
        trigger_times: list[float],
        *,
        trigger_available_times: list[float],
        trigger_after_ms: float,
    ) -> None:
        self.ltp = ltp
        self.trigger_times = trigger_times
        self.trigger_available_times = trigger_available_times
        self.trigger_after_ms = trigger_after_ms
        self._trigger_available = False
        self._ltp: float = self.ltp - 10.0
        self._ltp_version = 0
        self._availability_lock = threading.Lock()
        self._price_update_condition = threading.Condition(self._availability_lock)
        self._availability_thread = threading.Thread(target=self._make_trigger_available, daemon=True)
        self._availability_thread.start()

    def _make_trigger_available(self) -> None:
        time.sleep(max(self.trigger_after_ms, 0.0) / 1000.0)
        with self._price_update_condition:
            self._trigger_available = True
            self._ltp = self.ltp
            self._ltp_version += 1
            self.trigger_available_times.append(time.perf_counter())
            self._price_update_condition.notify_all()

    def get_latest_ltp(self) -> float:
        with self._availability_lock:
            trigger_available = self._trigger_available
            ltp = self._ltp
        if trigger_available:
            self.trigger_times.append(time.perf_counter())
        return ltp

    def get_price_update_version(self) -> int:
        with self._availability_lock:
            return self._ltp_version

    def wait_for_price_update(
        self,
        last_seen_version: int,
        timeout_seconds: float | None = None,
    ) -> tuple[float, int]:
        with self._price_update_condition:
            if self._ltp_version <= last_seen_version:
                self._price_update_condition.wait(timeout=timeout_seconds)
            if self._trigger_available and self._ltp_version > last_seen_version:
                self.trigger_times.append(time.perf_counter())
            return self._ltp, self._ltp_version

    def pause(self) -> None:
        return None

    def start_market_details(self) -> None:
        return None

    def stop_market_details(self) -> None:
        return None


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


def make_fake_response() -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = b'{"code":"0","description":"simulated"}'
    response.encoding = "utf-8"
    return response


def default_output_path() -> Path:
    day_dir = Path("logs") / "latency" / datetime.now().strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"atrad_order_path_probe_{datetime.now().strftime('%H%M%S')}.txt"


def load_client(user_config_path: str) -> ATRADClient:
    config = ATRADUserConfig.from_file(user_config_path)
    client = ATRADClient(config)
    if not client.ensure_authenticated():
        raise RuntimeError(f"[{config.user_id}] authentication failed")
    return client


def measure_trigger_to_session_request(
    client: ATRADClient,
    *,
    symbol: str,
    trigger_price: float,
    final_price: float,
    quantity: int,
    side: str,
    iterations: int,
    trigger_after_ms: float,
) -> tuple[MetricStats, MetricStats, MetricStats]:
    service = ATRADOrderService(client)
    price_update_to_detect_values: list[float] = []
    trigger_to_request_values: list[float] = []
    place_to_request_values: list[float] = []

    for _ in range(iterations):
        trigger_available_times: list[float] = []
        trigger_times: list[float] = []
        place_order_entry_times: list[float] = []
        request_entry_times: list[float] = []
        fetcher = TriggerPriceFetcher(
            trigger_price,
            trigger_times,
            trigger_available_times=trigger_available_times,
            trigger_after_ms=trigger_after_ms,
        )

        original_place_order = client.place_order
        original_session_request = client.session.request

        def wrapped_session_request(method: str, url: str, timeout: float = 5.0, **request_kwargs: Any):
            request_entry_times.append(time.perf_counter())
            return make_fake_response()

        def wrapped_place_order(*args: Any, **kwargs: Any):
            place_order_entry_times.append(time.perf_counter())
            with patched_method(client.session, "request", wrapped_session_request):
                return original_place_order(*args, **kwargs)

        with patched_method(client, "place_order", wrapped_place_order):
            response = service._execute_no_ladder_mode(
                price_fetcher=fetcher,
                price_levels=[trigger_price - 10.0, trigger_price, final_price],
                order_quantity=quantity,
                just_buy=False,
                just_buy_interval_ms=100,
                just_buy_timeout=5,
                just_buy_pre_wait_ms=0,
                just_buy_max_requests=None,
                just_buy_fade_interval_ms=None,
                just_buy_fade_timeout=None,
                platform_params={"symbol": symbol, "side": side},
            )

        client.session.request = original_session_request

        if response is None:
            raise RuntimeError("Probe returned no response")
        if not trigger_available_times or not trigger_times or not request_entry_times or not place_order_entry_times:
            raise RuntimeError("Probe did not capture all timestamps")

        price_update_to_detect_values.append(trigger_times[0] - trigger_available_times[0])
        trigger_to_request_values.append(request_entry_times[0] - trigger_times[0])
        place_to_request_values.append(request_entry_times[0] - place_order_entry_times[0])

    return (
        summarize(price_update_to_detect_values),
        summarize(trigger_to_request_values),
        summarize(place_to_request_values),
    )


def render_report(
    *,
    user_id: str,
    symbol: str,
    side: str,
    quantity: int,
    trigger_price: float,
    final_price: float,
    iterations: int,
    price_update_to_detect: MetricStats,
    trigger_to_request: MetricStats,
    place_to_request: MetricStats,
) -> str:
    lines = [
        "ATRAD Order Path Probe",
        "=" * 72,
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        f"User: {user_id}",
        f"Symbol: {symbol}",
        f"Side: {side}",
        f"Quantity: {quantity}",
        f"Trigger Price: {trigger_price}",
        f"Final Order Price: {final_price}",
        f"Iterations: {iterations}",
        "Mode: live-authenticated, no live order sent, session.request intercepted",
        "=" * 72,
        f"{'metric':<30} {'median':>12} {'p95':>12} {'min':>12} {'max':>12}",
        "-" * 72,
        (
            f"{'price_update_to_trigger_detect':<30} "
            f"{price_update_to_detect.median_ms:>10.4f}ms "
            f"{price_update_to_detect.p95_ms:>10.4f}ms "
            f"{price_update_to_detect.min_ms:>10.4f}ms "
            f"{price_update_to_detect.max_ms:>10.4f}ms"
        ),
        (
            f"{'trigger_to_session_request':<30} "
            f"{trigger_to_request.median_ms:>10.4f}ms "
            f"{trigger_to_request.p95_ms:>10.4f}ms "
            f"{trigger_to_request.min_ms:>10.4f}ms "
            f"{trigger_to_request.max_ms:>10.4f}ms"
        ),
        (
            f"{'place_order_to_session_request':<30} "
            f"{place_to_request.median_ms:>10.4f}ms "
            f"{place_to_request.p95_ms:>10.4f}ms "
            f"{place_to_request.min_ms:>10.4f}ms "
            f"{place_to_request.max_ms:>10.4f}ms"
        ),
        "=" * 72,
        "Definitions",
        "- price_update_to_trigger_detect: from the synthetic price source becoming triggered to the event-driven trigger waiter receiving that triggered LTP update",
        "- trigger_to_session_request: from the triggered LTP read to entering client.session.request(...)",
        "- place_order_to_session_request: from entering ATRADClient.place_order(...) to entering client.session.request(...)",
        "",
        "This measures local in-process order-path overhead only.",
        "It excludes network RTT and broker-side processing because session.request is intercepted.",
        "",
    ]
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure ATRAD trigger-to-session.request overhead on the current order path.",
    )
    parser.add_argument("user_config", help="ATRAD user config JSON used to authenticate the order client")
    parser.add_argument("--symbol", default="NABIL", help="Symbol used in the simulated order path")
    parser.add_argument("--side", default="BUY", choices=["BUY", "SELL"], help="Order side")
    parser.add_argument("--quantity", type=int, default=10, help="Order quantity")
    parser.add_argument("--trigger-price", type=float, default=110.0, help="Simulated trigger price")
    parser.add_argument("--final-price", type=float, default=120.0, help="Final order price submitted after trigger")
    parser.add_argument("--iterations", type=int, default=200, help="Number of measurements to collect")
    parser.add_argument(
        "--trigger-after-ms",
        type=float,
        default=5.0,
        help="Delay before the synthetic price source flips into the triggered state",
    )
    parser.add_argument("--output", help="Optional report path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = load_client(args.user_config)
    price_update_to_detect, trigger_to_request, place_to_request = measure_trigger_to_session_request(
        client,
        symbol=args.symbol,
        trigger_price=args.trigger_price,
        final_price=args.final_price,
        quantity=args.quantity,
        side=args.side,
        iterations=args.iterations,
        trigger_after_ms=args.trigger_after_ms,
    )
    report = render_report(
        user_id=client.user_id,
        symbol=args.symbol,
        side=args.side,
        quantity=args.quantity,
        trigger_price=args.trigger_price,
        final_price=args.final_price,
        iterations=args.iterations,
        price_update_to_detect=price_update_to_detect,
        trigger_to_request=trigger_to_request,
        place_to_request=place_to_request,
    )
    output_path = Path(args.output) if args.output else default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"Report written to {output_path}")


if __name__ == "__main__":
    main()
