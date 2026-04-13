from argparse import Namespace

import pytest

from utils.atrad_latency_tester import (
    ProbeResult,
    UserLatencyResult,
    render_report,
    validate_args,
)


def test_validate_args_requires_symbol_for_quote():
    args = Namespace(
        endpoint="quote",
        symbol=None,
        requests=30,
        timeout=5.0,
        parallel=False,
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
        spawn_interval_ms=5.0,
        symbol="NABIL",
    )
    result = UserLatencyResult(
        user_id="atrad-user-1",
        endpoint="quote",
        request_count=2,
        parallel=False,
        samples=[
            ProbeResult(index=1, latency_ms=12.5, success=True, status_code=200),
            ProbeResult(index=2, latency_ms=20.0, success=False, status_code=500, error="unexpected response"),
        ],
    )

    report = render_report([result], args)

    assert "ATRAD Latency Benchmark" in report
    assert "user_id" in report
    assert "atrad-user-1" in report
    assert "1" in report
    assert "12.50ms" in report
    assert "#01" not in report
