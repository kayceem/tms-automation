#!/usr/bin/env python3
"""Run real-code ATRAD debug scenarios against the local debug server."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Scenario:
    name: str
    queue_id: int
    kind: str
    order_ids: list[str]
    tickers: list[str]


@dataclass(frozen=True)
class ScenarioResult:
    scenario_name: str
    kind: str
    order_ids: list[str]
    tickers: list[str]
    return_code: int
    duration_seconds: float
    selected_success_ids: list[str]
    selected_failed_ids: list[str]
    server_order_attempts: int
    server_order_accepts: int
    stdout_path: str
    stderr_path: str
    server_state_path: str

    @property
    def passed(self) -> bool:
        return self.return_code == 0 and not self.selected_failed_ids and len(self.selected_success_ids) == len(self.order_ids)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run real-code ATRAD scenarios against utils/atrad_debug_server.py")
    parser.add_argument("--order-store", required=True, help="Source order store JSON")
    parser.add_argument("--user-config", help="Main user config for non-pooled scenarios")
    parser.add_argument("--pool-users", nargs="+", help="Pool user configs for pooled order-store execution")
    parser.add_argument("--fetch-users", nargs="+", help="Fetch user configs for non-pooled trigger scenarios")
    parser.add_argument("--just-buy-users", nargs="+", help="Optional global just-buy user configs")
    parser.add_argument("--atrad-fetch", action="store_true", help="Pass --atrad-fetch to main.py")
    parser.add_argument("--include-full-store", action="store_true", help="Also run one scenario with the full executable store")
    parser.add_argument("--scenario", action="append", help="Run only the named scenario(s)")
    parser.add_argument("--server-host", default="127.0.0.1")
    parser.add_argument("--server-port", type=int, default=8010)
    parser.add_argument("--min-delay-ms", type=float, default=6.0)
    parser.add_argument("--max-delay-ms", type=float, default=15.0)
    parser.add_argument("--requests-per-step", type=int, default=100)
    parser.add_argument("--order-accept-after-requests", type=int, default=10)
    parser.add_argument("--inactivity-reset-seconds", type=float, default=5.0)
    parser.add_argument("--health-timeout-seconds", type=float, default=10.0)
    parser.add_argument("--output-dir", help="Optional output directory; defaults to logs/debug_harness/YYYYMMDD/HHMMSS")
    return parser.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_scenarios(order_store_path: str, include_full_store: bool = False) -> list[Scenario]:
    data = _load_json(Path(order_store_path))
    orders = data.get("orders", [])
    executable_orders = [
        order for order in orders
        if order.get("execute", False) and not order.get("success", False)
    ]

    queue_groups: dict[int, list[dict[str, Any]]] = {}
    for order in executable_orders:
        queue_groups.setdefault(int(order.get("queue_id", 999)), []).append(order)

    scenarios: list[Scenario] = []
    for queue_id in sorted(queue_groups):
        group = queue_groups[queue_id]
        is_multi_queue = bool(group[0].get("multi_queue", False)) and len(group) > 1
        is_trigger_sell_queue = bool(group[0].get("trigger_sell_queue", False)) and len(group) > 1
        if is_multi_queue:
            scenarios.append(
                Scenario(
                    name=f"queue_{queue_id:02d}_multi_queue",
                    queue_id=queue_id,
                    kind="multi_queue",
                    order_ids=[str(order["id"]) for order in group],
                    tickers=[str(order["ticker"]).upper() for order in group],
                )
            )
            continue
        if is_trigger_sell_queue:
            scenarios.append(
                Scenario(
                    name=f"queue_{queue_id:02d}_trigger_sell_queue",
                    queue_id=queue_id,
                    kind="trigger_sell_queue",
                    order_ids=[str(order["id"]) for order in group],
                    tickers=[str(order["ticker"]).upper() for order in group],
                )
            )
            continue
        for order in group:
            scenarios.append(
                Scenario(
                    name=f"queue_{queue_id:02d}_{order['id']}",
                    queue_id=queue_id,
                    kind=str(order["mode"]),
                    order_ids=[str(order["id"])],
                    tickers=[str(order["ticker"]).upper()],
                )
            )

    if include_full_store and executable_orders:
        scenarios.insert(
            0,
            Scenario(
                name="full_store",
                queue_id=0,
                kind="full_store",
                order_ids=[str(order["id"]) for order in executable_orders],
                tickers=[str(order["ticker"]).upper() for order in executable_orders],
            ),
        )
    return scenarios


def create_scenario_store(source_store_path: str, scenario: Scenario, output_path: Path) -> None:
    payload = _load_json(Path(source_store_path))
    selected_ids = set(scenario.order_ids)
    for order in payload.get("orders", []):
        order_id = str(order.get("id"))
        if order_id in selected_ids:
            order["execute"] = True
            order["success"] = False
        else:
            order["execute"] = False
    _write_json(output_path, payload)


def build_main_command(args: argparse.Namespace, scenario_store_path: Path) -> list[str]:
    command = [sys.executable, str(ROOT / "main.py"), "--order-store", str(scenario_store_path), "--log-level", "DEBUG"]
    if args.pool_users:
        command.extend(["--pool-users", *args.pool_users])
    else:
        if not args.user_config:
            raise ValueError("--user-config is required when --pool-users is not provided")
        command.extend(["--user-config", args.user_config])
        if args.fetch_users:
            command.extend(["--fetch-users", *args.fetch_users])
        if args.just_buy_users:
            command.extend(["--just-buy-users", *args.just_buy_users])
        if args.atrad_fetch:
            command.append("--atrad-fetch")
    return command


def build_server_command(args: argparse.Namespace) -> list[str]:
    command = [
        sys.executable,
        str(ROOT / "utils" / "atrad_debug_server.py"),
        "--host",
        args.server_host,
        "--port",
        str(args.server_port),
        "--order-store",
        args.order_store,
        "--price-step-every-requests",
        str(args.requests_per_step),
        "--order-accept-after-requests",
        str(args.order_accept_after_requests),
        "--min-delay-ms",
        str(args.min_delay_ms),
        "--max-delay-ms",
        str(args.max_delay_ms),
        "--inactivity-reset-seconds",
        str(args.inactivity_reset_seconds),
    ]
    return command


def _http_json(url: str, method: str = "GET") -> dict[str, Any]:
    request = Request(url=url, method=method)
    with urlopen(request, timeout=2.0) as response:
        return json.loads(response.read().decode("utf-8"))


def wait_for_health(base_url: str, timeout_seconds: float) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Optional[Exception] = None
    while time.time() < deadline:
        try:
            payload = _http_json(f"{base_url}/healthz")
            if payload.get("status") == "ok":
                return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.2)
    raise RuntimeError(f"Debug server did not become healthy within {timeout_seconds}s: {last_error}")


def reset_server_state(base_url: str) -> None:
    _http_json(f"{base_url}/__debug/reset", method="POST")


def fetch_server_state(base_url: str) -> dict[str, Any]:
    return _http_json(f"{base_url}/__debug/state")


def _safe_terminate(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=3)


def _collect_selected_results(scenario_store_path: Path, selected_ids: list[str]) -> tuple[list[str], list[str]]:
    payload = _load_json(scenario_store_path)
    selected = {
        str(order.get("id")): order
        for order in payload.get("orders", [])
        if str(order.get("id")) in selected_ids
    }
    success_ids = [order_id for order_id in selected_ids if selected.get(order_id, {}).get("success", False)]
    failed_ids = [order_id for order_id in selected_ids if not selected.get(order_id, {}).get("success", False)]
    return success_ids, failed_ids


def run_scenario(
    *,
    args: argparse.Namespace,
    scenario: Scenario,
    run_dir: Path,
    base_url: str,
) -> ScenarioResult:
    scenario_dir = run_dir / scenario.name
    scenario_dir.mkdir(parents=True, exist_ok=True)
    scenario_store_path = scenario_dir / "order_store.json"
    stdout_path = scenario_dir / "main.stdout.log"
    stderr_path = scenario_dir / "main.stderr.log"
    server_state_path = scenario_dir / "server_state.json"

    create_scenario_store(args.order_store, scenario, scenario_store_path)
    reset_server_state(base_url)

    env = os.environ.copy()
    env["DEBUG"] = "true"
    env["DEBUG_ATRAD_BASE_URL"] = base_url
    env["DEBUG_ATRAD_HOST"] = f"{args.server_host}:{args.server_port}"
    env["PYTHONUNBUFFERED"] = "1"

    command = build_main_command(args, scenario_store_path)
    started_at = time.time()
    with stdout_path.open("w", encoding="utf-8") as stdout_handle, stderr_path.open("w", encoding="utf-8") as stderr_handle:
        process = subprocess.Popen(
            command,
            cwd=str(ROOT),
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=env,
        )
        return_code = process.wait()
    duration_seconds = time.time() - started_at

    server_state = fetch_server_state(base_url)
    _write_json(server_state_path, server_state)
    selected_success_ids, selected_failed_ids = _collect_selected_results(scenario_store_path, scenario.order_ids)
    order_events = [
        event for event in server_state.get("order_events", [])
        if event.get("symbol", "").upper() in set(scenario.tickers)
    ]

    return ScenarioResult(
        scenario_name=scenario.name,
        kind=scenario.kind,
        order_ids=scenario.order_ids,
        tickers=scenario.tickers,
        return_code=return_code,
        duration_seconds=duration_seconds,
        selected_success_ids=selected_success_ids,
        selected_failed_ids=selected_failed_ids,
        server_order_attempts=len(order_events),
        server_order_accepts=sum(1 for event in order_events if event.get("accepted")),
        stdout_path=str(stdout_path),
        stderr_path=str(stderr_path),
        server_state_path=str(server_state_path),
    )


def render_report(results: list[ScenarioResult], run_dir: Path) -> str:
    lines = [
        "ATRAD Debug Harness",
        "=" * 80,
        f"Run directory: {run_dir}",
        "",
        f"{'Scenario':<36} {'Kind':<22} {'Result':<8} {'Orders':<12} {'Attempts':<10} {'Accepts':<8} {'Duration':<10}",
        "-" * 80,
    ]
    for result in results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(
            f"{result.scenario_name:<36} {result.kind:<22} {status:<8} "
            f"{len(result.selected_success_ids)}/{len(result.order_ids):<12} "
            f"{result.server_order_attempts:<10} {result.server_order_accepts:<8} "
            f"{result.duration_seconds:>7.2f}s"
        )
    lines.extend(["", "Per-scenario artifacts:"])
    for result in results:
        lines.append(
            f"- {result.scenario_name}: stdout={result.stdout_path}, stderr={result.stderr_path}, server_state={result.server_state_path}"
        )
    return "\n".join(lines)


def default_run_dir(custom_output_dir: Optional[str]) -> Path:
    if custom_output_dir:
        return Path(custom_output_dir)
    day_dir = ROOT / "logs" / "debug_harness" / datetime.now().strftime("%Y%m%d")
    return day_dir / datetime.now().strftime("%H%M%S")


def main() -> int:
    args = parse_args()
    scenarios = build_scenarios(args.order_store, include_full_store=args.include_full_store)
    if args.scenario:
        selected = set(args.scenario)
        scenarios = [scenario for scenario in scenarios if scenario.name in selected]
    if not scenarios:
        raise SystemExit("No scenarios selected")

    run_dir = default_run_dir(args.output_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "scenarios.json").write_text(
        json.dumps([asdict(scenario) for scenario in scenarios], indent=2),
        encoding="utf-8",
    )

    server_stdout = run_dir / "server.stdout.log"
    server_stderr = run_dir / "server.stderr.log"
    server_command = build_server_command(args)
    base_url = f"http://{args.server_host}:{args.server_port}"

    with server_stdout.open("w", encoding="utf-8") as server_stdout_handle, server_stderr.open("w", encoding="utf-8") as server_stderr_handle:
        server_process = subprocess.Popen(
            server_command,
            cwd=str(ROOT),
            stdout=server_stdout_handle,
            stderr=server_stderr_handle,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
        )
        try:
            wait_for_health(base_url, args.health_timeout_seconds)
            results = [
                run_scenario(args=args, scenario=scenario, run_dir=run_dir, base_url=base_url)
                for scenario in scenarios
            ]
        finally:
            _safe_terminate(server_process)

    summary = {
        "results": [asdict(result) | {"passed": result.passed} for result in results],
        "server_stdout": str(server_stdout),
        "server_stderr": str(server_stderr),
    }
    _write_json(run_dir / "summary.json", summary)
    report = render_report(results, run_dir)
    (run_dir / "report.txt").write_text(report, encoding="utf-8")
    print(report)
    return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
