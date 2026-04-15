from services.orders.base_order_service import BaseOrderService
from types import SimpleNamespace
import threading
import time


class DummyClient:
    def __init__(self):
        self.user_id = "dummy-user"
        self.user_config = type(
            "Config",
            (),
            {
                "trigger_mode_poll_interval_ms": 100,
                "multi_fetch_poll_interval_ms": 100,
                "trigger_mode_slow_poll_interval_ms": 500,
                "trigger_sell_poll_interval_ms": 500,
                "trigger_mode_refresh_interval_seconds": 60,
                "trigger_mode_requests_per_fetch_user": 5,
                "trigger_mode_parallel_fetch_enabled": False,
                "trigger_mode_parallel_spawn_interval_ms": 10,
                "trigger_mode_parallel_cycle_timeout_ms": 20,
                "trigger_mode_parallel_wait": False,
            },
        )()


class DummyService(BaseOrderService):
    def __init__(self):
        super().__init__(DummyClient(), "dummy-user")
        self.placed_orders = []
        self.raise_on_place = None

    def _place_single_order(self, price: float, quantity: int, **params):
        if self.raise_on_place:
            raise self.raise_on_place
        payload = {"price": price, "quantity": quantity, "params": params}
        self.placed_orders.append(payload)
        return {"status": "ok", **payload}

    def _setup_token_manager(self):
        return None

    def _cleanup_token_manager(self, token_manager):
        return None

    def _get_identifier_for_logging(self, **params):
        return params.get("symbol") or f"Security={params.get('security_id', 'unknown')}"


class FakePriceFetcher:
    def __init__(self, ltps):
        self.ltps = list(ltps)
        self.index = 0
        self.market_started = 0
        self.market_stopped = 0
        self.settings = []
        self.started = 0
        self.stopped = 0
        self.paused = 0
        self.resumed = 0
        self.scheduler_modes = []

    def get_latest_ltp(self):
        if not self.ltps:
            return None
        if self.index >= len(self.ltps):
            return self.ltps[-1]
        value = self.ltps[self.index]
        self.index += 1
        return value

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1

    def pause(self):
        self.paused += 1

    def resume(self):
        self.resumed += 1

    def start_market_details(self):
        self.market_started += 1

    def stop_market_details(self):
        self.market_stopped += 1

    def update_poll_settings(self, poll_interval_ms, enable_cooldown=False):
        self.settings.append((poll_interval_ms, enable_cooldown))

    def update_scheduler_mode(self, scheduler_mode):
        self.scheduler_modes.append(scheduler_mode)


def test_calculate_price_levels_without_limit():
    service = DummyService()

    levels, increments = service._calculate_price_levels(1000)

    assert levels == [1000.0, 1020.0, 1040.4, 1061.2, 1082.4, 1104.0]
    assert increments == [0, 2, 2, 2, 2, 2]


def test_calculate_price_levels_with_limit_appends_limit_plus_ten_percent():
    service = DummyService()

    levels, increments = service._calculate_price_levels(1000, limit_price=950)

    assert levels == [1000.0, 1020.0, 1040.4, 1045.0]
    assert increments == [0, 2, 2, 10]


def test_calculate_price_levels_returns_single_level_for_no_ladder():
    service = DummyService()

    levels, increments = service._calculate_price_levels(500, no_ladder=True)

    assert levels == [500]
    assert increments == [0]


def test_calculate_lower_price_levels_uses_base_price_when_above_limit():
    service = DummyService()

    levels, decrements = service._calculate_lower_price_levels(1000, limit_price=900)

    assert levels == [910.0, 900.0]
    assert decrements == [9, 10]


def test_calculate_lower_price_levels_uses_limit_when_base_is_lower():
    service = DummyService()

    levels, decrements = service._calculate_lower_price_levels(1000, limit_price=1100)

    assert levels == [1012.0, 1001.0]
    assert decrements == [8, 9]


def test_get_quantity_for_level_uses_base_quantity_until_final_level():
    service = DummyService()

    assert service._get_quantity_for_level(1, 3, 50, 10) == 10
    assert service._get_quantity_for_level(2, 3, 50, 10) == 10
    assert service._get_quantity_for_level(3, 3, 50, 10) == 50
    assert service._get_quantity_for_level(1, 3, 50, None) == 50


def test_execute_double_buy_uses_override_quantity(monkeypatch):
    service = DummyService()
    sleep_calls = []
    monkeypatch.setattr("services.orders.base_order_service.time.sleep", lambda seconds: sleep_calls.append(seconds))

    service._execute_double_buy(
        price=500.5,
        quantity=10,
        double_buy_quantity=7,
        security_id=101,
        symbol="NABIL",
        buy_or_sell=1,
    )

    assert sleep_calls == [0.5]
    assert service.placed_orders[0]["price"] == 500.5
    assert service.placed_orders[0]["quantity"] == 7


def test_execute_double_buy_swallows_order_errors(monkeypatch):
    service = DummyService()
    service.raise_on_place = RuntimeError("boom")
    monkeypatch.setattr("services.orders.base_order_service.time.sleep", lambda _seconds: None)

    service._execute_double_buy(
        price=500.5,
        quantity=10,
        double_buy_quantity=None,
        security_id=101,
        symbol="NABIL",
        buy_or_sell=1,
    )

    assert service.placed_orders == []


def test_resolve_fetch_id_for_client_uses_ticker_store_match():
    service = DummyService()
    ticker_store = type("TickerStore", (), {"get_fetch_id": lambda self, ticker, host=None: 777})()
    client = type("FetchClient", (), {"user_id": "fetch-1", "user_config": type("Cfg", (), {"tms_host": "host-1"})()})()

    fetch_id = service._resolve_fetch_id_for_client(client, "NABIL", ticker_store, 123, 0)

    assert fetch_id == 777


def test_resolve_fetch_id_for_client_falls_back_on_lookup_error():
    service = DummyService()

    class BadTickerStore:
        def get_fetch_id(self, ticker, host=None):
            raise ValueError("missing")

    client = type("FetchClient", (), {"user_id": "fetch-1", "user_config": type("Cfg", (), {"tms_host": "host-1"})()})()

    fetch_id = service._resolve_fetch_id_for_client(client, "NABIL", BadTickerStore(), 123, 0)

    assert fetch_id == 123


def test_place_order_with_retries_retries_until_success(monkeypatch):
    service = DummyService()
    price_fetcher = FakePriceFetcher([])
    attempts = {"count": 0}
    sleep_calls = []
    monkeypatch.setattr("services.orders.base_order_service.time.sleep", lambda seconds: sleep_calls.append(seconds))

    def flaky_place(price, quantity, **params):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary")
        return {"status": "ok", "price": price, "quantity": quantity}

    service._place_single_order = flaky_place

    response = service._place_order_with_retries(
        price_fetcher=price_fetcher,
        target_price=500.5,
        quantity=10,
        level_display=2,
        total_levels=4,
        ltp=499.0,
        platform_params={"security_id": 101},
    )

    assert response == {"status": "ok", "price": 500.5, "quantity": 10}
    assert attempts["count"] == 3
    assert sleep_calls == [0.001, 0.001]
    assert price_fetcher.market_stopped == 1


def test_execute_no_ladder_mode_places_immediately_when_only_one_level():
    service = DummyService()
    response = service._execute_no_ladder_mode(
        price_fetcher=FakePriceFetcher([]),
        price_levels=[550.0],
        order_quantity=25,
        just_buy=False,
        just_buy_interval_ms=100,
        just_buy_timeout=5,
        just_buy_pre_wait_ms=0,
        just_buy_max_requests=None,
        just_buy_fade_interval_ms=None,
        just_buy_fade_timeout=None,
        platform_params={"security_id": 101},
    )

    assert response["price"] == 550.0
    assert response["quantity"] == 25


def test_execute_no_ladder_mode_starts_market_details_after_order_dispatch(monkeypatch):
    service = DummyService()
    price_fetcher = FakePriceFetcher([110.0, 110.0])
    place_started = threading.Event()
    finish_place = threading.Event()
    call_order = []

    service._wait_for_no_ladder_trigger = lambda **kwargs: (True, None)

    def fake_place_order_with_retries(**kwargs):
        call_order.append("place")
        place_started.set()
        assert finish_place.wait(1.0)
        return {"status": "ok", "kwargs": kwargs}

    def fake_start_market_details():
        assert place_started.wait(1.0)
        call_order.append("market")
        finish_place.set()

    service._place_order_with_retries = fake_place_order_with_retries
    price_fetcher.start_market_details = fake_start_market_details

    response = service._execute_no_ladder_mode(
        price_fetcher=price_fetcher,
        price_levels=[100.0, 110.0, 120.0],
        order_quantity=25,
        just_buy=False,
        just_buy_interval_ms=100,
        just_buy_timeout=5,
        just_buy_pre_wait_ms=0,
        just_buy_max_requests=None,
        just_buy_fade_interval_ms=None,
        just_buy_fade_timeout=None,
        platform_params={"security_id": 101},
    )

    assert response["status"] == "ok"
    assert call_order == ["place", "market"]


def test_wait_for_no_ladder_trigger_uses_just_buy_for_already_triggered_order():
    service = DummyService()
    calls = {}

    def fake_execute_just_buy(**kwargs):
        calls.update(kwargs)
        return True, {"status": "ok"}

    service._execute_just_buy = fake_execute_just_buy

    triggered, response = service._wait_for_no_ladder_trigger(
        price_fetcher=FakePriceFetcher([100.0]),
        trigger_price=110.0,
        final_price=120.0,
        switch_threshold=115.0,
        fast_poll_ms=100,
        slow_poll_ms=500,
        just_buy=True,
        just_buy_params={
            "order_quantity": 10,
            "interval_ms": 100,
            "timeout": 5,
            "pre_wait_ms": 0,
            "max_requests": None,
            "fade_interval_ms": None,
            "fade_timeout": None,
        },
        platform_params={"security_id": 101},
        already_triggered=True,
    )

    assert triggered is True
    assert response == {"status": "ok"}
    assert calls["final_price"] == 120.0
    assert calls["trigger_price"] == 110.0


def test_wait_for_no_ladder_trigger_switches_to_slow_then_fast_polling(monkeypatch):
    service = DummyService()
    service.client.user_config.trigger_mode_parallel_fetch_enabled = True
    price_fetcher = FakePriceFetcher([100.0, 115.0, 120.0])
    sleep_calls = []
    monkeypatch.setattr("services.orders.base_order_service.time.sleep", lambda seconds: sleep_calls.append(seconds))
    service._execute_just_buy = lambda **kwargs: (False, None)

    triggered, response = service._wait_for_no_ladder_trigger(
        price_fetcher=price_fetcher,
        trigger_price=120.0,
        final_price=130.0,
        switch_threshold=110.0,
        fast_poll_ms=100,
        slow_poll_ms=500,
        just_buy=True,
        just_buy_params={
            "order_quantity": 10,
            "interval_ms": 100,
            "timeout": 5,
            "pre_wait_ms": 0,
            "max_requests": None,
            "fade_interval_ms": None,
            "fade_timeout": None,
        },
        platform_params={"security_id": 101},
    )

    assert triggered is True
    assert response is None
    assert price_fetcher.settings == [(500, False), (100, True)]
    assert price_fetcher.scheduler_modes == ["sequential", "parallel"]
    assert sleep_calls[:2] == [0.1, min(0.02, 0.001)]


def test_wait_for_no_ladder_trigger_starts_in_parallel_when_already_above_switch_threshold(monkeypatch):
    service = DummyService()
    service.client.user_config.trigger_mode_parallel_fetch_enabled = True
    price_fetcher = FakePriceFetcher([115.0, 120.0])
    sleep_calls = []
    monkeypatch.setattr("services.orders.base_order_service.time.sleep", lambda seconds: sleep_calls.append(seconds))

    triggered, response = service._wait_for_no_ladder_trigger(
        price_fetcher=price_fetcher,
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
        platform_params={"security_id": 101},
    )

    assert triggered is True
    assert response is None
    assert price_fetcher.scheduler_modes == ["parallel"]
    assert price_fetcher.settings == []
    assert sleep_calls == [min(0.02, 0.001)]


def test_setup_tms_price_fetcher_passes_parallel_scheduler_settings(monkeypatch):
    service = DummyService()
    service.client.user_config.trigger_mode_parallel_fetch_enabled = True
    service.client.user_config.trigger_mode_parallel_spawn_interval_ms = 12
    service.client.user_config.trigger_mode_parallel_cycle_timeout_ms = 34
    service.client.user_config.trigger_mode_parallel_wait = True

    captured = {}

    class FakeFetcher:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("services.orders.base_order_service.MultiUserPriceFetcher", FakeFetcher)
    monkeypatch.setattr(
        "services.orders.base_order_service.FetchUser",
        lambda name, client, fetch_security_id: SimpleNamespace(
            name=name,
            client=client,
            fetch_security_id=fetch_security_id,
        ),
    )

    fetch_client = type(
        "FetchClient",
        (),
        {"user_id": "fetch-1", "user_config": type("Cfg", (), {"tms_host": "host-1"})()},
    )()

    service._setup_tms_price_fetcher([fetch_client, fetch_client], 123, None, 100)

    assert captured["poll_interval_ms"] == 100
    assert captured["requests_per_user"] == 5
    assert captured["scheduler_mode"] == "sequential"
    assert captured["parallel_fetch_enabled"] is True
    assert captured["parallel_spawn_interval_ms"] == 12
    assert captured["parallel_cycle_timeout_ms"] == 34
    assert captured["parallel_wait"] is True


def test_setup_atrad_price_fetcher_passes_parallel_scheduler_settings(monkeypatch):
    service = DummyService()
    service.client = type(
        "ATRADLikeClient",
        (),
        {
            "user_id": "dummy-user",
            "user_config": type(
                "Cfg",
                (),
                {
                    "trigger_mode_requests_per_fetch_user": 5,
                    "trigger_mode_parallel_fetch_enabled": True,
                    "trigger_mode_parallel_spawn_interval_ms": 11,
                    "trigger_mode_parallel_cycle_timeout_ms": 21,
                    "trigger_mode_parallel_wait": False,
                },
            )(),
        },
    )()
    captured = {}

    class FakeFetcher:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr("services.orders.base_order_service.ATRADMultiUserPriceFetcher", FakeFetcher)
    monkeypatch.setattr(
        "services.orders.base_order_service.ATRADFetchUser",
        lambda name, client, symbol: SimpleNamespace(
            name=name,
            client=client,
            symbol=symbol,
        ),
    )

    fetch_client = type("FetchClient", (), {"user_id": "fetch-1"})()

    service._setup_atrad_price_fetcher([fetch_client, fetch_client], "NABIL", 90)

    assert captured["poll_interval_ms"] == 90
    assert captured["requests_per_user"] == 5
    assert captured["scheduler_mode"] == "sequential"
    assert captured["parallel_fetch_enabled"] is True
    assert captured["parallel_spawn_interval_ms"] == 11
    assert captured["parallel_cycle_timeout_ms"] == 21
    assert captured["parallel_wait"] is False


def test_execute_just_buy_uses_fade_phase_after_main_phase_failure(monkeypatch):
    service = DummyService()
    price_fetcher = FakePriceFetcher([])
    attempts = {"count": 0}
    sleep_calls = []
    clock = {"now": 0.0}

    monkeypatch.setattr(
        "services.orders.base_order_service.time",
        SimpleNamespace(
            time=lambda: clock["now"],
            sleep=lambda seconds: sleep_calls.append(seconds) or clock.__setitem__("now", clock["now"] + seconds),
        ),
    )

    def flaky_place(price: float, quantity: int, **params):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("temporary")
        payload = {"status": "ok", "price": price, "quantity": quantity, "params": params}
        service.placed_orders.append(payload)
        return payload

    service._place_single_order = flaky_place

    success, response = service._execute_just_buy(
        final_price=120.0,
        trigger_price=110.0,
        order_quantity=10,
        just_buy_interval_ms=100,
        just_buy_timeout=5,
        just_buy_pre_wait_ms=0,
        price_fetcher=price_fetcher,
        platform_params={"security_id": 101},
        just_buy_max_requests=2,
        just_buy_fade_interval_ms=250,
        just_buy_fade_timeout=0.2,
    )

    assert success is True
    assert response["price"] == 120.0
    assert attempts["count"] == 3
    assert price_fetcher.market_started == 1
    assert price_fetcher.market_stopped == 1
    assert sleep_calls[:3] == [0.1, 0.1, 0.25]


def test_execute_just_buy_returns_failure_when_fade_phase_also_fails(monkeypatch):
    service = DummyService()
    price_fetcher = FakePriceFetcher([])
    sleep_calls = []
    clock = {"now": 0.0}

    monkeypatch.setattr(
        "services.orders.base_order_service.time",
        SimpleNamespace(
            time=lambda: clock["now"],
            sleep=lambda seconds: sleep_calls.append(seconds) or clock.__setitem__("now", clock["now"] + seconds),
        ),
    )
    service._place_single_order = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("always fail"))

    success, response = service._execute_just_buy(
        final_price=120.0,
        trigger_price=110.0,
        order_quantity=10,
        just_buy_interval_ms=100,
        just_buy_timeout=5,
        just_buy_pre_wait_ms=0,
        price_fetcher=price_fetcher,
        platform_params={"security_id": 101},
        just_buy_max_requests=2,
        just_buy_fade_interval_ms=250,
        just_buy_fade_timeout=0.2,
    )

    assert success is False
    assert response is None
    assert price_fetcher.market_started == 1
    assert price_fetcher.market_stopped == 1
    assert sleep_calls[:3] == [0.1, 0.1, 0.25]


def test_execute_just_buy_stops_with_success_even_if_multiple_threads_were_spawned():
    service = DummyService()
    price_fetcher = FakePriceFetcher([])
    allow_first_finish = threading.Event()
    first_started = threading.Event()
    attempts = {"count": 0}
    result = {}

    def controlled_place(price: float, quantity: int, **params):
        attempts["count"] += 1
        first_started.set()
        allow_first_finish.wait(timeout=1)
        payload = {"status": "ok", "price": price, "quantity": quantity, "params": params}
        service.placed_orders.append(payload)
        return payload

    service._place_single_order = controlled_place

    def run_just_buy():
        result["value"] = service._execute_just_buy(
            final_price=120.0,
            trigger_price=110.0,
            order_quantity=10,
            just_buy_interval_ms=1,
            just_buy_timeout=5,
            just_buy_pre_wait_ms=0,
            price_fetcher=price_fetcher,
            platform_params={"security_id": 101},
            just_buy_max_requests=2,
        )

    runner = threading.Thread(target=run_just_buy)
    runner.start()

    assert first_started.wait(timeout=1) is True
    time.sleep(0.05)
    allow_first_finish.set()
    runner.join(timeout=2)

    assert result["value"][0] is True
    assert attempts["count"] >= 1
    assert len(service.placed_orders) >= 1


def test_execute_just_buy_aborts_threads_waiting_behind_client_lock():
    service = DummyService()
    attempts = {"count": 0}

    def queued_place(price: float, quantity: int, **params):
        attempts["count"] += 1
        if attempts["count"] == 1:
            time.sleep(0.03)
            payload = {"status": "ok", "price": price, "quantity": quantity, "params": params}
            service.placed_orders.append(payload)
            return payload

        payload = {"status": "extra", "price": price, "quantity": quantity, "params": params}
        service.placed_orders.append(payload)
        return payload

    service._place_single_order = queued_place

    success, response = service._execute_just_buy(
        final_price=120.0,
        trigger_price=110.0,
        order_quantity=10,
        just_buy_interval_ms=1,
        just_buy_timeout=1,
        just_buy_pre_wait_ms=0,
        price_fetcher=FakePriceFetcher([]),
        platform_params={"security_id": 101},
        just_buy_max_requests=5,
    )

    assert success is True
    assert response["status"] == "ok"
    assert attempts["count"] == 1
    assert len(service.placed_orders) == 1


def test_execute_ipo_trigger_uses_no_ladder_path_and_cleans_up():
    service = DummyService()
    price_fetcher = FakePriceFetcher([100.0])
    cleanup = {"token_manager": None, "stopped": 0}

    service._setup_price_fetcher = lambda *args, **kwargs: price_fetcher
    service._setup_token_manager = lambda: "token-manager"
    service._cleanup_token_manager = lambda token_manager: cleanup.update({"token_manager": token_manager})
    service._execute_no_ladder_mode = lambda **kwargs: {"status": "no-ladder", "kwargs": kwargs}

    price_fetcher.stop = lambda: cleanup.update({"stopped": cleanup["stopped"] + 1})

    response = service._execute_ipo_trigger(
        base_price=500.0,
        order_quantity=10,
        fetch_clients=[object()],
        no_ladder=True,
        security_id=101,
        symbol="NABIL",
    )

    assert response["status"] == "no-ladder"
    assert cleanup["token_manager"] == "token-manager"
    assert cleanup["stopped"] == 1


def test_execute_ipo_trigger_uses_ladder_path():
    service = DummyService()
    price_fetcher = FakePriceFetcher([100.0])
    calls = {}

    service._setup_price_fetcher = lambda *args, **kwargs: price_fetcher
    service._setup_token_manager = lambda: None
    service._cleanup_token_manager = lambda token_manager: None
    service._execute_ladder_mode = lambda **kwargs: calls.update(kwargs) or (3, {"status": "ladder"})
    price_fetcher.stop = lambda: None

    response = service._execute_ipo_trigger(
        base_price=500.0,
        order_quantity=10,
        fetch_clients=[object()],
        no_ladder=False,
        base_quantity=5,
        double_buy=True,
        double_buy_quantity=2,
        security_id=101,
        symbol="NABIL",
    )

    assert response == {"status": "ladder"}
    assert calls["order_quantity"] == 10
    assert calls["base_quantity"] == 5
    assert calls["double_buy"] is True
    assert calls["double_buy_quantity"] == 2


def test_execute_ipo_trigger_rejects_just_buy_without_no_ladder():
    service = DummyService()
    price_fetcher = FakePriceFetcher([100.0])
    service._setup_price_fetcher = lambda *args, **kwargs: price_fetcher
    service._setup_token_manager = lambda: None
    service._cleanup_token_manager = lambda token_manager: None
    price_fetcher.stop = lambda: None

    try:
        service._execute_ipo_trigger(
            base_price=500.0,
            order_quantity=10,
            fetch_clients=[object()],
            just_buy=True,
            no_ladder=False,
            security_id=101,
        )
    except ValueError as exc:
        assert "just_buy can only be used with no_ladder=True mode" in str(exc)
    else:
        raise AssertionError("Expected ValueError for invalid just_buy configuration")


def test_execute_ipo_trigger_low_places_order_when_trigger_reached(monkeypatch):
    service = DummyService()
    price_fetcher = FakePriceFetcher([950.0, 909.0, 905.0])
    cleanup = {"stopped": 0, "market_stopped": 0}

    service._setup_price_fetcher = lambda *args, **kwargs: price_fetcher
    service._setup_token_manager = lambda: None
    service._cleanup_token_manager = lambda token_manager: None
    monkeypatch.setattr("services.orders.base_order_service.time.sleep", lambda _seconds: None)

    price_fetcher.stop = lambda: cleanup.update({"stopped": cleanup["stopped"] + 1})
    price_fetcher.stop_market_details = lambda: cleanup.update({"market_stopped": cleanup["market_stopped"] + 1})

    response = service._execute_ipo_trigger_low(
        base_price=1000.0,
        order_quantity=10,
        fetch_clients=[object()],
        limit_price=900.0,
        security_id=101,
        symbol="NABIL",
    )

    assert response["price"] == 900.0
    assert response["quantity"] == 10
    assert cleanup["stopped"] == 1
    assert cleanup["market_stopped"] == 1


def test_execute_ipo_trigger_low_returns_none_on_timeout(monkeypatch):
    service = DummyService()
    price_fetcher = FakePriceFetcher([950.0, 940.0, 930.0])
    state = {"time": 0.0}

    service._setup_price_fetcher = lambda *args, **kwargs: price_fetcher
    service._setup_token_manager = lambda: None
    service._cleanup_token_manager = lambda token_manager: None
    price_fetcher.stop = lambda: None
    price_fetcher.stop_market_details = lambda: None

    def fake_time():
        state["time"] += 0.6
        return state["time"]

    monkeypatch.setattr("services.orders.base_order_service.time.time", fake_time)
    monkeypatch.setattr("services.orders.base_order_service.time.sleep", lambda _seconds: None)

    response = service._execute_ipo_trigger_low(
        base_price=1000.0,
        order_quantity=10,
        fetch_clients=[object()],
        limit_price=900.0,
        timeout_ipo_trigger_low=1,
        security_id=101,
    )

    assert response is None


def test_execute_trigger_sell_places_sell_order_when_trigger_price_reached(monkeypatch):
    service = DummyService()
    fake_fetcher = FakePriceFetcher([None, 490.0, 500.0])
    monkeypatch.setattr("services.fetchers.price_fetcher.PriceFetcher", lambda fetch_client, security_id, poll_interval_ms: fake_fetcher)
    monkeypatch.setattr("services.workflows.specialized_workflows.time.sleep", lambda _seconds: None)

    fetch_client = type(
        "FetchClient",
        (),
        {
            "user_id": "fetch-1",
            "user_config": type("Cfg", (), {"tms_host": "host-1"})(),
        },
    )()

    response = service._execute_trigger_sell(
        sell_price=500.0,
        order_quantity=10,
        fetch_client=fetch_client,
        fetch_security_id=123,
        security_id=101,
        exchange_security_id=202,
        buy_or_sell=1,
    )

    assert response["price"] == 500.0
    assert response["quantity"] == 10
    assert response["params"]["buy_or_sell"] == 2
    assert response["params"]["market_price"] == 500.0
    assert fake_fetcher.started == 1
    assert fake_fetcher.paused == 1
    assert fake_fetcher.resumed == 1
    assert fake_fetcher.stopped == 1


def test_execute_single_ipo_order_maps_tms_order_fields(monkeypatch):
    service = DummyService()
    captured = {}
    monkeypatch.setattr(service, "_execute_ipo_trigger", lambda **kwargs: captured.update(kwargs) or {"status": "ok"})

    response = service._execute_single_ipo_order(
        order={
            "price": 500.0,
            "quantity": 10,
            "security_id": 101,
            "exchange_security_id": 202,
            "fetch_id": 303,
            "ticker": "NABIL",
            "sell": False,
            "no_ladder": True,
            "just_buy": True,
        },
        fetch_clients=[object()],
        already_triggered=True,
    )

    assert response == {"status": "ok"}
    assert captured["base_price"] == 500.0
    assert captured["order_quantity"] == 10
    assert captured["security_id"] == 101
    assert captured["exchange_security_id"] == 202
    assert captured["buy_or_sell"] == 1
    assert captured["fetch_security_id"] == 303
    assert captured["ticker"] == "NABIL"
    assert captured["no_ladder"] is True
    assert captured["just_buy"] is True
    assert captured["already_triggered"] is True


def test_execute_multi_queue_ipo_trigger_preserves_just_buy_and_fade_settings(monkeypatch):
    service = DummyService()
    calls = []

    class FakeMultiFetcher:
        def __init__(self, symbols_config, fetch_clients, poll_interval_ms, user_id, is_atrad):
            self.symbols_config = symbols_config
            self.fetch_clients = fetch_clients
            self.poll_interval_ms = poll_interval_ms
            self.user_id = user_id
            self.is_atrad = is_atrad

        def start(self):
            return None

        def stop(self):
            return None

        def get_priority_symbol(self):
            return "BBB"

        def get_all_ltps(self):
            return {"AAA": 100.0, "BBB": 110.0}

    monkeypatch.setattr(
        "services.fetchers.multi_symbol_price_fetcher.MultiSymbolSequentialPriceFetcher",
        FakeMultiFetcher,
    )
    monkeypatch.setattr("services.workflows.coordinated_workflows.time.sleep", lambda _seconds: None)
    monkeypatch.setattr(
        service,
        "_execute_ipo_trigger",
        lambda **kwargs: calls.append(kwargs) or {"status": "ok", "ticker": kwargs.get("ticker")},
    )

    result = service._execute_multi_queue_ipo_trigger(
        orders=[
            {
                "id": "order-a",
                "ticker": "AAA",
                "price": 100.0,
                "quantity": 10,
                "security_id": 101,
                "exchange_security_id": 201,
                "fetch_id": 301,
                "mode": "ipo-trigger",
                "queue_id": 1,
                "multi_queue": True,
                "no_ladder": True,
                "just_buy": True,
                "just_buy_interval_ms": 100,
                "just_buy_timeout": 5,
                "just_buy_pre_wait_ms": 0,
                "just_buy_max_requests": None,
                "just_buy_fade_interval_ms": 250,
                "just_buy_fade_timeout": 2,
            },
            {
                "id": "order-b",
                "ticker": "BBB",
                "price": 110.0,
                "quantity": 11,
                "security_id": 102,
                "exchange_security_id": 202,
                "fetch_id": 302,
                "mode": "ipo-trigger",
                "queue_id": 1,
                "multi_queue": True,
                "no_ladder": True,
                "just_buy": True,
                "just_buy_interval_ms": 120,
                "just_buy_timeout": 6,
                "just_buy_pre_wait_ms": 100,
                "just_buy_max_requests": None,
                "just_buy_fade_interval_ms": 300,
                "just_buy_fade_timeout": 3,
            },
        ],
        fetch_clients=[object()],
    )

    assert result["successful_orders"] == ["order-b", "order-a"]
    assert len(calls) == 2

    priority_call = calls[0]
    assert priority_call["ticker"] == "BBB"
    assert priority_call["already_triggered"] is True
    assert priority_call["just_buy"] is True
    assert priority_call["just_buy_interval_ms"] == 120
    assert priority_call["just_buy_timeout"] == 6
    assert priority_call["just_buy_pre_wait_ms"] == 100
    assert priority_call["just_buy_fade_interval_ms"] == 300
    assert priority_call["just_buy_fade_timeout"] == 3

    remaining_call = calls[1]
    assert remaining_call["ticker"] == "AAA"
    assert remaining_call["already_triggered"] is False
    assert remaining_call["just_buy"] is True
    assert remaining_call["just_buy_interval_ms"] == 100
    assert remaining_call["just_buy_timeout"] == 5
    assert remaining_call["just_buy_fade_interval_ms"] == 250
    assert remaining_call["just_buy_fade_timeout"] == 2


def test_place_sell_order_with_retry_retries_and_sets_response(monkeypatch):
    service = DummyService()
    attempts = {"count": 0}
    sleep_calls = []
    monkeypatch.setattr("services.workflows.coordinated_workflows.time.sleep", lambda seconds: sleep_calls.append(seconds))

    def flaky_place(price, quantity, **params):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary")
        payload = {"price": price, "quantity": quantity, "params": params}
        service.placed_orders.append(payload)
        return payload

    service._place_single_order = flaky_place

    class Flag:
        def __init__(self):
            self.value = False

        def set(self):
            self.value = True

    success_flag = Flag()
    response_container = {"response": None}

    service._place_sell_order_with_retry(
        sell_price=500.0,
        sell_quantity=10,
        success_flag=success_flag,
        response_container=response_container,
        is_atrad=False,
        security_id=101,
        exchange_security_id=202,
        symbol=None,
        market_price=499.5,
        max_retries=2,
    )

    assert attempts["count"] == 2
    assert sleep_calls == [0.1]
    assert success_flag.value is True
    assert response_container["response"]["params"]["buy_or_sell"] == 2
