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
                    "just_buy_fade_timeout": None,
                    "refresh_before": 20,
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
                "just_buy_fade_timeout": None,
                "refresh_before": 20,
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
                    "just_buy_fade_timeout": None,
                    "refresh_before": 20,
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
