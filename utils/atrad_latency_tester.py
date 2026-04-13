#!/usr/bin/env python3
"""Live ATRAD latency benchmarking utility."""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
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
    latency_ms: float
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
        default=5.0,
        help="Per-request timeout in seconds (default: 5.0)",
    )
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Run each probe request in its own thread with staggered spawn",
    )
    parser.add_argument(
        "--spawn-interval-ms",
        type=float,
        default=5.0,
        help="Thread spawn interval in milliseconds when --parallel is used (default: 5)",
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

    if args.endpoint in {"quote", "market", "quickwatch"} and not args.symbol:
        raise ValueError(f"--symbol is required for endpoint '{args.endpoint}'")

    if args.endpoint == "order":
        if not args.allow_live_order:
            raise ValueError(
                "Endpoint 'order' is live and unsafe. Re-run with --allow-live-order "
                "only if you explicitly want to place real ATRAD orders."
            )
        if args.parallel:
            raise ValueError("Endpoint 'order' does not support --parallel for safety reasons")
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
            success, status_code, error = _execute_probe_with_session(client.session, spec, timeout)
            latency_ms = (time.perf_counter() - start) * 1000
            collected[index] = ProbeResult(
                index=index + 1,
                latency_ms=latency_ms,
                success=success,
                status_code=status_code,
                error=error,
            )

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
            success, status_code, error = _execute_probe_with_client(client, spec, timeout)
            latency_ms = (time.perf_counter() - start) * 1000
            samples.append(
                ProbeResult(
                    index=index + 1,
                    latency_ms=latency_ms,
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


def render_report(results: list[UserLatencyResult], args: argparse.Namespace) -> str:
    def fmt(value: Optional[float]) -> str:
        return f"{value:.2f}ms" if value is not None else "N/A"

    lines = [
        "ATRAD Latency Benchmark",
        "=" * 70,
        f"Date: {datetime.now().isoformat(timespec='seconds')}",
        f"Endpoint: {args.endpoint}",
        f"Requests per user: {args.requests}",
        f"Mode: {'parallel' if args.parallel else 'sequential'}",
    ]
    if args.symbol:
        lines.append(f"Symbol: {args.symbol}")
    if args.parallel:
        lines.append(f"Spawn interval: {args.spawn_interval_ms}ms")
    lines.append("=" * 70)
    lines.append(
        f"{'user_id':<18} {'success':>9} {'failure':>9} {'avg':>12} {'min':>12} {'max':>12}"
    )
    lines.append("-" * 70)
    for result in results:
        lines.append(
            f"{result.user_id:<18} "
            f"{result.success_count:>9} "
            f"{result.failure_count:>9} "
            f"{fmt(result.average_latency_ms):>12} "
            f"{fmt(result.min_latency_ms):>12} "
            f"{fmt(result.max_latency_ms):>12}"
        )
    lines.append("=" * 70)

    return "\n".join(lines) + "\n"


def default_output_path(endpoint: str) -> Path:
    day_dir = Path("logs") / "latency" / datetime.now().strftime("%Y%m%d")
    day_dir.mkdir(parents=True, exist_ok=True)
    return day_dir / f"atrad_latency_{endpoint}_{datetime.now().strftime('%H%M%S')}.txt"


def main() -> None:
    args = parse_args()
    validate_args(args)

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

    report = render_report(results, args)
    output_path = Path(args.output) if args.output else default_output_path(args.endpoint)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(report, end="")
    print(f"Saved report to {output_path}")


if __name__ == "__main__":
    main()
