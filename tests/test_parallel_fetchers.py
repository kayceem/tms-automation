import time

from services.fetchers.atrad_price_fetcher import ATRADFetchUser, ATRADMultiUserPriceFetcher
from services.fetchers.price_fetcher import FetchUser, MultiUserPriceFetcher


class FakeTMSClient:
    def __init__(self, user_id, call_log, delay=0.0):
        self.user_id = user_id
        self.call_log = call_log
        self.delay = delay
        self.counter = 0

    def get_ltp(self, security_id, timeout=None):
        self.call_log.append((self.user_id, time.perf_counter()))
        if self.delay:
            time.sleep(self.delay)
        self.counter += 1
        return float(self.counter)


class FakeATRADClient:
    def __init__(self, user_id, ltp_log, market_log, ltp_delay=0.0):
        self.user_id = user_id
        self.ltp_log = ltp_log
        self.market_log = market_log
        self.ltp_delay = ltp_delay
        self.counter = 0

    def get_ltp(self, symbol, timeout=None):
        self.ltp_log.append((self.user_id, time.perf_counter()))
        if self.ltp_delay:
            time.sleep(self.ltp_delay)
        self.counter += 1
        return float(self.counter)

    def get_market_details(self, symbol, timeout=None):
        self.market_log.append((self.user_id, time.perf_counter()))
        return {"price": "100", "qty": "1", "splits": "1"}


def test_multi_user_price_fetcher_sequential_rotation_prefix(monkeypatch):
    monkeypatch.setattr("services.fetchers.price_fetcher.TMSClient", FakeTMSClient)
    call_log = []
    fetcher = MultiUserPriceFetcher(
        fetch_users=[
            FetchUser("FU-1", FakeTMSClient("u1", call_log), 101),
            FetchUser("FU-2", FakeTMSClient("u2", call_log), 202),
        ],
        poll_interval_ms=5,
        requests_per_user=2,
        enable_cooldown=False,
    )

    fetcher.start()
    time.sleep(0.05)
    fetcher.stop()

    assert [entry[0] for entry in call_log[:4]] == ["u1", "u1", "u2", "u2"]


def test_multi_user_price_fetcher_parallel_cycles_on_response(monkeypatch):
    monkeypatch.setattr("services.fetchers.price_fetcher.TMSClient", FakeTMSClient)
    call_log = []
    fetcher = MultiUserPriceFetcher(
        fetch_users=[
            FetchUser("FU-1", FakeTMSClient("u1", call_log, delay=0.001), 101),
            FetchUser("FU-2", FakeTMSClient("u2", call_log, delay=0.05), 202),
        ],
        poll_interval_ms=5,
        requests_per_user=2,
        enable_cooldown=False,
        scheduler_mode="parallel",
        parallel_fetch_enabled=True,
        parallel_spawn_interval_ms=10,
        parallel_cycle_timeout_ms=40,
        parallel_wait=False,
    )

    fetcher.start()
    time.sleep(0.08)
    fetcher.stop()

    assert [entry[0] for entry in call_log[:3]] == ["u1", "u2", "u1"]


def test_multi_user_price_fetcher_parallel_wait_enforces_dispatch_gap(monkeypatch):
    monkeypatch.setattr("services.fetchers.price_fetcher.TMSClient", FakeTMSClient)
    call_log = []
    fetcher = MultiUserPriceFetcher(
        fetch_users=[
            FetchUser("FU-1", FakeTMSClient("u1", call_log), 101),
            FetchUser("FU-2", FakeTMSClient("u2", call_log), 202),
        ],
        poll_interval_ms=5,
        requests_per_user=2,
        enable_cooldown=False,
        scheduler_mode="parallel",
        parallel_fetch_enabled=True,
        parallel_spawn_interval_ms=12,
        parallel_cycle_timeout_ms=20,
        parallel_wait=True,
    )

    fetcher.start()
    time.sleep(0.07)
    fetcher.stop()

    dispatch_times = [entry[1] for entry in call_log[:4]]
    gaps_ms = [
        (dispatch_times[index + 1] - dispatch_times[index]) * 1000
        for index in range(len(dispatch_times) - 1)
    ]
    assert gaps_ms
    assert min(gaps_ms) >= 9


def test_multi_user_price_fetcher_parallel_pause_and_resume(monkeypatch):
    monkeypatch.setattr("services.fetchers.price_fetcher.TMSClient", FakeTMSClient)
    call_log = []
    fetcher = MultiUserPriceFetcher(
        fetch_users=[
            FetchUser("FU-1", FakeTMSClient("u1", call_log, delay=0.03), 101),
            FetchUser("FU-2", FakeTMSClient("u2", call_log, delay=0.03), 202),
        ],
        poll_interval_ms=5,
        requests_per_user=2,
        enable_cooldown=False,
        scheduler_mode="parallel",
        parallel_fetch_enabled=True,
        parallel_spawn_interval_ms=10,
        parallel_cycle_timeout_ms=20,
        parallel_wait=False,
    )

    fetcher.start()
    time.sleep(0.02)
    fetcher.pause()
    paused_count = len(call_log)
    time.sleep(0.05)
    paused_after_wait = len(call_log)
    fetcher.resume()
    time.sleep(0.05)
    resumed_count = len(call_log)
    fetcher.stop()

    assert paused_count > 0
    assert paused_after_wait == paused_count
    assert resumed_count > paused_after_wait


def test_multi_user_price_fetcher_parallel_fallback_dispatches_oldest_user(monkeypatch):
    monkeypatch.setattr("services.fetchers.price_fetcher.TMSClient", FakeTMSClient)
    call_log = []
    fetcher = MultiUserPriceFetcher(
        fetch_users=[
            FetchUser("FU-1", FakeTMSClient("u1", call_log, delay=0.08), 101),
            FetchUser("FU-2", FakeTMSClient("u2", call_log, delay=0.08), 202),
        ],
        poll_interval_ms=5,
        requests_per_user=2,
        enable_cooldown=False,
        scheduler_mode="parallel",
        parallel_fetch_enabled=True,
        parallel_spawn_interval_ms=10,
        parallel_cycle_timeout_ms=15,
        parallel_wait=False,
    )

    fetcher.start()
    time.sleep(0.045)
    fetcher.stop()

    assert [entry[0] for entry in call_log[:3]] == ["u1", "u2", "u1"]


def test_atrad_multi_user_parallel_market_details_blocks_ltp_updates(monkeypatch):
    monkeypatch.setattr("services.fetchers.atrad_price_fetcher.ATRADClient", FakeATRADClient)
    ltp_log = []
    market_log = []
    fetcher = ATRADMultiUserPriceFetcher(
        fetch_users=[
            ATRADFetchUser("AFU-1", FakeATRADClient("a1", ltp_log, market_log), "NABIL"),
            ATRADFetchUser("AFU-2", FakeATRADClient("a2", ltp_log, market_log), "NABIL"),
        ],
        poll_interval_ms=5,
        requests_per_user=2,
        enable_cooldown=False,
        scheduler_mode="parallel",
        parallel_fetch_enabled=True,
        parallel_spawn_interval_ms=10,
        parallel_cycle_timeout_ms=20,
        parallel_wait=False,
    )

    fetcher.start()
    time.sleep(0.05)
    before_market = fetcher.get_latest_ltp()
    fetcher.start_market_details()
    time.sleep(0.03)
    during_market = fetcher.get_latest_ltp()
    fetcher.stop_market_details()
    time.sleep(0.03)
    after_market = fetcher.get_latest_ltp()
    fetcher.stop()

    assert before_market is not None
    assert during_market == before_market
    assert after_market is not None
    assert len(market_log) > 0


def test_atrad_multi_user_parallel_pause_and_resume(monkeypatch):
    monkeypatch.setattr("services.fetchers.atrad_price_fetcher.ATRADClient", FakeATRADClient)
    ltp_log = []
    market_log = []
    fetcher = ATRADMultiUserPriceFetcher(
        fetch_users=[
            ATRADFetchUser("AFU-1", FakeATRADClient("a1", ltp_log, market_log, ltp_delay=0.03), "NABIL"),
            ATRADFetchUser("AFU-2", FakeATRADClient("a2", ltp_log, market_log, ltp_delay=0.03), "NABIL"),
        ],
        poll_interval_ms=5,
        requests_per_user=2,
        enable_cooldown=False,
        scheduler_mode="parallel",
        parallel_fetch_enabled=True,
        parallel_spawn_interval_ms=10,
        parallel_cycle_timeout_ms=20,
        parallel_wait=False,
    )

    fetcher.start()
    time.sleep(0.02)
    fetcher.pause()
    paused_count = len(ltp_log)
    time.sleep(0.05)
    paused_after_wait = len(ltp_log)
    fetcher.resume()
    time.sleep(0.05)
    resumed_count = len(ltp_log)
    fetcher.stop()

    assert paused_count > 0
    assert paused_after_wait == paused_count
    assert resumed_count > paused_after_wait
