#!/usr/bin/env python3
"""Live ATRAD latency benchmarking utility."""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import requests
sys.path.insert(0, str(Path(__file__).parent.parent))
    
from api.atrad_client import ATRADClient
from config.models import ATRADUserConfig
from utils.logger import get_logger


logger = get_logger(__name__)
for h in logger.handlers:
    logger.removeHandler(h)

ENDPOINT_CHOICES = ("quote", "market", "orderbook", "quickwatch", "order")
READ_ONLY_ENDPOINTS = {"quote", "market", "orderbook", "quickwatch"}


@dataclass(frozen=True)
class ProbeSpec:
    method: str
    url: str
    data: Optional[str] = None


@dataclass(frozen=True)
class ProbeResult:
    index: int
    user_id: str
    sent_at_ms: float
    sent_wall_ms: float
    latency_ms: float
    completed_at_ms: float
    completed_wall_ms: float
    success: bool
    status_code: Optional[int]
    error: Optional[str] = None


@dataclass(frozen=True)
class UserLatencyResult:
    user_id: str
    endpoint: str
    request_count: int
    parallel: bool
    samples: list[ProbeResult]

    @property
    def success_count(self) -> int:
        return sum(1 for sample in self.samples if sample.success)

    @property
    def failure_count(self) -> int:
        return self.request_count - self.success_count

    @property
    def successful_latencies(self) -> list[float]:
        return [sample.latency_ms for sample in self.samples if sample.success]

    @property
    def average_latency_ms(self) -> Optional[float]:
        values = self.successful_latencies
        return statistics.mean(values) if values else None

    @property
    def min_latency_ms(self) -> Optional[float]:
        values = self.successful_latencies
        return min(values) if values else None

    @property
    def max_latency_ms(self) -> Optional[float]:
        values = self.successful_latencies
        return max(values) if values else None

    @property
    def average_time_between_responses_ms(self) -> float:
        if self.request_count <= 1 or len(self.samples) <= 1:
            return 0.0
        ordered = sorted(self.samples, key=lambda sample: sample.completed_at_ms)
        gap_total = 0.0
        for previous, current in zip(ordered, ordered[1:]):
            gap_total += current.completed_at_ms - previous.completed_at_ms
        return gap_total / self.request_count

    @property
    def samples_by_response_time(self) -> list[ProbeResult]:
        return sorted(self.samples, key=lambda sample: sample.completed_at_ms)


@dataclass(frozen=True)
class CycleBenchmarkResult:
    user_results: list[UserLatencyResult]
    cycle_samples: list[ProbeResult]


def _average_request_interval_ms(samples: list[ProbeResult]) -> float:
    if len(samples) <= 1:
        return 0.0
    ordered = sorted(samples, key=lambda sample: sample.sent_at_ms)
    gap_total = 0.0
    for previous, current in zip(ordered, ordered[1:]):
        gap_total += current.sent_at_ms - previous.sent_at_ms
    return gap_total / len(samples)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark live ATRAD endpoint latency for one or more users.",
    )
    parser.add_argument(
        "user_configs",
        nargs="+",
        help="ATRAD user JSON files to benchmark one by one",
    )
    parser.add_argument(
        "--endpoint",
        required=True,
        choices=ENDPOINT_CHOICES,
        help="Endpoint to benchmark: quote, market, orderbook, quickwatch, order",
    )
    parser.add_argument(
        "--symbol",
        help="Security symbol required for quote, market, quickwatch, and order probes",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=30,
        help="Number of requests per user (default: 30)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=0.15,
        help="Per-request timeout in seconds (default: 0.15)",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run each probe request in its own thread with staggered spawn",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Enforce a strict global minimum gap of --spawn-interval-ms between dispatches",
    )
    parser.add_argument(
        "--cycle-users",
        action="store_true",
        help="Cycle requests across all users in one pooled stream instead of benchmarking users separately",
    )
    parser.add_argument(
        "--spawn-interval-ms",
        type=float,
        default=5.0,
        help="Thread spawn interval in milliseconds when --parallel is used (default: 5)",
    )
    parser.add_argument(
        "--cycle-timeout-ms",
        type=float,
        default=20.0,
        help="No-response timeout in milliseconds for --cycle-users parallel scheduling (default: 20)",
    )
    parser.add_argument(
        "--output",
        help="Optional output txt path; defaults to logs/latency/YYYYMMDD/...",
    )
    parser.add_argument(
        "--allow-live-order",
        action="store_true",
        help="Allow live submitOrder latency probing. Dangerous: can place real orders.",
    )
    parser.add_argument("--price", type=float, help="Required for --endpoint order")
    parser.add_argument("--quantity", type=int, help="Required for --endpoint order")
    parser.add_argument(
        "--side",
        choices=("BUY", "SELL"),
        default="BUY",
        help="Order side for --endpoint order (default: BUY)",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.requests <= 0:
        raise ValueError("--requests must be greater than 0")
    if args.timeout <= 0:
        raise ValueError("--timeout must be greater than 0")
    if args.parallel and args.spawn_interval_ms < 0:
        raise ValueError("--spawn-interval-ms must be 0 or greater")
    if args.cycle_users and args.cycle_timeout_ms <= 0:
        raise ValueError("--cycle-timeout-ms must be greater than 0")
    if args.wait and not args.parallel:
        raise ValueError("--wait requires --parallel")

    if args.endpoint in {"quote", "market", "quickwatch"} and not args.symbol:
        raise ValueError(f"--symbol is required for endpoint '{args.endpoint}'")

    if args.endpoint == "order":
        if not args.allow_live_order:
            raise ValueError(
                "Endpoint 'order' is live and unsafe. Re-run with --allow-live-order "
                "only if you explicitly want to place real ATRAD orders."
            )
        if args.parallel and args.cycle_users:
            raise ValueError(
                "Endpoint 'order' does not support --parallel with --cycle-users for safety reasons"
            )
        for field_name in ("symbol", "price", "quantity"):
            if getattr(args, field_name) in (None, ""):
                raise ValueError(f"--{field_name} is required for endpoint 'order'")


def _build_order_probe_data(client: ATRADClient, *, symbol: str, price: float, quantity: int, side: str) -> str:
    action_select = "2" if side.upper() == "SELL" else "1"
    dynamic_fields = {
        "marketPrice": f"{price:.1f}",
        "duplicateOrderId": client._generate_duplicate_order_id(),
        "actionSelect": action_select,
        "txtSecurity": symbol,
        "spnQuantity": str(quantity),
        "spnPrice": f"{price:.1f}",
    }
    dynamic_parts = []
    for key, value in dynamic_fields.items():
        dynamic_parts.append(f"{key}={quote(str(value), safe='')}")
    return client._static_body + "&" + "&".join(dynamic_parts)


def build_probe_spec(
    client: ATRADClient,
    *,
    endpoint: str,
    symbol: Optional[str],
    price: Optional[float],
    quantity: Optional[int],
    side: str,
) -> ProbeSpec:
    cache_bust = str(client._epoch_time_ms())
    if endpoint == "quote":
        return ProbeSpec(
            method="GET",
            url=f"{client.quote_endpoint}&securityid={symbol}&dojo.preventCache={cache_bust}",
        )
    if endpoint == "market":
        return ProbeSpec(
            method="GET",
            url=f"{client.market_endpoint}&security={symbol}&dojo.preventCache={cache_bust}",
        )
    if endpoint == "orderbook":
        return ProbeSpec(
            method="GET",
            url=f"{client.order_book_endpoint}&dojo.preventCache={cache_bust}",
        )
    if endpoint == "quickwatch":
        watch_id = client.user_config._watch_id or client.session.cookies.get("watchID")
        if not watch_id:
            raise ValueError(f"[{client.user_id}] quickwatch requires watchID after login")
        return ProbeSpec(
            method="GET",
            url=(
                f"{client.quick_watch_endpoint}&securityid={symbol}"
                f"&watchId={watch_id}&dojo.preventCache={cache_bust}"
            ),
        )
    if endpoint == "order":
        return ProbeSpec(
            method="POST",
            url=client.order_endpoint,
            data=_build_order_probe_data(
                client,
                symbol=str(symbol),
                price=float(price),
                quantity=int(quantity),
                side=side,
            ),
        )
    raise ValueError(f"Unsupported endpoint: {endpoint}")


def _is_success_response(response: requests.Response) -> bool:
    if response.status_code != 200:
        return False
    lowered = response.text.lower()
    if "<html" in lowered:
        return False
    return True


def _execute_probe_with_client(client: ATRADClient, spec: ProbeSpec, timeout: float) -> tuple[bool, Optional[int], Optional[str]]:
    response = client._request_with_reauth(spec.method, spec.url, timeout=timeout, data=spec.data)
    if response is None:
        return False, None, "no response"
    if not _is_success_response(response):
        return False, response.status_code, "unexpected response"
    return True, response.status_code, None


def _execute_probe_with_session(session: requests.Session, spec: ProbeSpec, timeout: float) -> tuple[bool, Optional[int], Optional[str]]:
    try:
        response = session.request(spec.method, spec.url, timeout=timeout, data=spec.data)
    except requests.exceptions.RequestException as exc:
        return False, None, str(exc)
    if not _is_success_response(response):
        return False, response.status_code, "unexpected response"
    return True, response.status_code, None


def benchmark_user(
    user_path: str,
    *,
    endpoint: str,
    symbol: Optional[str],
    request_count: int,
    timeout: float,
    parallel: bool,
    spawn_interval_ms: float,
    allow_live_order: bool,
    price: Optional[float],
    quantity: Optional[int],
    side: str,
) -> UserLatencyResult:
    user_config = ATRADUserConfig.from_file(user_path)
    client = ATRADClient(user_config)
    if not client.ensure_authenticated():
        raise RuntimeError(f"[{user_config.user_id}] authentication failed")

    if endpoint == "order" and not allow_live_order:
        raise ValueError("Live order probing is disabled")

    logger.info(
        f"[{user_config.user_id}] Starting latency benchmark: endpoint={endpoint}, "
        f"requests={request_count}, parallel={parallel}"
    )

    samples: list[ProbeResult] = []

    if parallel:
        collected: list[ProbeResult | None] = [None] * request_count
        threads = []

        def run_probe(index: int) -> None:
            spec = build_probe_spec(
                client,
                endpoint=endpoint,
                symbol=symbol,
                price=price,
                quantity=quantity,
                side=side,
            )
            start = time.perf_counter()
            sent_at_ms = start * 1000
            sent_wall_ms = time.time() * 1000
            success, status_code, error = _execute_probe_with_session(client.session, spec, timeout)
            completed_at_ms = time.perf_counter() * 1000
            completed_wall_ms = time.time() * 1000
            latency_ms = completed_at_ms - (start * 1000)
            collected[index] = ProbeResult(
                index=index + 1,
                user_id=user_config.user_id,
                sent_at_ms=sent_at_ms,
                sent_wall_ms=sent_wall_ms,
                latency_ms=latency_ms,
                completed_at_ms=completed_at_ms,
                completed_wall_ms=completed_wall_ms,
                success=success,
                status_code=status_code,
                error=error,
            )

        if endpoint == "order":
            max_in_flight = 2
            sem = threading.Semaphore(max_in_flight)

            def run_probe_bounded(index: int) -> None:
                try:
                    run_probe(index)
                finally:
                    sem.release()

            for index in range(request_count):
                sem.acquire()
                thread = threading.Thread(
                    target=run_probe_bounded,
                    args=(index,),
                    name=f"{user_config.user_id}-probe-{index + 1}",
                )
                threads.append(thread)
                thread.start()
                if index == 0 and request_count > 1:
                    time.sleep(spawn_interval_ms / 1000.0)
        else:
            for index in range(request_count):
                thread = threading.Thread(
                    target=run_probe,
                    args=(index,),
                    name=f"{user_config.user_id}-probe-{index + 1}",
                )
                threads.append(thread)
                thread.start()
                time.sleep(spawn_interval_ms / 1000.0)

        for thread in threads:
            thread.join()

        samples = [sample for sample in collected if sample is not None]
    else:
        for index in range(request_count):
            spec = build_probe_spec(
                client,
                endpoint=endpoint,
                symbol=symbol,
                price=price,
                quantity=quantity,
                side=side,
            )
            start = time.perf_counter()
            sent_at_ms = start * 1000
            sent_wall_ms = time.time() * 1000
            success, status_code, error = _execute_probe_with_client(client, spec, timeout)
            completed_at_ms = time.perf_counter() * 1000
            completed_wall_ms = time.time() * 1000
            latency_ms = completed_at_ms - (start * 1000)
            samples.append(
                ProbeResult(
                    index=index + 1,
                    user_id=user_config.user_id,
                    sent_at_ms=sent_at_ms,
                    sent_wall_ms=sent_wall_ms,
                    latency_ms=latency_ms,
                    completed_at_ms=completed_at_ms,
                    completed_wall_ms=completed_wall_ms,
                    success=success,
                    status_code=status_code,
                    error=error,
                )
            )

    samples.sort(key=lambda sample: sample.index)
    return UserLatencyResult(
        user_id=user_config.user_id,
        endpoint=endpoint,
        request_count=request_count,
        parallel=parallel,
        samples=samples,
    )


def benchmark_cycle_users(
    user_paths: list[str],
    *,
    endpoint: str,
    symbol: Optional[str],
    request_count: int,
    timeout: float,
    parallel: bool,
    spawn_interval_ms: float,
    cycle_timeout_ms: float,
    wait: bool,
    allow_live_order: bool,
    price: Optional[float],
    quantity: Optional[int],
    side: str,
) -> CycleBenchmarkResult:
    clients: list[ATRADClient] = []
    per_user_samples: dict[str, list[ProbeResult]] = {}
    last_dispatch_ms: dict[str, float] = {}
    sent_counts: dict[str, int] = {}

    for user_path in user_paths:
        user_config = ATRADUserConfig.from_file(user_path)
        client = ATRADClient(user_config)
        if not client.ensure_authenticated():
            raise RuntimeError(f"[{user_config.user_id}] authentication failed")
        clients.append(client)
        per_user_samples[user_config.user_id] = []
        last_dispatch_ms[user_config.user_id] = 0.0
        sent_counts[user_config.user_id] = 0

    if endpoint == "order" and not allow_live_order:
        raise ValueError("Live order probing is disabled")

    total_target = request_count
    cycle_samples: list[ProbeResult] = []

    if not parallel:
        probe_index = 0
        client_index = 0
        while probe_index < total_target:
            client = clients[client_index % len(clients)]
            client_index += 1

            spec = build_probe_spec(
                client,
                endpoint=endpoint,
                symbol=symbol,
                price=price,
                quantity=quantity,
                side=side,
            )
            sent_counts[client.user_id] += 1
            start = time.perf_counter()
            sent_at_ms = start * 1000
            sent_wall_ms = time.time() * 1000
            success, status_code, error = _execute_probe_with_client(client, spec, timeout)
            completed_at_ms = time.perf_counter() * 1000
            completed_wall_ms = time.time() * 1000
            latency_ms = completed_at_ms - (start * 1000)
            probe_index += 1
            sample = ProbeResult(
                index=probe_index,
                user_id=client.user_id,
                sent_at_ms=sent_at_ms,
                sent_wall_ms=sent_wall_ms,
                latency_ms=latency_ms,
                completed_at_ms=completed_at_ms,
                completed_wall_ms=completed_wall_ms,
                success=success,
                status_code=status_code,
                error=error,
            )
            per_user_samples[client.user_id].append(sample)
            cycle_samples.append(sample)
    else:
        state_lock = threading.Lock()
        completion_queue: deque[str] = deque()
        threads: list[threading.Thread] = []
        probe_counter = 0
        completed_count = 0
        last_spawn_wall_ms = 0.0
        last_dispatch_any_ms = 0.0

        def dispatch_probe(client: ATRADClient) -> bool:
            nonlocal probe_counter, last_spawn_wall_ms, last_dispatch_any_ms
            with state_lock:
                if probe_counter >= total_target:
                    return False
                now_ms = time.perf_counter() * 1000
                if wait and last_dispatch_any_ms and (now_ms - last_dispatch_any_ms) < spawn_interval_ms:
                    return False
                probe_counter += 1
                probe_index = probe_counter
                sent_counts[client.user_id] += 1
                last_dispatch_ms[client.user_id] = now_ms
                last_spawn_wall_ms = last_dispatch_ms[client.user_id]
                last_dispatch_any_ms = now_ms

            def run_probe() -> None:
                nonlocal completed_count
                spec = build_probe_spec(
                    client,
                    endpoint=endpoint,
                    symbol=symbol,
                    price=price,
                    quantity=quantity,
                    side=side,
                )
                start = time.perf_counter()
                sent_at_ms = start * 1000
                sent_wall_ms = time.time() * 1000
                success, status_code, error = _execute_probe_with_session(client.session, spec, timeout)
                completed_at_ms = time.perf_counter() * 1000
                completed_wall_ms = time.time() * 1000
                latency_ms = completed_at_ms - (start * 1000)
                sample = ProbeResult(
                    index=probe_index,
                    user_id=client.user_id,
                    sent_at_ms=sent_at_ms,
                    sent_wall_ms=sent_wall_ms,
                    latency_ms=latency_ms,
                    completed_at_ms=completed_at_ms,
                    completed_wall_ms=completed_wall_ms,
                    success=success,
                    status_code=status_code,
                    error=error,
                )
                with state_lock:
                    per_user_samples[client.user_id].append(sample)
                    cycle_samples.append(sample)
                    completed_count += 1
                    completion_queue.append(client.user_id)

            thread = threading.Thread(
                target=run_probe,
                name=f"{client.user_id}-cycle-probe-{probe_index}",
            )
            threads.append(thread)
            thread.start()
            return True

        for client in clients[:total_target]:
            dispatch_probe(client)
            time.sleep(spawn_interval_ms / 1000.0)

        while True:
            with state_lock:
                if completed_count >= total_target:
                    break
                completed_user_id = completion_queue.popleft() if completion_queue else None

            if completed_user_id is not None:
                client = next(item for item in clients if item.user_id == completed_user_id)
                if dispatch_probe(client):
                    continue

            now_ms = time.perf_counter() * 1000
            timeout_threshold_ms = spawn_interval_ms if wait else cycle_timeout_ms
            if now_ms - last_spawn_wall_ms >= timeout_threshold_ms:
                with state_lock:
                    eligible_clients = sorted(
                        clients,
                        key=lambda client: last_dispatch_ms[client.user_id],
                    )
                if eligible_clients:
                    dispatch_probe(eligible_clients[0])
                    continue

            time.sleep(0.001)

        for thread in threads:
            thread.join()

    user_results = [
        UserLatencyResult(
            user_id=client.user_id,
            endpoint=endpoint,
            request_count=len(per_user_samples[client.user_id]),
            parallel=parallel,
            samples=sorted(per_user_samples[client.user_id], key=lambda sample: sample.index),
        )
        for client in clients
    ]

    return CycleBenchmarkResult(
        user_results=user_results,
        cycle_samples=sorted(cycle_samples, key=lambda sample: sample.completed_at_ms),
    )


def render_report(
    results: list[UserLatencyResult],
    args: argparse.Namespace,
    cycle_samples: list[ProbeResult] | None = None,
) -> str:
    def fmt(value: Optional[float]) -> str:
        return f"{value:.2f}ms" if value is not None else "N/A"

    def fmt_wall(ms: float) -> str:
        return datetime.fromtimestamp(ms / 1000).strftime("%H:%M:%S.%f")[:-3]

    def aggregate_cycle_results() -> UserLatencyResult:
        return UserLatencyResult(
            user_id="ALL_USERS",
            endpoint=args.endpoint,
            request_count=len(cycle_samples or []),
            parallel=args.parallel,
            samples=list(cycle_samples or []),
        )

    lines = [
        "ATRAD Latency Benchmark",
        "=" * 70,
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        f"Endpoint: {args.endpoint}",
        (
            f"Requests total: {args.requests}"
            if getattr(args, "cycle_users", False)
            else f"Requests per user: {args.requests}"
        ),
        f"Mode: {'parallel' if args.parallel else 'sequential'}",
        f"Scheduling: {'cycle-users' if getattr(args, 'cycle_users', False) else 'per-user'}",
    ]
    if args.symbol:
        lines.append(f"Symbol: {args.symbol}")
    if args.parallel:
        lines.append(f"Spawn interval: {args.spawn_interval_ms}ms")
    if getattr(args, "cycle_users", False) and args.parallel:
        lines.append(f"Cycle timeout: {args.cycle_timeout_ms}ms")
    if args.wait:
        lines.append("Strict wait: enabled")
    lines.append("=" * 70)
    summary_results = [aggregate_cycle_results()] if cycle_samples is not None else results
    lines.append(
        f"{'user_id':<18} {'success':>9} {'failure':>9} {'avg':>12} {'min':>12} {'max':>12} {'resp_gap':>12}"
    )
    lines.append("-" * 70)
    for result in summary_results:
        lines.append(
            f"{result.user_id:<18} "
            f"{result.success_count:>9} "
            f"{result.failure_count:>9} "
            f"{fmt(result.average_latency_ms):>12} "
            f"{fmt(result.min_latency_ms):>12} "
            f"{fmt(result.max_latency_ms):>12} "
            f"{fmt(result.average_time_between_responses_ms):>12}"
        )
    lines.append("=" * 70)

    if cycle_samples is not None:
        lines.append("Cycle Request Interval By User")
        lines.append("-" * 70)
        lines.append(f"{'user_id':<18} {'avg_req_interval':>18}")
        lines.append("-" * 70)
        for result in results:
            lines.append(
                f"{result.user_id:<18} "
                f"{fmt(_average_request_interval_ms(result.samples)):>18}"
            )
        lines.append("=" * 70)

        lines.append("Cycle Response Timeline")
        lines.append("-" * 70)
        lines.append(
            f"{'recv#':<8} {'probe#':<8} {'user':<18} {'req_time':>14} {'req_at':>12} {'recv_time':>14} {'recv_at':>12} {'recv_at_interval':>18} {'latency':>12} {'status':>8} {'result':>10}"
        )
        if cycle_samples:
            base_sent_at_ms = min(sample.sent_at_ms for sample in cycle_samples)
        else:
            base_sent_at_ms = 0.0
        previous_completed_at_ms = base_sent_at_ms
        for receive_index, sample in enumerate(cycle_samples, start=1):
            request_offset_ms = sample.sent_at_ms - base_sent_at_ms
            receive_offset_ms = sample.completed_at_ms - base_sent_at_ms
            receive_interval_ms = sample.completed_at_ms - previous_completed_at_ms
            lines.append(
                f"{receive_index:<8} "
                f"{sample.index:<8} "
                f"{sample.user_id:<18} "
                f"{fmt_wall(sample.sent_wall_ms):>14} "
                f"{request_offset_ms:>10.2f}ms "
                f"{fmt_wall(sample.completed_wall_ms):>14} "
                f"{receive_offset_ms:>10.2f}ms "
                f"{receive_interval_ms:>16.2f}ms "
                f"{sample.latency_ms:>10.2f}ms "
                f"{str(sample.status_code or '-'):>8} "
                f"{('ok' if sample.success else 'fail'):>10}"
            )
            previous_completed_at_ms = sample.completed_at_ms
        lines.append("=" * 70)
    else:
        for result in results:
            lines.append(f"Response Timeline :: {result.user_id}")
            lines.append("-" * 70)
            lines.append(
                f"{'recv#':<8} {'probe#':<8} {'req_time':>14} {'req_at':>12} {'recv_time':>14} {'recv_at':>12} {'recv_at_interval':>18} {'latency':>12} {'status':>8} {'result':>10}"
            )
            if result.samples_by_response_time:
                base_sent_at_ms = min(sample.sent_at_ms for sample in result.samples_by_response_time)
            else:
                base_sent_at_ms = 0.0
            previous_completed_at_ms = base_sent_at_ms
            for receive_index, sample in enumerate(result.samples_by_response_time, start=1):
                request_offset_ms = sample.sent_at_ms - base_sent_at_ms
                receive_offset_ms = sample.completed_at_ms - base_sent_at_ms
                receive_interval_ms = sample.completed_at_ms - previous_completed_at_ms
                lines.append(
                    f"{receive_index:<8} "
                    f"{sample.index:<8} "
                    f"{fmt_wall(sample.sent_wall_ms):>14} "
                    f"{request_offset_ms:>10.2f}ms "
                    f"{fmt_wall(sample.completed_wall_ms):>14} "
                    f"{receive_offset_ms:>10.2f}ms "
                    f"{receive_interval_ms:>16.2f}ms "
                    f"{sample.latency_ms:>10.2f}ms "
                    f"{str(sample.status_code or '-'):>8} "
                    f"{('ok' if sample.success else 'fail'):>10}"
                )
                previous_completed_at_ms = sample.completed_at_ms
            lines.append("=" * 70)

    return "\n".join(lines) + "\n"


def default_output_path(endpoint: str) -> Path:
    day_dir = Path("logs") / "latency" / datetime.now().strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"atrad_latency_{endpoint}_{datetime.now().strftime('%H%M%S')}.txt"


def main() -> None:
    args = parse_args()
    validate_args(args)

    cycle_samples: list[ProbeResult] | None = None
    if args.cycle_users:
        cycle_result = benchmark_cycle_users(
            user_paths=args.user_configs,
            endpoint=args.endpoint,
            symbol=args.symbol,
            request_count=args.requests,
            timeout=args.timeout,
            parallel=args.parallel,
            spawn_interval_ms=args.spawn_interval_ms,
            cycle_timeout_ms=args.cycle_timeout_ms,
            wait=args.wait,
            allow_live_order=args.allow_live_order,
            price=args.price,
            quantity=args.quantity,
            side=args.side,
        )
        results = cycle_result.user_results
        cycle_samples = cycle_result.cycle_samples
    else:
        results = []
        for user_path in args.user_configs:
            results.append(
                benchmark_user(
                    user_path=user_path,
                    endpoint=args.endpoint,
                    symbol=args.symbol,
                    request_count=args.requests,
                    timeout=args.timeout,
                    parallel=args.parallel,
                    spawn_interval_ms=args.spawn_interval_ms,
                    allow_live_order=args.allow_live_order,
                    price=args.price,
                    quantity=args.quantity,
                    side=args.side,
                )
            )

    report = render_report(results, args, cycle_samples=cycle_samples)
    output_path = Path(args.output) if args.output else default_output_path(args.endpoint)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"Saved report to {output_path}")


if __name__ == "__main__":
    main()
