from argparse import Namespace

import pytest

import app.execution as execution
import app.factories as factories
import main
from config import ATRADUserConfig
from app.models import ResolvedTicker


class DummyConfig:
    def __init__(self, user_id="main-user"):
        self.user_id = user_id
        self.tms_host = "example.test"


def make_args(**overrides):
    data = {
        "user_config": "users/main.json",
        "pool_users": None,
        "order_store": None,
        "ticker": None,
        "security_id": 101,
        "exchange_security_id": 202,
        "price": 500.0,
        "quantity": 10,
        "ipo_trigger": False,
        "ipo_trigger_low": False,
        "trigger_sell": False,
        "ipo_sell_buy_trigger": False,
        "fetch_user": None,
        "fetch_users": None,
        "seller": None,
        "buyer": None,
        "sell_quantity": None,
        "sell_pre_wait_ms": 5000,
        "skip_first": False,
        "limit": None,
        "double_buy": False,
        "double_buy_quantity": None,
        "just_buy": False,
        "just_buy_users": None,
        "just_buy_interval": 100,
        "just_buy_timeout": 5,
        "atrad_fetch": False,
        "sell": False,
    }
    data.update(overrides)
    return Namespace(**data)


def test_validate_args_rejects_multiple_mode_flags():
    args = make_args(ipo_trigger=True, trigger_sell=True, fetch_user="users/fetch.json")

    with pytest.raises(ValueError, match="Cannot use multiple mode flags together"):
        main.validate_args(args)


def test_validate_args_requires_fetch_user_for_trigger_mode():
    args = make_args(ipo_trigger=True)

    with pytest.raises(ValueError, match="--fetch-user or --fetch-users is required when using --ipo-trigger mode"):
        main.validate_args(args)


def test_validate_args_accepts_pool_users_for_order_store_only():
    args = make_args(
        user_config=None,
        pool_users=["users/u1.json", "users/u2.json"],
        order_store="stores/order_store.json",
    )

    main.validate_args(args)


def test_validate_args_rejects_pool_users_with_user_config():
    args = make_args(
        pool_users=["users/u1.json", "users/u2.json"],
        order_store="stores/order_store.json",
    )

    with pytest.raises(ValueError, match="--pool-users cannot be used together with --user-config"):
        main.validate_args(args)


def test_execute_order_for_user_uses_scheduler_for_scheduled_tms(monkeypatch):
    calls = {}

    class FakeTMSClient:
        def __init__(self, config):
            self.user_id = config.user_id
            calls["client_config"] = config

    class FakeOrderService:
        def __init__(self, client):
            self.client = client
            self.execute_order = lambda **kwargs: {"status": "immediate", "kwargs": kwargs}
            calls["service_client"] = client

    def fake_schedule_order(time_str, order_func, main_client=None, fetch_clients=None, just_buy_clients=None, user_id="unknown", **order_params):
        calls["scheduled"] = {
            "time_str": time_str,
            "order_func": order_func,
            "main_client": main_client,
            "fetch_clients": fetch_clients,
            "just_buy_clients": just_buy_clients,
            "user_id": user_id,
            "order_params": order_params,
        }
        return {"status": "scheduled"}

    monkeypatch.setattr(factories, "TMSClient", FakeTMSClient)
    monkeypatch.setattr(factories, "OrderService", FakeOrderService)
    monkeypatch.setattr(execution.OrderScheduler, "schedule_order", staticmethod(fake_schedule_order))

    fetch_configs = [DummyConfig("fetch-1"), DummyConfig("fetch-2")]
    result = main.execute_order_for_user(
        user_config=DummyConfig("primary"),
        order_params={"security_id": 101, "symbol": "NABIL"},
        scheduled_time="10:30",
        fetch_user_configs=fetch_configs,
        is_atrad_fetch=False,
    )

    assert result == {"status": "scheduled"}
    assert calls["scheduled"]["time_str"] == "10:30"
    assert calls["scheduled"]["user_id"] == "primary"
    assert len(calls["scheduled"]["fetch_clients"]) == 2
    assert calls["scheduled"]["order_params"] == {"security_id": 101, "symbol": "NABIL"}


def test_execute_order_for_user_uses_atrad_immediate_execution(monkeypatch, atrad_user_config):
    calls = {}

    class FakeATRADClient:
        def __init__(self, config):
            self.user_id = config.user_id
            calls.setdefault("clients", []).append(config.user_id)

    class FakeATRADOrderService:
        def __init__(self, client):
            self.client = client

        def execute_order(self, **kwargs):
            calls["execute_order"] = kwargs
            return {"status": "ok"}

    monkeypatch.setattr(factories, "ATRADClient", FakeATRADClient)
    monkeypatch.setattr(factories, "ATRADOrderService", FakeATRADOrderService)

    fetch_config = ATRADUserConfig.from_dict(
        {
            "user_id": "fetch-atrad",
            "atrad_base_url": "https://atrad.test",
            "atrad_host": "atrad.test",
            "username": "fetch-user",
            "password": "fetch-pass",
            "account_id": "ACC-2",
        }
    )

    result = main.execute_order_for_user(
        user_config=atrad_user_config,
        order_params={"symbol": "NABIL", "order_price": 500},
        fetch_user_configs=[fetch_config],
        is_atrad_fetch=True,
    )

    assert result == {"status": "ok"}
    assert calls["clients"] == ["fetch-atrad", "atrad-user"]
    assert len(calls["execute_order"]["fetch_clients"]) == 1
    assert calls["execute_order"]["symbol"] == "NABIL"


def test_execute_from_order_store_overrides_first_start_time_and_marks_success(monkeypatch):
    holder = {}

    class FakeOrderStore:
        def __init__(self, _path):
            self.orders = [
                {
                    "id": "order-1",
                    "ticker": "nabil",
                    "price": 500.0,
                    "quantity": 10,
                    "mode": "normal",
                    "queue_id": 1,
                    "time": None,
                    "sell": False,
                    "skip_first": False,
                    "skip_second_last": False,
                    "no_ladder": False,
                    "limit": None,
                    "base_quantity": 10,
                    "double_buy": False,
                    "double_buy_quantity": None,
                    "just_buy": False,
                    "just_buy_interval_ms": 100,
                    "just_buy_timeout": 5,
                    "just_buy_pre_wait_ms": 0,
                    "just_buy_max_requests": None,
                    "just_buy_fade_interval_ms": None,
                    "just_buy_fade_timeout": None
                }
            ]
            self.marked_success = []
            self.marked_failed = []
            holder["store"] = self

        def get_order_summary(self):
            return "summary"

        def get_executable_orders(self):
            return list(self.orders)

        def validate_order(self, order):
            return dict(order)

        def mark_success(self, order_id):
            self.marked_success.append(order_id)

        def mark_failed(self, order_id):
            self.marked_failed.append(order_id)

    class FakeTickerStore:
        def lookup(self, ticker):
            assert ticker == "nabil"
            return 101, 202

        def get_fetch_id(self, ticker, host=None):
            assert ticker == "nabil"
            assert host == "example.test"
            return 303

    execution_calls = {}

    def fake_execute_order_for_user(user_config, order_params, scheduled_time=None, fetch_user_configs=None, is_atrad_fetch=False):
        execution_calls["call"] = {
            "user_config": user_config,
            "order_params": order_params,
            "scheduled_time": scheduled_time,
            "fetch_user_configs": fetch_user_configs,
            "is_atrad_fetch": is_atrad_fetch,
        }
        return {"status": "ok"}

    monkeypatch.setattr(execution, "OrderStore", FakeOrderStore)
    monkeypatch.setattr(factories, "get_ticker_store", lambda: FakeTickerStore())
    monkeypatch.setattr(execution, "execute_order_for_user", fake_execute_order_for_user)

    user_config = DummyConfig("main-user")
    fetch_configs = [DummyConfig("fetch-user")]
    result = main.execute_from_order_store(
        user_config=user_config,
        order_store_path="stores/order_store.json",
        fetch_user_configs=fetch_configs,
        is_atrad_fetch=False,
        start_time="10:45",
    )

    assert result == {"status": "ok"}
    assert holder["store"].marked_success == ["order-1"]
    assert holder["store"].marked_failed == []
    assert execution_calls["call"]["scheduled_time"] == "10:45"
    assert execution_calls["call"]["order_params"]["fetch_id"] == 303
    assert execution_calls["call"]["order_params"]["symbol"] == "NABIL"


def test_execute_from_order_store_prefers_order_level_just_buy_users(monkeypatch):
    holder = {}

    class FakeOrderStore:
        def __init__(self, _path):
            self.orders = [
                {
                    "id": "order-1",
                    "ticker": "nabil",
                    "price": 500.0,
                    "quantity": 10,
                    "mode": "ipo-trigger",
                    "queue_id": 1,
                    "time": None,
                    "sell": False,
                    "skip_first": False,
                    "skip_second_last": False,
                    "no_ladder": True,
                    "limit": None,
                    "base_quantity": 10,
                    "double_buy": False,
                    "double_buy_quantity": None,
                    "just_buy": True,
                    "just_buy_users": [
                        {"user": "users/order-jb1.json", "quantity": 337},
                        {"user": "users/order-jb2.json"},
                    ],
                    "just_buy_interval_ms": 100,
                    "just_buy_timeout": 5,
                    "just_buy_pre_wait_ms": 0,
                    "just_buy_max_requests": None,
                    "just_buy_fade_interval_ms": None,
                    "just_buy_fade_timeout": None,
                    "multi_queue": False,
                }
            ]
            self.marked_success = []
            holder["store"] = self

        def get_order_summary(self):
            return "summary"

        def get_executable_orders(self):
            return list(self.orders)

        def validate_order(self, order):
            return dict(order)

        def mark_success(self, order_id):
            self.marked_success.append(order_id)

        def mark_failed(self, order_id):
            raise AssertionError("order should not fail")

    class FakeTickerStore:
        def lookup(self, ticker):
            assert ticker == "nabil"
            return 101, 202

        def get_fetch_id(self, ticker, host=None):
            assert ticker == "nabil"
            assert host == "example.test"
            return 303

    execution_calls = {}

    def fake_execute_order_for_user(user_config, order_params, scheduled_time=None, fetch_user_configs=None, is_atrad_fetch=False, just_buy_user_configs=None):
        execution_calls["call"] = {
            "user_config": user_config,
            "order_params": order_params,
            "scheduled_time": scheduled_time,
            "fetch_user_configs": fetch_user_configs,
            "is_atrad_fetch": is_atrad_fetch,
            "just_buy_user_configs": just_buy_user_configs,
        }
        return {"status": "ok"}

    monkeypatch.setattr(execution, "OrderStore", FakeOrderStore)
    monkeypatch.setattr(factories, "get_ticker_store", lambda: FakeTickerStore())
    monkeypatch.setattr(execution, "execute_order_for_user", fake_execute_order_for_user)
    monkeypatch.setattr(
        execution,
        "load_just_buy_user_specs",
        lambda paths, _role_label: [
            {
                "user_config": DummyConfig(f"loaded:{entry['user']}"),
                "quantity_override": entry.get("quantity"),
            }
            for entry in paths
        ],
    )

    result = main.execute_from_order_store(
        user_config=DummyConfig("main-user"),
        order_store_path="stores/order_store.json",
        fetch_user_configs=[DummyConfig("fetch-user")],
        just_buy_user_configs=[DummyConfig("global-jb")],
        is_atrad_fetch=False,
    )

    assert result == {"status": "ok"}
    assert holder["store"].marked_success == ["order-1"]
    assert [
        (entry["user_config"].user_id, entry["quantity_override"])
        for entry in execution_calls["call"]["just_buy_user_configs"]
    ] == [
        ("loaded:users/order-jb1.json", 337),
        ("loaded:users/order-jb2.json", None),
    ]


def test_execute_manual_order_builds_shared_order_params(monkeypatch):
    execution_calls = {}

    class FakeTickerStore:
        def get_name(self, ticker):
            assert ticker == "NABIL"
            return "Nabil Bank"

    def fake_resolve_ticker(ticker, fetch_user_configs=None, is_atrad_fetch=False):
        assert ticker == "NABIL"
        assert len(fetch_user_configs) == 1
        assert is_atrad_fetch is False
        return ResolvedTicker(
            ticker="NABIL",
            security_id=101,
            exchange_security_id=202,
            fetch_id=303,
            symbol="NABIL",
            fetch_host="example.test",
        )

    def fake_execute_order_for_user(user_config, order_params, scheduled_time=None, fetch_user_configs=None, is_atrad_fetch=False):
        execution_calls["call"] = {
            "user_config": user_config,
            "order_params": order_params,
            "scheduled_time": scheduled_time,
            "fetch_user_configs": fetch_user_configs,
            "is_atrad_fetch": is_atrad_fetch,
        }
        return {"status": "ok"}

    monkeypatch.setattr(execution, "resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(execution, "execute_order_for_user", fake_execute_order_for_user)
    monkeypatch.setattr("utils.get_ticker_store", lambda: FakeTickerStore())

    result = execution.execute_manual_order(
        user_config=DummyConfig("main-user"),
        args=make_args(
            ticker="NABIL",
            price=500.0,
            quantity=10,
            ipo_trigger=True,
            fetch_user="users/fetch.json",
        ),
        fetch_user_configs=[DummyConfig("fetch-user")],
        is_atrad_fetch=False,
    )

    assert result == {"status": "ok"}
    assert execution_calls["call"]["scheduled_time"] is None
    assert execution_calls["call"]["order_params"]["fetch_id"] == 303
    assert execution_calls["call"]["order_params"]["symbol"] == "NABIL"
    assert execution_calls["call"]["order_params"]["ticker"] == "NABIL"
    assert execution_calls["call"]["order_params"]["ipo_trigger_mode"] is True


def test_execute_from_order_store_uses_multi_queue_executor(monkeypatch):
    holder = {}

    class FakeOrderStore:
        def __init__(self, _path):
            self.orders = [
                {
                    "id": "mq-1",
                    "ticker": "aaa",
                    "price": 100.0,
                    "quantity": 10,
                    "mode": "ipo-trigger",
                    "queue_id": 1,
                    "multi_queue": True,
                    "no_ladder": True,
                    "time": None,
                },
                {
                    "id": "mq-2",
                    "ticker": "bbb",
                    "price": 110.0,
                    "quantity": 11,
                    "mode": "ipo-trigger",
                    "queue_id": 1,
                    "multi_queue": True,
                    "no_ladder": True,
                    "time": None,
                },
            ]
            holder["store"] = self

        def get_order_summary(self):
            return "summary"

        def get_executable_orders(self):
            return list(self.orders)

        def validate_order(self, order):
            normalized = {
                "sell": False,
                "skip_first": False,
                "skip_second_last": False,
                "limit": None,
                "base_quantity": 10,
                "double_buy": False,
                "double_buy_quantity": None,
                "just_buy": False,
                "just_buy_interval_ms": 100,
                "just_buy_timeout": 5,
                "just_buy_pre_wait_ms": 0,
                "just_buy_max_requests": None,
                "just_buy_fade_interval_ms": None,
                "just_buy_fade_timeout": None
            }
            normalized.update(order)
            return normalized

        def mark_success(self, order_id):
            raise AssertionError("mark_success should be handled by multi-queue path")

        def mark_failed(self, order_id):
            raise AssertionError("mark_failed should be handled by multi-queue path")

    calls = {}

    def fake_execute_multi_queue_group(
        user_config,
        orders,
        order_store,
        fetch_user_configs=None,
        is_atrad_fetch=False,
        just_buy_user_configs=None,
        user_pool=None,
    ):
        calls["multi_queue"] = {
            "user_config": user_config,
            "orders": orders,
            "order_store": order_store,
            "fetch_user_configs": fetch_user_configs,
            "is_atrad_fetch": is_atrad_fetch,
            "just_buy_user_configs": just_buy_user_configs,
            "user_pool": user_pool,
        }
        return {"responses": [], "successful_orders": ["mq-1", "mq-2"], "failed_orders": []}

    monkeypatch.setattr(execution, "OrderStore", FakeOrderStore)
    monkeypatch.setattr(execution, "execute_multi_queue_group", fake_execute_multi_queue_group)

    result = main.execute_from_order_store(
        user_config=DummyConfig("main-user"),
        order_store_path="stores/order_store.json",
        fetch_user_configs=[DummyConfig("fetch-user")],
        is_atrad_fetch=False,
    )

    assert result["successful_orders"] == ["mq-1", "mq-2"]
    assert [order["id"] for order in calls["multi_queue"]["orders"]] == ["mq-1", "mq-2"]


def test_execute_from_order_store_uses_trigger_sell_queue_executor(monkeypatch):
    holder = {}

    class FakeOrderStore:
        def __init__(self, _path):
            self.orders = [
                {
                    "id": "ts-1",
                    "ticker": "aaa",
                    "price": 100.0,
                    "quantity": 10,
                    "mode": "trigger-sell",
                    "queue_id": 1,
                    "trigger_sell_queue": True,
                    "time": None,
                },
                {
                    "id": "ts-2",
                    "ticker": "bbb",
                    "price": 110.0,
                    "quantity": 11,
                    "mode": "trigger-sell",
                    "queue_id": 1,
                    "trigger_sell_queue": True,
                    "time": None,
                },
            ]
            holder["store"] = self

        def get_order_summary(self):
            return "summary"

        def get_executable_orders(self):
            return list(self.orders)

        def validate_order(self, order):
            normalized = {"trigger_sell_queue": True, "multi_queue": False}
            normalized.update(order)
            return normalized

    calls = {}

    def fake_execute_trigger_sell_queue_group(
        user_config,
        orders,
        order_store,
        fetch_user_configs=None,
        is_atrad_fetch=False,
        user_pool=None,
    ):
        calls["trigger_sell_queue"] = {
            "user_config": user_config,
            "orders": orders,
            "order_store": order_store,
            "fetch_user_configs": fetch_user_configs,
            "is_atrad_fetch": is_atrad_fetch,
            "user_pool": user_pool,
        }
        return {"responses": [], "successful_orders": ["ts-1", "ts-2"], "failed_orders": []}

    monkeypatch.setattr(execution, "OrderStore", FakeOrderStore)
    monkeypatch.setattr(execution, "execute_trigger_sell_queue_group", fake_execute_trigger_sell_queue_group)

    result = main.execute_from_order_store(
        user_config=DummyConfig("main-user"),
        order_store_path="stores/order_store.json",
        fetch_user_configs=[DummyConfig("fetch-user")],
        is_atrad_fetch=False,
    )

    assert result["successful_orders"] == ["ts-1", "ts-2"]
    assert [order["id"] for order in calls["trigger_sell_queue"]["orders"]] == ["ts-1", "ts-2"]


def test_execute_multi_queue_group_updates_store_after_each_completed_order(monkeypatch):
    events = []

    class FakeOrderStore:
        def mark_success(self, order_id):
            events.append(f"success:{order_id}")

        def mark_failed(self, order_id):
            events.append(f"failed:{order_id}")

    class FakePlatform:
        def __init__(self):
            self.client = object()
            self.service = self

        def _execute_multi_queue_ipo_trigger(self, orders, fetch_clients, on_order_complete=None, order_executor=None):
            events.append("start")
            if on_order_complete is not None:
                on_order_complete(orders[0]["id"], True, None)
                events.append("after-first")
                on_order_complete(orders[1]["id"], False, RuntimeError("boom"))
                events.append("after-second")
            return {
                "responses": [{"status": "ok"}],
                "successful_orders": [orders[0]["id"]],
                "failed_orders": [orders[1]["id"]],
            }

    monkeypatch.setattr(execution, "create_order_client_and_service", lambda _user_config: FakePlatform())
    monkeypatch.setattr(execution, "create_fetch_clients", lambda _configs, _is_atrad: ["fetch-client"])
    monkeypatch.setattr(execution, "resolve_ticker", lambda ticker, *_args: ResolvedTicker(
        ticker=ticker.upper(),
        security_id=101,
        exchange_security_id=202,
        fetch_id=303,
        symbol=ticker.upper(),
    ))

    with pytest.raises(ValueError, match="Multi-queue had 1 failed order"):
        execution.execute_multi_queue_group(
            user_config=DummyConfig("main-user"),
            orders=[
                {"id": "mq-1", "ticker": "aaa", "symbol": "AAA", "price": 100.0, "quantity": 10, "queue_id": 1, "multi_queue": True, "no_ladder": True},
                {"id": "mq-2", "ticker": "bbb", "symbol": "BBB", "price": 110.0, "quantity": 11, "queue_id": 1, "multi_queue": True, "no_ladder": True},
            ],
            order_store=FakeOrderStore(),
            fetch_user_configs=[DummyConfig("fetch-user")],
            is_atrad_fetch=False,
        )

    assert events == [
        "start",
        "success:mq-1",
        "after-first",
        "failed:mq-2",
        "after-second",
    ]


def test_execute_multi_queue_group_resolves_order_level_just_buy_users(monkeypatch):
    captured = {}

    class FakeWorkerService:
        def __init__(self, user_id):
            self.user_id = user_id

    class FakeBundle:
        def __init__(self, user_id, quantity_override):
            self.client = DummyConfig(user_id)
            self.service = FakeWorkerService(user_id)
            self.quantity_override = quantity_override

    class FakePlatform:
        def __init__(self):
            self.client = object()
            self.service = self

        def _execute_multi_queue_ipo_trigger(self, orders, fetch_clients, on_order_complete=None, order_executor=None):
            captured["orders"] = orders
            captured["fetch_clients"] = fetch_clients
            captured["order_executor"] = order_executor
            return {
                "responses": [],
                "successful_orders": [order["id"] for order in orders],
                "failed_orders": [],
            }

    monkeypatch.setattr(execution, "create_order_client_and_service", lambda _user_config: FakePlatform())
    monkeypatch.setattr(execution, "create_fetch_clients", lambda _configs, _is_atrad: ["fetch-client"])
    monkeypatch.setattr(
        execution,
        "resolve_ticker",
        lambda ticker, *_args: ResolvedTicker(
            ticker=ticker.upper(),
            security_id=101,
            exchange_security_id=202,
            fetch_id=303,
            symbol=ticker.upper(),
        ),
    )
    monkeypatch.setattr(
        execution,
        "load_just_buy_user_specs",
        lambda paths, _role_label: [
            {
                "user_config": DummyConfig(f"loaded:{entry['user']}"),
                "quantity_override": entry.get("quantity"),
            }
            for entry in paths
        ],
    )
    monkeypatch.setattr(
        execution,
        "create_order_bundles",
        lambda specs: [
            FakeBundle(spec["user_config"].user_id, spec.get("quantity_override"))
            for spec in specs
        ],
    )

    result = execution.execute_multi_queue_group(
        user_config=DummyConfig("main-user"),
        orders=[
            {
                "id": "mq-1",
                "ticker": "aaa",
                "symbol": "AAA",
                "price": 100.0,
                "quantity": 10,
                "queue_id": 1,
                "multi_queue": True,
                "no_ladder": True,
                "just_buy": True,
                "just_buy_users": [
                    {"user": "users/jb1.json", "quantity": 337},
                    {"user": "users/jb2.json"},
                ],
            },
        ],
        order_store=type("Store", (), {"mark_success": lambda *_args: None, "mark_failed": lambda *_args: None})(),
        fetch_user_configs=[DummyConfig("fetch-user")],
        is_atrad_fetch=False,
    )

    assert result["successful_orders"] == ["mq-1"]
    just_buy_services = captured["orders"][0]["just_buy_services"]
    assert [
        (entry["service"].user_id, entry["quantity_override"])
        for entry in just_buy_services
    ] == [
        ("loaded:users/jb1.json", 337),
        ("loaded:users/jb2.json", None),
    ]


def test_execute_multi_queue_group_resolves_pooled_users_per_order(monkeypatch):
    captured = {"executed": []}

    class FakeOrderService:
        def __init__(self, user_id):
            self.user_id = user_id

        def _execute_single_ipo_order(self, order, fetch_clients, already_triggered):
            captured["executed"].append(
                {
                    "order_id": order["id"],
                    "service_user_id": self.user_id,
                    "fetch_client_ids": list(fetch_clients),
                    "already_triggered": already_triggered,
                }
            )
            return {"status": "ok", "order_id": order["id"], "user_id": self.user_id}

    class FakePlatform:
        def __init__(self, user_id):
            self.client = type("Client", (), {"user_id": user_id})()
            self.service = FakeOrderService(user_id)

    class MonitoringPlatform:
        def __init__(self):
            self.client = object()
            self.service = self
            self._delegate = FakeOrderService("main-a")

        def _execute_multi_queue_ipo_trigger(self, orders, fetch_clients, on_order_complete=None, order_executor=None):
            captured["monitor_fetch_clients"] = list(fetch_clients)
            priority_response = order_executor(orders[1], True)
            if on_order_complete is not None:
                on_order_complete(orders[1]["id"], True, None)
            remaining_response = order_executor(orders[0], False)
            if on_order_complete is not None:
                on_order_complete(orders[0]["id"], True, None)
            return {
                "responses": [priority_response, remaining_response],
                "successful_orders": [orders[1]["id"], orders[0]["id"]],
                "failed_orders": [],
            }

        def _execute_single_ipo_order(self, order, fetch_clients, already_triggered):
            return self._delegate._execute_single_ipo_order(order, fetch_clients, already_triggered)

    user_a = DummyConfig("main-a")
    user_b = DummyConfig("main-b")
    user_c = DummyConfig("main-c")
    pool = execution.UserPool(
        users_by_id={cfg.user_id: cfg for cfg in [user_a, user_b, user_c]},
        ordered_users=[user_a, user_b, user_c],
        is_atrad=False,
    )

    monkeypatch.setattr(
        execution,
        "create_order_client_and_service",
        lambda user_config: MonitoringPlatform() if user_config.user_id == "main-a" else FakePlatform(user_config.user_id),
    )
    monkeypatch.setattr(
        execution,
        "create_fetch_clients",
        lambda configs, _is_atrad: [cfg.user_id for cfg in configs],
    )
    monkeypatch.setattr(
        execution,
        "resolve_ticker",
        lambda ticker, *_args: ResolvedTicker(
            ticker=ticker.upper(),
            security_id=101,
            exchange_security_id=202,
            fetch_id=303,
            symbol=ticker.upper(),
        ),
    )

    store_events = []
    order_store = type(
        "Store",
        (),
        {
            "mark_success": lambda _self, order_id: store_events.append(("success", order_id)),
            "mark_failed": lambda _self, order_id: store_events.append(("failed", order_id)),
        },
    )()

    result = execution.execute_multi_queue_group(
        user_config=user_a,
        orders=[
            {
                "id": "mq-1",
                "ticker": "aaa",
                "symbol": "AAA",
                "user_id": "main-a",
                "price": 100.0,
                "quantity": 10,
                "queue_id": 1,
                "multi_queue": True,
                "no_ladder": True,
            },
            {
                "id": "mq-2",
                "ticker": "bbb",
                "symbol": "BBB",
                "user_id": "main-b",
                "price": 110.0,
                "quantity": 11,
                "queue_id": 1,
                "multi_queue": True,
                "no_ladder": True,
            },
        ],
        order_store=order_store,
        fetch_user_configs=[user_b, user_c],
        is_atrad_fetch=False,
        user_pool=pool,
    )

    assert result["successful_orders"] == ["mq-2", "mq-1"]
    assert captured["monitor_fetch_clients"] == ["main-a", "main-b", "main-c"]
    assert captured["executed"] == [
        {
            "order_id": "mq-2",
            "service_user_id": "main-b",
            "fetch_client_ids": ["main-a", "main-c"],
            "already_triggered": True,
        },
        {
            "order_id": "mq-1",
            "service_user_id": "main-a",
            "fetch_client_ids": ["main-b", "main-c"],
            "already_triggered": False,
        },
    ]
    assert store_events == [("success", "mq-2"), ("success", "mq-1")]


def test_execute_trigger_sell_queue_group_resolves_pooled_users_per_order(monkeypatch):
    captured = {"placed": []}

    class FakeSellService:
        def __init__(self, user_id):
            self.user_id = user_id

        def _place_single_order(self, **kwargs):
            captured["placed"].append({"user_id": self.user_id, **kwargs})
            return {"status": "ok", "user_id": self.user_id}

    class FakePlatform:
        def __init__(self, user_id):
            self.client = type("Client", (), {"user_id": user_id})()
            self.service = FakeSellService(user_id)

    user_a = DummyConfig("main-a")
    user_b = DummyConfig("main-b")
    user_c = DummyConfig("main-c")
    user_a.trigger_sell_poll_interval_ms = 100
    user_b.trigger_sell_poll_interval_ms = 100
    user_c.trigger_sell_poll_interval_ms = 100
    user_a.multi_fetch_poll_interval_ms = 100
    user_b.multi_fetch_poll_interval_ms = 100
    user_c.multi_fetch_poll_interval_ms = 100
    user_a.multi_fetch_slow_poll_interval_ms = 500
    user_b.multi_fetch_slow_poll_interval_ms = 500
    user_c.multi_fetch_slow_poll_interval_ms = 500
    pool = execution.UserPool(
        users_by_id={cfg.user_id: cfg for cfg in [user_a, user_b, user_c]},
        ordered_users=[user_a, user_b, user_c],
        is_atrad=False,
    )

    class FakeFetcher:
        priority_calls = 0

        def __init__(self, symbols_config, fetch_clients, poll_interval_ms, user_id, is_atrad):
            self._symbols_config = symbols_config
            self.poll_interval_ms = poll_interval_ms
            captured["monitor_fetch_clients"] = list(fetch_clients)
            captured["monitor_user_id"] = user_id
            captured["is_atrad"] = is_atrad

        def start(self):
            return None

        def stop(self):
            return None

        def update_poll_interval_ms(self, poll_interval_ms):
            self.poll_interval_ms = poll_interval_ms

        def get_priority_symbol(self):
            if len(self._symbols_config) == 1:
                return self._symbols_config[0].symbol
            symbol = self._symbols_config[1].symbol if FakeFetcher.priority_calls == 0 else self._symbols_config[0].symbol
            FakeFetcher.priority_calls += 1
            return symbol

        def get_all_ltps(self):
            return {cfg.symbol: cfg.switch_threshold for cfg in self._symbols_config}

    monkeypatch.setattr(execution, "create_order_client_and_service", lambda user_config: FakePlatform(user_config.user_id))
    monkeypatch.setattr(execution, "create_fetch_clients", lambda configs, _is_atrad: [cfg.user_id for cfg in configs])
    monkeypatch.setattr(
        execution,
        "resolve_ticker",
        lambda ticker, *_args: ResolvedTicker(
            ticker=ticker.upper(),
            security_id=101,
            exchange_security_id=202,
            fetch_id=303,
            symbol=ticker.upper(),
        ),
    )
    monkeypatch.setattr(execution, "MultiSymbolSequentialPriceFetcher", FakeFetcher)

    store_events = []
    order_store = type(
        "Store",
        (),
        {
            "mark_success": lambda _self, order_id: store_events.append(("success", order_id)),
            "mark_failed": lambda _self, order_id: store_events.append(("failed", order_id)),
        },
    )()

    result = execution.execute_trigger_sell_queue_group(
        user_config=user_a,
        orders=[
            {
                "id": "ts-1",
                "ticker": "aaa",
                "symbol": "AAA",
                "user_id": "main-a",
                "price": 100.0,
                "quantity": 10,
                "queue_id": 1,
                "mode": "trigger-sell",
                "trigger_sell_queue": True,
                "time": None,
                "limit": None,
            },
            {
                "id": "ts-2",
                "ticker": "bbb",
                "symbol": "BBB",
                "user_id": "main-b",
                "price": 110.0,
                "quantity": 11,
                "queue_id": 1,
                "mode": "trigger-sell",
                "trigger_sell_queue": True,
                "time": None,
                "limit": None,
            },
        ],
        order_store=order_store,
        fetch_user_configs=[user_b, user_c],
        is_atrad_fetch=False,
        user_pool=pool,
    )

    assert set(result["successful_orders"]) == {"ts-1", "ts-2"}
    assert captured["monitor_fetch_clients"] == ["main-a", "main-b", "main-c"]
    placed_by_user = {entry["user_id"]: entry for entry in captured["placed"]}
    assert placed_by_user["main-a"] == {
        "user_id": "main-a",
        "price": 100.0,
        "quantity": 10,
        "security_id": 101,
        "exchange_security_id": 202,
        "buy_or_sell": 2,
        "order_type": "LMT",
        "order_validity": "DAY",
        "market_price": pytest.approx(97.1),
    }
    assert placed_by_user["main-b"] == {
        "user_id": "main-b",
        "price": 110.0,
        "quantity": 11,
        "security_id": 101,
        "exchange_security_id": 202,
        "buy_or_sell": 2,
        "order_type": "LMT",
        "order_validity": "DAY",
        "market_price": pytest.approx(106.8),
    }
    assert set(store_events) == {("success", "ts-1"), ("success", "ts-2")}


def test_execute_trigger_sell_queue_group_switches_from_slow_to_fast_polling(monkeypatch):
    captured = {}

    class FakeSellService:
        def __init__(self, user_id):
            self.user_id = user_id

        def _place_single_order(self, **kwargs):
            return {"status": "ok", "user_id": self.user_id, **kwargs}

    class FakePlatform:
        def __init__(self, user_id):
            self.client = type("Client", (), {"user_id": user_id})()
            self.service = FakeSellService(user_id)

    user_a = DummyConfig("main-a")
    user_a.multi_fetch_poll_interval_ms = 100
    user_a.multi_fetch_slow_poll_interval_ms = 500

    class FakeFetcher:
        def __init__(self, symbols_config, fetch_clients, poll_interval_ms, user_id, is_atrad):
            self._symbols_config = symbols_config
            self.poll_interval_ms = poll_interval_ms
            self.update_calls = []
            self.priority_calls = 0
            captured["fetcher"] = self

        def start(self):
            return None

        def stop(self):
            return None

        def update_poll_interval_ms(self, poll_interval_ms):
            self.update_calls.append(poll_interval_ms)
            self.poll_interval_ms = poll_interval_ms

        def get_priority_symbol(self):
            self.priority_calls += 1
            if len(self._symbols_config) == 1:
                return self._symbols_config[0].symbol
            return self._symbols_config[1].symbol if self.priority_calls >= 2 else None

        def get_all_ltps(self):
            if len(self._symbols_config) == 1:
                return {self._symbols_config[0].symbol: 97.1}
            if self.priority_calls == 0:
                return {cfg.symbol: 90.0 for cfg in self._symbols_config}
            return {
                self._symbols_config[0].symbol: 95.0,
                self._symbols_config[1].symbol: 106.8,
            }

    monkeypatch.setattr(execution, "create_order_client_and_service", lambda user_config: FakePlatform(user_config.user_id))
    monkeypatch.setattr(execution, "create_fetch_clients", lambda configs, _is_atrad: [cfg.user_id for cfg in configs])
    monkeypatch.setattr(
        execution,
        "resolve_ticker",
        lambda ticker, *_args: ResolvedTicker(
            ticker=ticker.upper(),
            security_id=101,
            exchange_security_id=202,
            fetch_id=303,
            symbol=ticker.upper(),
        ),
    )
    monkeypatch.setattr(execution, "MultiSymbolSequentialPriceFetcher", FakeFetcher)
    monkeypatch.setattr(execution.time, "sleep", lambda _seconds: None)

    order_store = type(
        "Store",
        (),
        {
            "mark_success": lambda *_args: None,
            "mark_failed": lambda *_args: None,
        },
    )()

    result = execution.execute_trigger_sell_queue_group(
        user_config=user_a,
        orders=[
            {
                "id": "ts-1",
                "ticker": "aaa",
                "symbol": "AAA",
                "price": 100.0,
                "quantity": 10,
                "queue_id": 1,
                "mode": "trigger-sell",
                "trigger_sell_queue": True,
                "time": None,
                "limit": None,
            },
            {
                "id": "ts-2",
                "ticker": "bbb",
                "symbol": "BBB",
                "price": 110.0,
                "quantity": 11,
                "queue_id": 1,
                "mode": "trigger-sell",
                "trigger_sell_queue": True,
                "time": None,
                "limit": None,
            },
        ],
        order_store=order_store,
        fetch_user_configs=[DummyConfig("fetch-a"), DummyConfig("fetch-b")],
        is_atrad_fetch=False,
    )

    assert set(result["successful_orders"]) == {"ts-1", "ts-2"}
    assert captured["fetcher"].poll_interval_ms == 100
    assert captured["fetcher"].update_calls == [100]


def test_execute_from_order_store_resolves_pooled_users_per_order(monkeypatch):
    holder = {}

    class FakeOrderStore:
        def __init__(self, _path):
            self.orders = [
                {
                    "id": "pool-1",
                    "ticker": "aaa",
                    "user_id": "main-b",
                    "price": 100.0,
                    "quantity": 10,
                    "mode": "normal",
                    "queue_id": 1,
                    "time": None,
                    "sell": False,
                    "skip_first": False,
                    "skip_second_last": False,
                    "no_ladder": False,
                    "limit": None,
                    "base_quantity": 10,
                    "double_buy": False,
                    "double_buy_quantity": None,
                    "just_buy": False,
                    "just_buy_interval_ms": 100,
                    "just_buy_timeout": 5,
                    "just_buy_pre_wait_ms": 0,
                    "just_buy_max_requests": None,
                    "just_buy_fade_interval_ms": None,
                    "just_buy_fade_timeout": None,
                    "multi_queue": False,
                }
            ]
            self.marked_success = []
            holder["store"] = self

        def get_order_summary(self):
            return "summary"

        def get_executable_orders(self):
            return list(self.orders)

        def validate_order(self, order):
            return dict(order)

        def mark_success(self, order_id):
            self.marked_success.append(order_id)

        def mark_failed(self, order_id):
            raise AssertionError("should not fail")

    calls = {}

    def fake_resolve_ticker(ticker, fetch_user_configs=None, is_atrad_fetch=False):
        calls["resolve_ticker"] = {
            "ticker": ticker,
            "fetch_user_ids": [cfg.user_id for cfg in fetch_user_configs],
            "is_atrad_fetch": is_atrad_fetch,
        }
        return ResolvedTicker(
            ticker=ticker.upper(),
            security_id=101,
            exchange_security_id=202,
            fetch_id=303,
            symbol=ticker.upper(),
            fetch_host="example.test",
        )

    def fake_execute_order_for_user(user_config, order_params, scheduled_time=None, fetch_user_configs=None, is_atrad_fetch=False):
        calls["execute"] = {
            "user_id": user_config.user_id,
            "fetch_user_ids": [cfg.user_id for cfg in fetch_user_configs],
            "is_atrad_fetch": is_atrad_fetch,
            "order_params": order_params,
        }
        return {"status": "ok"}

    user_a = DummyConfig("main-a")
    user_b = DummyConfig("main-b")
    user_c = DummyConfig("main-c")
    pool = execution.UserPool(
        users_by_id={cfg.user_id: cfg for cfg in [user_a, user_b, user_c]},
        ordered_users=[user_a, user_b, user_c],
        is_atrad=False,
    )

    monkeypatch.setattr(execution, "OrderStore", FakeOrderStore)
    monkeypatch.setattr(execution, "resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(execution, "execute_order_for_user", fake_execute_order_for_user)

    result = main.execute_from_order_store(
        user_config=None,
        order_store_path="stores/order_store.json",
        user_pool=pool,
    )

    assert result == {"status": "ok"}
    assert holder["store"].marked_success == ["pool-1"]
    assert calls["resolve_ticker"]["fetch_user_ids"] == ["main-a", "main-c"]
    assert calls["execute"]["user_id"] == "main-b"
    assert calls["execute"]["fetch_user_ids"] == ["main-a", "main-c"]
    assert calls["execute"]["is_atrad_fetch"] is False


def test_execute_from_order_store_supports_mixed_pool_users_in_multi_queue(monkeypatch):
    class FakeOrderStore:
        def __init__(self, _path):
            self.orders = [
                {
                    "id": "mq-1",
                    "ticker": "aaa",
                    "user_id": "main-a",
                    "price": 100.0,
                    "quantity": 10,
                    "mode": "ipo-trigger",
                    "queue_id": 1,
                    "multi_queue": True,
                    "no_ladder": True,
                },
                {
                    "id": "mq-2",
                    "ticker": "bbb",
                    "user_id": "main-b",
                    "price": 110.0,
                    "quantity": 10,
                    "mode": "ipo-trigger",
                    "queue_id": 1,
                    "multi_queue": True,
                    "no_ladder": True,
                },
            ]

        def get_order_summary(self):
            return "summary"

        def get_executable_orders(self):
            return list(self.orders)

        def validate_order(self, order):
            normalized = {
                "time": None,
                "sell": False,
                "skip_first": False,
                "skip_second_last": False,
                "limit": None,
                "base_quantity": 10,
                "double_buy": False,
                "double_buy_quantity": None,
                "just_buy": False,
                "just_buy_interval_ms": 100,
                "just_buy_timeout": 5,
                "just_buy_pre_wait_ms": 0,
                "just_buy_max_requests": None,
                "just_buy_fade_interval_ms": None,
                "just_buy_fade_timeout": None,
            }
            normalized.update(order)
            return normalized

    user_a = DummyConfig("main-a")
    user_b = DummyConfig("main-b")
    pool = execution.UserPool(
        users_by_id={cfg.user_id: cfg for cfg in [user_a, user_b]},
        ordered_users=[user_a, user_b],
        is_atrad=False,
    )

    calls = {}

    def fake_execute_multi_queue_group(
        user_config,
        orders,
        order_store,
        fetch_user_configs=None,
        is_atrad_fetch=False,
        just_buy_user_configs=None,
        user_pool=None,
    ):
        calls["multi_queue"] = {
            "user_config": user_config,
            "orders": orders,
            "fetch_user_configs": fetch_user_configs,
            "is_atrad_fetch": is_atrad_fetch,
            "user_pool": user_pool,
        }
        return {"responses": [], "successful_orders": ["mq-1", "mq-2"], "failed_orders": []}

    monkeypatch.setattr(execution, "OrderStore", FakeOrderStore)
    monkeypatch.setattr(execution, "execute_multi_queue_group", fake_execute_multi_queue_group)

    result = main.execute_from_order_store(
        user_config=None,
        order_store_path="stores/order_store.json",
        user_pool=pool,
    )

    assert result["successful_orders"] == ["mq-1", "mq-2"]
    assert [order["id"] for order in calls["multi_queue"]["orders"]] == ["mq-1", "mq-2"]
    assert calls["multi_queue"]["user_pool"] is pool
    assert calls["multi_queue"]["fetch_user_configs"] == [user_b]
    assert calls["multi_queue"]["user_config"] is user_a


def test_execute_from_order_store_supports_mixed_pool_users_in_trigger_sell_queue(monkeypatch):
    class FakeOrderStore:
        def __init__(self, _path):
            self.orders = [
                {
                    "id": "ts-1",
                    "ticker": "aaa",
                    "user_id": "main-a",
                    "price": 100.0,
                    "quantity": 10,
                    "mode": "trigger-sell",
                    "queue_id": 1,
                    "trigger_sell_queue": True,
                },
                {
                    "id": "ts-2",
                    "ticker": "bbb",
                    "user_id": "main-b",
                    "price": 110.0,
                    "quantity": 10,
                    "mode": "trigger-sell",
                    "queue_id": 1,
                    "trigger_sell_queue": True,
                },
            ]

        def get_order_summary(self):
            return "summary"

        def get_executable_orders(self):
            return list(self.orders)

        def validate_order(self, order):
            normalized = {
                "time": None,
                "sell": False,
                "skip_first": False,
                "skip_second_last": False,
                "limit": None,
                "base_quantity": 10,
                "double_buy": False,
                "double_buy_quantity": None,
                "just_buy": False,
                "just_buy_interval_ms": 100,
                "just_buy_timeout": 5,
                "just_buy_pre_wait_ms": 0,
                "just_buy_max_requests": None,
                "just_buy_fade_interval_ms": None,
                "just_buy_fade_timeout": None,
                "multi_queue": False,
            }
            normalized.update(order)
            return normalized

    user_a = DummyConfig("main-a")
    user_b = DummyConfig("main-b")
    pool = execution.UserPool(
        users_by_id={cfg.user_id: cfg for cfg in [user_a, user_b]},
        ordered_users=[user_a, user_b],
        is_atrad=False,
    )

    calls = {}

    def fake_execute_trigger_sell_queue_group(
        user_config,
        orders,
        order_store,
        fetch_user_configs=None,
        is_atrad_fetch=False,
        user_pool=None,
    ):
        calls["trigger_sell_queue"] = {
            "user_config": user_config,
            "orders": orders,
            "fetch_user_configs": fetch_user_configs,
            "is_atrad_fetch": is_atrad_fetch,
            "user_pool": user_pool,
        }
        return {"responses": [], "successful_orders": ["ts-1", "ts-2"], "failed_orders": []}

    monkeypatch.setattr(execution, "OrderStore", FakeOrderStore)
    monkeypatch.setattr(execution, "execute_trigger_sell_queue_group", fake_execute_trigger_sell_queue_group)

    result = main.execute_from_order_store(
        user_config=None,
        order_store_path="stores/order_store.json",
        user_pool=pool,
    )

    assert result["successful_orders"] == ["ts-1", "ts-2"]
    assert [order["id"] for order in calls["trigger_sell_queue"]["orders"]] == ["ts-1", "ts-2"]
    assert calls["trigger_sell_queue"]["user_pool"] is pool
    assert calls["trigger_sell_queue"]["fetch_user_configs"] == [user_b]
    assert calls["trigger_sell_queue"]["user_config"] is user_a


def test_execute_from_order_store_marks_failed_when_trigger_mode_has_no_fetch_users(monkeypatch):
    holder = {}

    class FakeOrderStore:
        def __init__(self, _path):
            self.orders = [
                {
                    "id": "trigger-1",
                    "ticker": "aaa",
                    "price": 100.0,
                    "quantity": 10,
                    "mode": "ipo-trigger",
                    "queue_id": 1,
                    "time": None,
                    "sell": False,
                    "skip_first": False,
                    "skip_second_last": False,
                    "no_ladder": False,
                    "limit": None,
                    "base_quantity": 10,
                    "double_buy": False,
                    "double_buy_quantity": None,
                    "just_buy": False,
                    "just_buy_interval_ms": 100,
                    "just_buy_timeout": 5,
                    "just_buy_pre_wait_ms": 0,
                    "just_buy_max_requests": None,
                    "just_buy_fade_interval_ms": None,
                    "just_buy_fade_timeout": None
                }
            ]
            self.marked_failed = []
            holder["store"] = self

        def get_order_summary(self):
            return "summary"

        def get_executable_orders(self):
            return list(self.orders)

        def validate_order(self, order):
            return dict(order)

        def mark_success(self, order_id):
            raise AssertionError("should not succeed")

        def mark_failed(self, order_id):
            self.marked_failed.append(order_id)

    class FakeTickerStore:
        def lookup(self, ticker):
            return 101, 202

        def get_fetch_id(self, ticker, host=None):
            return 303

    monkeypatch.setattr(execution, "OrderStore", FakeOrderStore)
    monkeypatch.setattr(factories, "get_ticker_store", lambda: FakeTickerStore())

    with pytest.raises(ValueError, match="Fetch user configuration is required for 'ipo-trigger' mode"):
        main.execute_from_order_store(
            user_config=DummyConfig("main-user"),
            order_store_path="stores/order_store.json",
            fetch_user_configs=None,
            is_atrad_fetch=False,
        )

    assert holder["store"].marked_failed == ["trigger-1"]


def test_execute_from_order_store_characterizes_mixed_multi_queue_and_trigger_orders(monkeypatch):
    holder = {}

    class FakeOrderStore:
        def __init__(self, _path):
            self.orders = [
                {
                    "id": "mq1-a",
                    "ticker": "aaa",
                    "price": 100.0,
                    "quantity": 10,
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
                    "time": None,
                },
                {
                    "id": "mq1-b",
                    "ticker": "bbb",
                    "price": 110.0,
                    "quantity": 11,
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
                    "time": None,
                },
                {
                    "id": "trigger-standalone",
                    "ticker": "ccc",
                    "price": 120.0,
                    "quantity": 12,
                    "mode": "ipo-trigger",
                    "queue_id": 2,
                    "multi_queue": False,
                    "no_ladder": True,
                    "just_buy": True,
                    "just_buy_interval_ms": 120,
                    "just_buy_timeout": 9,
                    "just_buy_pre_wait_ms": 100,
                    "just_buy_max_requests": None,
                    "just_buy_fade_interval_ms": None,
                    "just_buy_fade_timeout": None,
                    "time": None,
                },
                {
                    "id": "mq2-a",
                    "ticker": "ddd",
                    "price": 130.0,
                    "quantity": 13,
                    "mode": "ipo-trigger",
                    "queue_id": 3,
                    "multi_queue": True,
                    "no_ladder": True,
                    "just_buy": True,
                    "just_buy_interval_ms": 90,
                    "just_buy_timeout": 4,
                    "just_buy_pre_wait_ms": 0,
                    "just_buy_max_requests": None,
                    "just_buy_fade_interval_ms": None,
                    "just_buy_fade_timeout": None,
                    "time": None,
                },
                {
                    "id": "mq2-b",
                    "ticker": "eee",
                    "price": 140.0,
                    "quantity": 14,
                    "mode": "ipo-trigger",
                    "queue_id": 3,
                    "multi_queue": True,
                    "no_ladder": True,
                    "just_buy": True,
                    "just_buy_interval_ms": 90,
                    "just_buy_timeout": 4,
                    "just_buy_pre_wait_ms": 0,
                    "just_buy_max_requests": None,
                    "just_buy_fade_interval_ms": None,
                    "just_buy_fade_timeout": None,
                    "time": None,
                },
                {
                    "id": "trigger-low",
                    "ticker": "fff",
                    "price": 150.0,
                    "quantity": 15,
                    "mode": "ipo-trigger-low",
                    "queue_id": 4,
                    "multi_queue": False,
                    "no_ladder": False,
                    "just_buy": False,
                    "just_buy_interval_ms": 100,
                    "just_buy_timeout": 5,
                    "just_buy_pre_wait_ms": 0,
                    "just_buy_max_requests": None,
                    "just_buy_fade_interval_ms": None,
                    "just_buy_fade_timeout": None,
                    "time": None,
                },
            ]
            self.marked_success = []
            self.marked_failed = []
            holder["store"] = self

        def get_order_summary(self):
            return "summary"

        def get_executable_orders(self):
            return list(self.orders)

        def validate_order(self, order):
            normalized = {
                "sell": False,
                "skip_first": False,
                "skip_second_last": False,
                "limit": None,
                "base_quantity": 10,
                "double_buy": False,
                "double_buy_quantity": None,
                "refresh_before": 20,
                "seller_config": None,
                "buyer_config": None,
                "sell_quantity": None,
                "sell_pre_wait_ms": 5000,
            }
            normalized.update(order)
            return normalized

        def mark_success(self, order_id):
            self.marked_success.append(order_id)

        def mark_failed(self, order_id):
            self.marked_failed.append(order_id)

    calls = {"multi_queue": [], "single": []}

    def fake_execute_multi_queue_group(
        user_config,
        orders,
        order_store,
        fetch_user_configs=None,
        is_atrad_fetch=False,
        just_buy_user_configs=None,
        user_pool=None,
    ):
        for order in orders:
            order_store.mark_success(order["id"])
        calls["multi_queue"].append(
            {
                "user_config": user_config,
                "order_ids": [order["id"] for order in orders],
                "orders": orders,
                "order_store": order_store,
                "fetch_user_configs": fetch_user_configs,
                "is_atrad_fetch": is_atrad_fetch,
                "just_buy_user_configs": just_buy_user_configs,
                "user_pool": user_pool,
            }
        )
        return {
            "responses": [],
            "successful_orders": [order["id"] for order in orders],
            "failed_orders": [],
        }

    def fake_resolve_ticker(ticker, fetch_user_configs=None, is_atrad_fetch=False):
        return ResolvedTicker(
            ticker=ticker.upper(),
            security_id=100 + len(ticker),
            exchange_security_id=200 + len(ticker),
            fetch_id=300 + len(ticker),
            symbol=ticker.upper(),
        )

    def fake_execute_order_for_user(user_config, order_params, scheduled_time=None, fetch_user_configs=None, is_atrad_fetch=False):
        calls["single"].append(
            {
                "user_config": user_config,
                "order_params": order_params,
                "scheduled_time": scheduled_time,
                "fetch_user_configs": fetch_user_configs,
                "is_atrad_fetch": is_atrad_fetch,
            }
        )
        return {"status": "ok", "symbol": order_params["symbol"]}

    monkeypatch.setattr(execution, "OrderStore", FakeOrderStore)
    monkeypatch.setattr(execution, "execute_multi_queue_group", fake_execute_multi_queue_group)
    monkeypatch.setattr(execution, "resolve_ticker", fake_resolve_ticker)
    monkeypatch.setattr(execution, "execute_order_for_user", fake_execute_order_for_user)

    result = main.execute_from_order_store(
        user_config=DummyConfig("main-user"),
        order_store_path="stores/order_store.json",
        fetch_user_configs=[DummyConfig("fetch-user")],
        is_atrad_fetch=False,
    )

    assert result == {"status": "ok", "symbol": "FFF"}
    assert [call["order_ids"] for call in calls["multi_queue"]] == [
        ["mq1-a", "mq1-b"],
        ["mq2-a", "mq2-b"],
    ]

    first_multi_queue_orders = calls["multi_queue"][0]["orders"]
    assert all(order["mode"] == "ipo-trigger" for order in first_multi_queue_orders)
    assert all(order["multi_queue"] is True for order in first_multi_queue_orders)
    assert all(order["no_ladder"] is True for order in first_multi_queue_orders)
    assert all(order["just_buy"] is True for order in first_multi_queue_orders)
    assert all(order["just_buy_fade_interval_ms"] == 250 for order in first_multi_queue_orders)
    assert all(order["just_buy_fade_timeout"] == 2 for order in first_multi_queue_orders)

    assert len(calls["single"]) == 2
    standalone_trigger = calls["single"][0]["order_params"]
    assert standalone_trigger["ticker"] == "ccc"
    assert standalone_trigger["ipo_trigger_mode"] is True
    assert standalone_trigger["ipo_trigger_low_mode"] is False
    assert standalone_trigger["no_ladder"] is True
    assert standalone_trigger["just_buy"] is True
    assert standalone_trigger["just_buy_interval_ms"] == 120
    assert standalone_trigger["just_buy_timeout"] == 9
    assert standalone_trigger["just_buy_pre_wait_ms"] == 100
    assert standalone_trigger["just_buy_fade_interval_ms"] is None
    assert standalone_trigger["just_buy_fade_timeout"] is None

    trigger_low = calls["single"][1]["order_params"]
    assert trigger_low["ticker"] == "fff"
    assert trigger_low["ipo_trigger_mode"] is False
    assert trigger_low["ipo_trigger_low_mode"] is True
    assert trigger_low["just_buy"] is False

    assert holder["store"].marked_success == [
        "mq1-a",
        "mq1-b",
        "trigger-standalone",
        "mq2-a",
        "mq2-b",
        "trigger-low",
    ]
    assert holder["store"].marked_failed == []
