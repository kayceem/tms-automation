from argparse import Namespace

import pytest

from utils.atrad_latency_tester import (
    ProbeResult,
    UserLatencyResult,
    render_report,
    validate_args,
)


def test_average_time_between_responses_uses_sorted_completion_times():
    result = UserLatencyResult(
        user_id="atrad-user-1",
        endpoint="quote",
        request_count=3,
        parallel=True,
        samples=[
            ProbeResult(index=1, user_id="atrad-user-1", sent_at_ms=900.0, latency_ms=12.5, completed_at_ms=1000.0, success=True, status_code=200),
            ProbeResult(index=2, user_id="atrad-user-1", sent_at_ms=905.0, latency_ms=12.5, completed_at_ms=1012.0, success=True, status_code=200),
            ProbeResult(index=3, user_id="atrad-user-1", sent_at_ms=910.0, latency_ms=12.5, completed_at_ms=1010.0, success=True, status_code=200),
        ],
    )

    assert result.average_time_between_responses_ms == pytest.approx(4.0)


def test_validate_args_requires_symbol_for_quote():
    args = Namespace(
        endpoint="quote",
        symbol=None,
        requests=30,
        timeout=5.0,
        parallel=False,
        wait=False,
        cycle_users=False,
        cycle_timeout_ms=20.0,
        spawn_interval_ms=5.0,
        allow_live_order=False,
        price=None,
        quantity=None,
        side="BUY",
    )

    with pytest.raises(ValueError, match="--symbol is required"):
        validate_args(args)


def test_validate_args_blocks_live_order_without_explicit_flag():
    args = Namespace(
        endpoint="order",
        symbol="NABIL",
        requests=30,
        timeout=5.0,
        parallel=False,
        wait=False,
        cycle_users=False,
        cycle_timeout_ms=20.0,
        spawn_interval_ms=5.0,
        allow_live_order=False,
        price=500.0,
        quantity=10,
        side="BUY",
    )

    with pytest.raises(ValueError, match="unsafe"):
        validate_args(args)


def test_render_report_includes_summary_and_samples():
    args = Namespace(
        endpoint="quote",
        requests=2,
        parallel=False,
        wait=False,
        cycle_users=False,
        cycle_timeout_ms=20.0,
        spawn_interval_ms=5.0,
        symbol="NABIL",
    )
    result = UserLatencyResult(
        user_id="atrad-user-1",
        endpoint="quote",
        request_count=2,
        parallel=False,
        samples=[
            ProbeResult(index=1, user_id="atrad-user-1", sent_at_ms=900.0, latency_ms=12.5, completed_at_ms=1000.0, success=True, status_code=200),
            ProbeResult(index=2, user_id="atrad-user-1", sent_at_ms=903.0, latency_ms=20.0, completed_at_ms=1003.0, success=False, status_code=500, error="unexpected response"),
        ],
    )

    report = render_report([result], args)

    assert "ATRAD Latency Benchmark" in report
    assert "user_id" in report
    assert "atrad-user-1" in report
    assert "1" in report
    assert "12.50ms" in report
    assert "1.50ms" in report
    assert "Response Timeline :: atrad-user-1" in report
    assert "recv#" in report
    assert "probe#" in report
    assert "req_at" in report
    assert "recv_at_interval" in report
    assert "0.00ms" in report
    assert "3.00ms" in report


def test_render_report_includes_cycle_timeline():
    args = Namespace(
        endpoint="quote",
        requests=2,
        parallel=True,
        wait=True,
        cycle_users=True,
        cycle_timeout_ms=20.0,
        spawn_interval_ms=5.0,
        symbol="NABIL",
    )
    results = [
        UserLatencyResult(
            user_id="atrad-user-1",
            endpoint="quote",
            request_count=2,
            parallel=True,
            samples=[
                ProbeResult(index=1, user_id="atrad-user-1", sent_at_ms=900.0, latency_ms=10.0, completed_at_ms=1005.0, success=True, status_code=200),
                ProbeResult(index=3, user_id="atrad-user-1", sent_at_ms=910.0, latency_ms=9.0, completed_at_ms=1015.0, success=True, status_code=200),
            ],
        ),
        UserLatencyResult(
            user_id="atrad-user-2",
            endpoint="quote",
            request_count=2,
            parallel=True,
            samples=[
                ProbeResult(index=2, user_id="atrad-user-2", sent_at_ms=905.0, latency_ms=8.0, completed_at_ms=1000.0, success=True, status_code=200),
            ],
        ),
    ]

    report = render_report(
        results,
        args,
        cycle_samples=[
            ProbeResult(index=2, user_id="atrad-user-2", sent_at_ms=905.0, latency_ms=8.0, completed_at_ms=1000.0, success=True, status_code=200),
            ProbeResult(index=1, user_id="atrad-user-1", sent_at_ms=900.0, latency_ms=10.0, completed_at_ms=1005.0, success=True, status_code=200),
            ProbeResult(index=3, user_id="atrad-user-1", sent_at_ms=910.0, latency_ms=9.0, completed_at_ms=1015.0, success=True, status_code=200),
        ],
    )

    assert "Requests total: 2" in report
    assert "Scheduling: cycle-users" in report
    assert "Cycle timeout: 20.0ms" in report
    assert "Strict wait: enabled" in report
    assert "ALL_USERS" in report
    assert "Cycle Request Interval By User" in report
    assert "atrad-user-1" in report
    assert "5.00ms" in report
    assert "Cycle Response Timeline" in report
    assert "atrad-user-2" in report


def test_validate_args_blocks_wait_without_parallel():
    args = Namespace(
        endpoint="quote",
        symbol="NABIL",
        requests=30,
        timeout=5.0,
        parallel=False,
        wait=True,
        cycle_users=False,
        cycle_timeout_ms=20.0,
        spawn_interval_ms=5.0,
        allow_live_order=False,
        price=None,
        quantity=None,
        side="BUY",
    )

    with pytest.raises(ValueError, match="--wait requires --parallel"):
        validate_args(args)
