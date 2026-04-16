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

    def fake_schedule_order(time_str, order_func, main_client=None, fetch_clients=None, user_id="unknown", **order_params):
        calls["scheduled"] = {
            "time_str": time_str,
            "order_func": order_func,
            "main_client": main_client,
            "fetch_clients": fetch_clients,
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

    def fake_execute_multi_queue_group(user_config, orders, order_store, fetch_user_configs=None, is_atrad_fetch=False):
        calls["multi_queue"] = {
            "user_config": user_config,
            "orders": orders,
            "order_store": order_store,
            "fetch_user_configs": fetch_user_configs,
            "is_atrad_fetch": is_atrad_fetch,
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

        def _execute_multi_queue_ipo_trigger(self, orders, fetch_clients, on_order_complete=None):
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


def test_execute_from_order_store_rejects_mixed_pool_users_in_multi_queue(monkeypatch):
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

    monkeypatch.setattr(execution, "OrderStore", FakeOrderStore)

    with pytest.raises(ValueError, match="must all use the same user_id"):
        main.execute_from_order_store(
            user_config=None,
            order_store_path="stores/order_store.json",
            user_pool=pool,
        )


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

    def fake_execute_multi_queue_group(user_config, orders, order_store, fetch_user_configs=None, is_atrad_fetch=False):
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
