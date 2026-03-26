"""Test utilities for intercepting and simulating API responses."""

import time
from typing import Optional, Dict, Any, List, Callable
from dataclasses import dataclass
from threading import Lock


@dataclass
class RequestRecord:
    """Record of an intercepted request."""
    timestamp: float
    method: str
    args: tuple
    kwargs: dict
    result: Any


@dataclass
class TimingRecord:
    """Record of timing between requests."""
    timestamp: float
    elapsed_since_last: Optional[float]
    method: str


class TMSClientInterceptor:
    """Wrapper that intercepts TMSClient method calls for testing."""

    def __init__(self, simulated_responses: Dict[str, Callable] = None):
        """
        Initialize interceptor.

        Args:
            simulated_responses: Dict mapping method names to callable that returns simulated response
        """
        self.simulated_responses = simulated_responses or {}
        self.request_records: List[RequestRecord] = []
        self.timing_records: List[TimingRecord] = []
        self._lock = Lock()
        self._last_request_time: Optional[float] = None

    def intercept_method(self, method_name: str, *args, **kwargs) -> Any:
        """
        Intercept a method call and return simulated response.

        Args:
            method_name: Name of the method being called
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Simulated response from configured callable
        """
        timestamp = time.time()

        # Get simulated response
        if method_name in self.simulated_responses:
            result = self.simulated_responses[method_name](*args, **kwargs)
        else:
            result = None

        # Record request
        with self._lock:
            self.request_records.append(RequestRecord(
                timestamp=timestamp,
                method=method_name,
                args=args,
                kwargs=kwargs,
                result=result
            ))

            # Record timing
            elapsed = None
            if self._last_request_time is not None:
                elapsed = timestamp - self._last_request_time

            self.timing_records.append(TimingRecord(
                timestamp=timestamp,
                elapsed_since_last=elapsed,
                method=method_name
            ))

            self._last_request_time = timestamp

        return result

    def get_requests_by_method(self, method_name: str) -> List[RequestRecord]:
        """Get all requests for a specific method."""
        return [r for r in self.request_records if r.method == method_name]

    def get_timing_for_method(self, method_name: str) -> List[TimingRecord]:
        """Get all timing records for a specific method."""
        return [t for t in self.timing_records if t.method == method_name]

    def get_poll_intervals(self) -> List[float]:
        """
        Get intervals between consecutive get_ltp calls.

        Returns:
            List of intervals in seconds
        """
        ltp_timings = self.get_timing_for_method('get_ltp')
        return [t.elapsed_since_last for t in ltp_timings if t.elapsed_since_last is not None]

    def verify_polling_transition(
        self,
        fast_interval_ms: int,
        slow_interval_ms: int,
        tolerance_ms: int = 50
    ) -> Dict[str, Any]:
        """
        Verify that polling transitioned from fast to slow to fast.

        Args:
            fast_interval_ms: Expected fast polling interval
            slow_interval_ms: Expected slow polling interval
            tolerance_ms: Tolerance for interval matching

        Returns:
            Dict with verification results
        """
        intervals = self.get_poll_intervals()

        if not intervals:
            return {
                'success': False,
                'error': 'No polling intervals recorded'
            }

        fast_interval_s = fast_interval_ms / 1000.0
        slow_interval_s = slow_interval_ms / 1000.0
        tolerance_s = tolerance_ms / 1000.0

        # Categorize intervals
        fast_intervals = []
        slow_intervals = []
        unknown_intervals = []

        for interval in intervals:
            if abs(interval - fast_interval_s) <= tolerance_s:
                fast_intervals.append(interval)
            elif abs(interval - slow_interval_s) <= tolerance_s:
                slow_intervals.append(interval)
            else:
                unknown_intervals.append(interval)

        # Find transition points
        phases = []
        current_phase = None

        for interval in intervals:
            if abs(interval - fast_interval_s) <= tolerance_s:
                phase = 'fast'
            elif abs(interval - slow_interval_s) <= tolerance_s:
                phase = 'slow'
            else:
                phase = 'unknown'

            if phase != current_phase:
                phases.append(phase)
                current_phase = phase

        return {
            'success': True,
            'total_intervals': len(intervals),
            'fast_count': len(fast_intervals),
            'slow_count': len(slow_intervals),
            'unknown_count': len(unknown_intervals),
            'phases': phases,
            'intervals': intervals,
            'unknown_intervals': unknown_intervals
        }

    def clear(self):
        """Clear all recorded data."""
        with self._lock:
            self.request_records.clear()
            self.timing_records.clear()
            self._last_request_time = None


class MockTMSClient:
    """Mock TMSClient that uses interceptor for all method calls."""

    def __init__(self, interceptor: TMSClientInterceptor, user_id: str = "test_user", user_config=None):
        """
        Initialize mock client.

        Args:
            interceptor: Interceptor to use for method calls
            user_id: User identifier
            user_config: Optional UserConfig object
        """
        self.interceptor = interceptor
        self.user_id = user_id
        self.host = "test_host"
        self.user_config = user_config

    def get_ltp(self, security_id: str) -> Optional[float]:
        """Mock get_ltp that uses interceptor."""
        return self.interceptor.intercept_method('get_ltp', security_id)

    def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        """Mock place_order that uses interceptor (accepts any arguments)."""
        return self.interceptor.intercept_method('place_order', *args, **kwargs)

    def refresh_tokens(self) -> bool:
        """Mock refresh_tokens that uses interceptor."""
        return self.interceptor.intercept_method('refresh_tokens')
