import statistics
import threading
import time

from services.fetchers.atrad_price_fetcher import ATRADFetchUser, ATRADMultiUserPriceFetcher
from tests.test_base_order_service import DummyService


def _stats_ms(values):
    ordered = sorted(values)
    p95_index = max(0, min(len(ordered) - 1, int(len(ordered) * 0.95) - 1))
    return {
        "median_ms": statistics.median(ordered) * 1000,
        "p95_ms": ordered[p95_index] * 1000,
        "min_ms": ordered[0] * 1000,
        "max_ms": ordered[-1] * 1000,
    }


class TimestampATRADClient:
    def __init__(self, user_id, event, timestamps, stop_fetcher=None):
        self.user_id = user_id
        self._event = event
        self._timestamps = timestamps
        self._stop_fetcher = stop_fetcher

    def get_ltp(self, symbol, timeout=None):
        self._timestamps.append(time.perf_counter())
        if self._stop_fetcher is not None:
            self._stop_fetcher._running = False
        self._event.set()
        return 123.45


class ThresholdPriceFetcher:
    def __init__(self, ltps, detect_times, schedule_times):
        self.ltps = list(ltps)
        self.index = 0
        self.detect_times = detect_times
        self.schedule_times = schedule_times

    def get_latest_ltp(self):
        self.detect_times.append(time.perf_counter())
        if self.index >= len(self.ltps):
            return self.ltps[-1]
        value = self.ltps[self.index]
        self.index += 1
        return value

    def update_scheduler_mode(self, scheduler_mode):
        self.schedule_times.append((scheduler_mode, time.perf_counter()))

    def start_market_details(self):
        pass

    def stop_market_details(self):
        pass

    def pause(self):
        pass

class TriggerPriceFetcher:
    def __init__(self, ltp, trigger_times):
        self.ltp = ltp
        self.trigger_times = trigger_times

    def get_latest_ltp(self):
        self.trigger_times.append(time.perf_counter())
        return self.ltp

    def start_market_details(self):
        return None

    def stop_market_details(self):
        return None

    def pause(self):
        pass


def test_characterize_atrad_parallel_scheduler_and_trigger_overheads(monkeypatch):
    monkeypatch.setattr("services.fetchers.atrad_price_fetcher.ATRADClient", TimestampATRADClient)
    monkeypatch.setattr("services.fetchers.atrad_price_fetcher.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("services.workflows.trigger_waiters.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("services.workflows.order_attempts.time.sleep", lambda _seconds: None)

    sequential_dispatch_overheads = []
    parallel_response_overheads = []
    parallel_fallback_overheads = []
    switch_overheads = []
    trigger_to_place_overheads = []

    for _ in range(200):
        # Sequential steady-state overhead: after selecting the user, how long until get_ltp is entered.
        sequential_event = threading.Event()
        sequential_call_times = []
        sequential_placeholder = ATRADFetchUser(
            "AFU-1",
            TimestampATRADClient("u1", sequential_event, sequential_call_times),
            "NABIL",
        )
        sequential_fetcher = ATRADMultiUserPriceFetcher(
            fetch_users=[sequential_placeholder],
            poll_interval_ms=5,
            requests_per_user=1,
            enable_cooldown=False,
        )
        current_user = ATRADFetchUser(
            "AFU-1",
            TimestampATRADClient("u1", sequential_event, sequential_call_times, stop_fetcher=sequential_fetcher),
            "NABIL",
        )
        sequential_fetcher.fetch_users = [current_user]
        sequential_fetcher._len_fetch_users = 1
        sequential_fetcher._parallel_last_dispatch_ms = {current_user.name: 0.0}
        sequential_fetcher._running = True
        decision_times = []
        original_get_next_user = sequential_fetcher._get_next_user

        def wrapped_get_next_user():
            decision_times.append(time.perf_counter())
            return original_get_next_user()

        sequential_fetcher._get_next_user = wrapped_get_next_user
        sequential_fetcher._fetch_loop()
        sequential_dispatch_overheads.append(sequential_call_times[0] - decision_times[0])

        # Parallel response-driven overhead: after completion is observed, how long until next get_ltp starts.
        response_event = threading.Event()
        response_call_times = []
        response_user = ATRADFetchUser(
            "AFU-1",
            TimestampATRADClient("u1", response_event, response_call_times),
            "NABIL",
        )
        response_fetcher = ATRADMultiUserPriceFetcher(
            fetch_users=[response_user],
            poll_interval_ms=5,
            requests_per_user=1,
            enable_cooldown=False,
            scheduler_mode="parallel",
            parallel_fetch_enabled=True,
            parallel_spawn_interval_ms=10,
            parallel_cycle_timeout_ms=20,
            parallel_wait=False,
        )
        response_fetcher._running = True
        response_fetcher._parallel_seeded = True
        response_fetcher._parallel_completion_queue.append("AFU-1")
        dispatch_started = time.perf_counter()
        assert response_fetcher._dispatch_next_parallel_fetch() is True
        assert response_event.wait(1.0)
        parallel_response_overheads.append(response_call_times[0] - dispatch_started)
        response_fetcher.stop()

        # Parallel fallback overhead: no completion, oldest-user fallback dispatches.
        fallback_event = threading.Event()
        fallback_call_times = []
        fallback_user = ATRADFetchUser(
            "AFU-1",
            TimestampATRADClient("u1", fallback_event, fallback_call_times),
            "NABIL",
        )
        fallback_fetcher = ATRADMultiUserPriceFetcher(
            fetch_users=[fallback_user],
            poll_interval_ms=5,
            requests_per_user=1,
            enable_cooldown=False,
            scheduler_mode="parallel",
            parallel_fetch_enabled=True,
            parallel_spawn_interval_ms=10,
            parallel_cycle_timeout_ms=1,
            parallel_wait=False,
        )
        fallback_fetcher._running = True
        fallback_fetcher._parallel_seeded = True
        now_ms = time.perf_counter() * 1000
        fallback_fetcher._parallel_last_dispatch_any_ms = now_ms - 5
        fallback_fetcher._parallel_last_dispatch_ms["AFU-1"] = now_ms - 5
        fallback_started = time.perf_counter()
        assert fallback_fetcher._dispatch_next_parallel_fetch() is True
        assert fallback_event.wait(1.0)
        parallel_fallback_overheads.append(fallback_call_times[0] - fallback_started)
        fallback_fetcher.stop()

        # Switch overhead: after reading an above-threshold LTP, how long until scheduler switch call.
        service = DummyService()
        service.client.user_config.trigger_mode_parallel_fetch_enabled = True
        detect_times = []
        schedule_times = []
        threshold_fetcher = ThresholdPriceFetcher(
            ltps=[115.0, 120.0],
            detect_times=detect_times,
            schedule_times=schedule_times,
        )
        triggered, response = service._wait_for_no_ladder_trigger(
            price_fetcher=threshold_fetcher,
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
        assert triggered is True
        assert response is None
        switch_overheads.append(schedule_times[0][1] - detect_times[0])

        # Trigger-to-placement overhead: after reading a triggered LTP, how long until _place_single_order starts.
        service = DummyService()
        trigger_times = []
        place_times = []
        trigger_fetcher = TriggerPriceFetcher(ltp=110.0, trigger_times=trigger_times)

        def record_place(price, quantity, **params):
            place_times.append(time.perf_counter())
            return {"status": "ok", "price": price, "quantity": quantity, "params": params}

        service._place_single_order = record_place
        response = service._execute_no_ladder_mode(
            price_fetcher=trigger_fetcher,
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
        assert response["status"] == "ok"
        trigger_to_place_overheads.append(place_times[0] - trigger_times[0])

    sequential_stats = _stats_ms(sequential_dispatch_overheads)
    parallel_response_stats = _stats_ms(parallel_response_overheads)
    parallel_fallback_stats = _stats_ms(parallel_fallback_overheads)
    switch_stats = _stats_ms(switch_overheads)
    trigger_place_stats = _stats_ms(trigger_to_place_overheads)

    print("ATRAD overhead characterization:")
    print(f"  sequential_dispatch: {sequential_stats}")
    print(f"  parallel_response_dispatch: {parallel_response_stats}")
    print(f"  parallel_fallback_dispatch: {parallel_fallback_stats}")
    print(f"  switch_to_parallel: {switch_stats}")
    print(f"  trigger_to_place: {trigger_place_stats}")

    assert sequential_stats["p95_ms"] < 5.0
    assert parallel_response_stats["p95_ms"] < 5.0
    assert parallel_fallback_stats["p95_ms"] < 5.0
    assert switch_stats["p95_ms"] < 5.0
    assert trigger_place_stats["p95_ms"] < 5.0
