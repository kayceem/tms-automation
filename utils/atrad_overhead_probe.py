#!/usr/bin/env python3
"""Live ATRAD overhead probe for closed-market simulation."""

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

sys.path.insert(0, str(Path(__file__).parent.parent))

from api import ATRADClient
from config.models import ATRADUserConfig
from services.fetchers.atrad_price_fetcher import ATRADFetchUser, ATRADMultiUserPriceFetcher
from services.orders.atrad_order_service import ATRADOrderService
from utils.logger import get_logger


logger = get_logger(__name__)
for handler in list(logger.handlers):
    logger.removeHandler(handler)


@dataclass(frozen=True)
class MetricStats:
    count: int
    median_ms: float
    p95_ms: float
    min_ms: float
    max_ms: float


class SwitchingPriceFetcher:
    def __init__(self, ltps: list[float], detect_times: list[float], schedule_times: list[tuple[str, float]]):
        self.ltps = ltps
        self.detect_times = detect_times
        self.schedule_times = schedule_times
        self.index = 0

    def get_latest_ltp(self) -> float:
        self.detect_times.append(time.perf_counter())
        if self.index >= len(self.ltps):
            return self.ltps[-1]
        value = self.ltps[self.index]
        self.index += 1
        return value

    def update_scheduler_mode(self, scheduler_mode: str) -> None:
        self.schedule_times.append((scheduler_mode, time.perf_counter()))


class TriggerPriceFetcher:
    def __init__(self, ltp: float, trigger_times: list[float], polls_before_trigger: int = 3) -> None:
        self.ltp = ltp
        self.trigger_times = trigger_times
        self.polls_before_trigger = polls_before_trigger
        self._counter = 0

    def get_latest_ltp(self) -> float:
        if self._counter >= self.polls_before_trigger:
            self.trigger_times.append(time.perf_counter())
            return self.ltp
        self._counter += 1
        return self.ltp - 10.0

    def pause(self) -> None:
        return None

    def start_market_details(self) -> None:
        time.sleep(0.01)  # Simulate some delay in starting market details
        return None

    def stop_market_details(self) -> None:
        return None



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure local ATRAD fetcher/order overheads with live authenticated users and simulated closed-market responses.",
    )
    parser.add_argument(
        "user_configs",
        nargs="+",
        help="ATRAD user config JSON files used to authenticate live clients",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=200,
        help="Number of measurements per metric (default: 200)",
    )
    parser.add_argument(
        "--output",
        help="Optional output txt path; defaults to logs/latency/YYYYMMDD/...",
    )
    return parser.parse_args()


def default_output_path() -> Path:
    day_dir = Path("logs") / "latency" / datetime.now().strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"atrad_overhead_probe_{datetime.now().strftime('%H%M%S')}.txt"


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


def load_clients(user_paths: list[str]) -> list[ATRADClient]:
    clients: list[ATRADClient] = []
    for user_path in user_paths:
        user_config = ATRADUserConfig.from_file(user_path)
        client = ATRADClient(user_config)
        if not client.ensure_authenticated():
            raise RuntimeError(f"[{user_config.user_id}] authentication failed")
        clients.append(client)
    return clients


@contextmanager
def patched_method(obj: Any, attr: str, replacement: Callable[..., Any]):
    original = getattr(obj, attr)
    setattr(obj, attr, replacement)
    try:
        yield
    finally:
        setattr(obj, attr, original)


def measure_sequential_dispatch(client: ATRADClient, iterations: int) -> MetricStats:
    values: list[float] = []

    for _ in range(iterations):
        event = threading.Event()
        call_times: list[float] = []
        fetcher = ATRADMultiUserPriceFetcher(
            fetch_users=[ATRADFetchUser("AFU-1", client, "NABIL")],
            poll_interval_ms=5,
            requests_per_user=1,
            enable_cooldown=False,
        )
        decision_times: list[float] = []

        original_get_next_user = fetcher._get_next_user

        def wrapped_get_next_user():
            decision_times.append(time.perf_counter())
            return original_get_next_user()

        def fake_get_ltp(symbol: str, timeout: float = 0.0):
            call_times.append(time.perf_counter())
            fetcher._running = False
            event.set()
            return 123.45

        fetcher._get_next_user = wrapped_get_next_user
        with patched_method(client, "get_ltp", fake_get_ltp):
            fetcher._running = True
            fetcher._fetch_loop()

        if not event.is_set():
            raise RuntimeError("Sequential dispatch probe did not run")
        values.append(call_times[0] - decision_times[0])

    return summarize(values)


def measure_parallel_dispatch(client: ATRADClient, iterations: int, fallback: bool) -> MetricStats:
    values: list[float] = []

    for _ in range(iterations):
        event = threading.Event()
        call_times: list[float] = []
        fetcher = ATRADMultiUserPriceFetcher(
            fetch_users=[ATRADFetchUser("AFU-1", client, "NABIL")],
            poll_interval_ms=5,
            requests_per_user=1,
            enable_cooldown=False,
            scheduler_mode="parallel",
            parallel_fetch_enabled=True,
            parallel_spawn_interval_ms=10,
            parallel_cycle_timeout_ms=1,
            parallel_wait=False,
        )

        def fake_get_ltp(symbol: str, timeout: float = 0.0):
            call_times.append(time.perf_counter())
            event.set()
            return 123.45

        with patched_method(client, "get_ltp", fake_get_ltp):
            fetcher._running = True
            fetcher._parallel_seeded = True
            if fallback:
                now_ms = time.perf_counter() * 1000
                fetcher._parallel_last_dispatch_any_ms = now_ms - 5
                fetcher._parallel_last_dispatch_ms["AFU-1"] = now_ms - 5
            else:
                fetcher._parallel_completion_queue.append("AFU-1")

            started_at = time.perf_counter()
            dispatched = fetcher._dispatch_next_parallel_fetch()
            if not dispatched:
                raise RuntimeError("Parallel dispatch probe failed to dispatch")
            if not event.wait(1.0):
                raise RuntimeError("Parallel dispatch probe timed out")
            for thread in list(fetcher._parallel_dispatch_threads):
                thread.join(timeout=0.1)
            values.append(call_times[0] - started_at)

    return summarize(values)


def measure_switch_to_parallel(order_client: ATRADClient, iterations: int) -> MetricStats:
    values: list[float] = []
    service = ATRADOrderService(order_client)
    service.client.user_config.trigger_mode_parallel_fetch_enabled = True

    for _ in range(iterations):
        detect_times: list[float] = []
        schedule_times: list[tuple[str, float]] = []
        fetcher = SwitchingPriceFetcher([115.0, 120.0], detect_times, schedule_times)

        triggered, response = service._wait_for_no_ladder_trigger(
            price_fetcher=fetcher,
            trigger_price=120.0,
            final_price=130.0,
            switch_threshold=110.0,
            fast_poll_ms=100,
            slow_poll_ms=500,
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
            platform_params={"symbol": "NABIL", "side": "BUY"},
        )
        if not triggered or response is not None:
            raise RuntimeError("Switch probe did not complete the simulated trigger path")
        values.append(schedule_times[0][1] - detect_times[0])

    return summarize(values)


def measure_trigger_to_place(order_client: ATRADClient, iterations: int) -> MetricStats:
    values: list[float] = []
    service = ATRADOrderService(order_client)

    for _ in range(iterations):
        trigger_times: list[float] = []
        place_times: list[float] = []
        fetcher = TriggerPriceFetcher(110.0, trigger_times)

        def fake_place_order(symbol: str, quantity: int, price: float, side: str = "BUY", market_price: float = None, **kwargs):
            place_times.append(time.perf_counter())
            return {
                "code": "0",
                "description": "simulated",
                "symbol": symbol,
                "quantity": quantity,
                "price": price,
                "side": side,
                "market_price": market_price,
            }

        with patched_method(order_client, "place_order", fake_place_order):
            response = service._execute_no_ladder_mode(
                price_fetcher=fetcher,
                price_levels=[100.0, 110.0, 120.0],
                order_quantity=10,
                just_buy=False,
                just_buy_interval_ms=100,
                just_buy_timeout=5,
                just_buy_pre_wait_ms=0,
                just_buy_max_requests=None,
                just_buy_fade_interval_ms=None,
                just_buy_fade_timeout=None,
                platform_params={"symbol": "NABIL", "side": "BUY"},
            )
        if response is None:
            raise RuntimeError("Trigger-to-place probe returned no response")
        values.append(place_times[0] - trigger_times[0])

    return summarize(values)


def render_report(user_ids: list[str], iterations: int, metrics: list[tuple[str, MetricStats]]) -> str:
    lines = [
        "ATRAD Overhead Probe",
        "=" * 72,
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        f"Users: {', '.join(user_ids)}",
        f"Iterations per metric: {iterations}",
        "Mode: live-authenticated, closed-market simulated",
        "=" * 72,
        f"{'metric':<30} {'median':>12} {'p95':>12} {'min':>12} {'max':>12}",
        "-" * 72,
    ]
    for name, stats in metrics:
        lines.append(
            f"{name:<30} "
            f"{stats.median_ms:>10.4f}ms "
            f"{stats.p95_ms:>10.4f}ms "
            f"{stats.min_ms:>10.4f}ms "
            f"{stats.max_ms:>10.4f}ms"
        )

    lines.extend(
        [
            "=" * 72,
            "Definitions",
            "- sequential_dispatch: time from sequential fetcher choosing a user to entering client.get_ltp()",
            "- parallel_response_dispatch: time from response-driven scheduler step to entering client.get_ltp()",
            "- parallel_fallback_dispatch: time from fallback scheduler step to entering client.get_ltp()",
            "- switch_to_parallel: time from reading above-threshold LTP to calling update_scheduler_mode('parallel')",
            "- trigger_to_place: time from reading triggered LTP to entering place_order()",
            "",
            "These are local in-process overheads only. They exclude live market data latency,",
            "broker processing time, and HTTP request round-trip time.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    if args.iterations <= 0:
        raise SystemExit("--iterations must be greater than 0")

    clients = load_clients(args.user_configs)
    user_ids = [client.user_id for client in clients]

    fetch_client = clients[0]
    order_client = clients[0]

    metrics = [
        ("sequential_dispatch", measure_sequential_dispatch(fetch_client, args.iterations)),
        ("parallel_response_dispatch", measure_parallel_dispatch(fetch_client, args.iterations, fallback=False)),
        ("parallel_fallback_dispatch", measure_parallel_dispatch(fetch_client, args.iterations, fallback=True)),
        ("switch_to_parallel", measure_switch_to_parallel(order_client, args.iterations)),
        ("trigger_to_place", measure_trigger_to_place(order_client, args.iterations)),
    ]

    report = render_report(user_ids, args.iterations, metrics)
    output_path = Path(args.output) if args.output else default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"Saved report to {output_path}")


if __name__ == "__main__":
    main()
