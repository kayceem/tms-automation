from services.orders.atrad_order_service import ATRADOrderService
from services.orders.order_service import OrderService


class DummyTMSClient:
    def __init__(self):
        self.user_id = "tms-user"
        self.user_config = type("Config", (), {"trigger_mode_refresh_interval_seconds": 60})()
        self.calls = []

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": "ok", "source": "tms"}


class DummyATRADClient:
    def __init__(self):
        self.user_id = "atrad-user"
        self.calls = []
        self.ensure_authenticated_calls = 0
        self.flush_calls = 0

    def ensure_authenticated(self):
        self.ensure_authenticated_calls += 1
        return True

    def place_order(self, **kwargs):
        self.calls.append(kwargs)
        return {"code": "0", "source": "atrad"}

    def flush_successful_orders(self):
        self.flush_calls += 1


def test_order_service_executes_normal_order_and_double_buy(monkeypatch):
    client = DummyTMSClient()
    service = OrderService(client)
    double_buy_calls = {}

    monkeypatch.setattr(service, "_execute_double_buy", lambda **kwargs: double_buy_calls.update(kwargs))

    result = service.execute_order(
        symbol="NABIL",
        security_id=101,
        exchange_security_id=202,
        order_price=500.5,
        order_quantity=10,
        double_buy=True,
        order_type="LMT",
        order_validity="DAY",
    )

    assert result == {"status": "ok", "source": "tms"}
    assert client.calls == [
        {
            "security_id": 101,
            "exchange_security_id": 202,
            "order_price": 500.5,
            "order_quantity": 10,
            "buy_or_sell": 1,
            "order_type": "LMT",
            "order_validity": "DAY",
        }
    ]
    assert double_buy_calls["security_id"] == 101
    assert double_buy_calls["exchange_security_id"] == 202


def test_order_service_dispatches_ipo_trigger_to_internal_workflow(monkeypatch):
    service = OrderService(DummyTMSClient())
    captured = {}

    monkeypatch.setattr(service, "_execute_ipo_trigger", lambda **kwargs: captured.update(kwargs) or {"status": "trigger"})
    fetch_client = object()

    result = service.execute_order(
        symbol="NABIL",
        security_id=101,
        exchange_security_id=202,
        order_price=500,
        order_quantity=10,
        ipo_trigger_mode=True,
        fetch_client=fetch_client,
        skip_first=True,
        no_ladder=True,
        ticker="NABIL",
    )

    assert result == {"status": "trigger"}
    assert captured["fetch_clients"] == [fetch_client]
    assert captured["fetch_security_id"] == 101
    assert captured["skip_first"] is True
    assert captured["no_ladder"] is True
    assert captured["ticker"] == "NABIL"


def test_order_service_trigger_sell_uses_first_fetch_client(monkeypatch):
    service = OrderService(DummyTMSClient())
    captured = {}

    monkeypatch.setattr(service, "_execute_trigger_sell", lambda **kwargs: captured.update(kwargs) or {"status": "sell"})

    result = service.execute_order(
        symbol="NABIL",
        security_id=101,
        exchange_security_id=202,
        order_price=500,
        order_quantity=10,
        trigger_sell_mode=True,
        fetch_clients=["first", "second"],
    )

    assert result == {"status": "sell"}
    assert captured["fetch_client"] == "first"
    assert captured["fetch_security_id"] == 101


def test_order_service_requires_fetch_client_for_trigger_modes():
    service = OrderService(DummyTMSClient())

    try:
        service.execute_order(
            symbol="NABIL",
            security_id=101,
            exchange_security_id=202,
            order_price=500,
            order_quantity=10,
            ipo_trigger_mode=True,
        )
    except ValueError as exc:
        assert "fetch_client or fetch_clients is required" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing fetch client")


def test_atrad_order_service_executes_normal_order_and_double_buy(monkeypatch):
    client = DummyATRADClient()
    service = ATRADOrderService(client)
    double_buy_calls = {}

    monkeypatch.setattr(service, "_execute_double_buy", lambda **kwargs: double_buy_calls.update(kwargs))

    result = service.execute_order(
        symbol="NABIL",
        order_price=500.5,
        order_quantity=10,
        double_buy=True,
    )

    assert result == {"code": "0", "source": "atrad"}
    assert client.ensure_authenticated_calls == 1
    assert client.calls == [
        {
            "symbol": "NABIL",
            "quantity": 10,
            "price": 500.5,
            "side": "BUY",
        }
    ]
    assert double_buy_calls["symbol"] == "NABIL"
    assert double_buy_calls["side"] == "BUY"


def test_atrad_order_service_dispatches_trigger_sell(monkeypatch):
    service = ATRADOrderService(DummyATRADClient())
    captured = {}

    monkeypatch.setattr(service, "_execute_trigger_sell", lambda **kwargs: captured.update(kwargs) or {"status": "sell"})

    result = service.execute_order(
        symbol="NABIL",
        order_price=500,
        order_quantity=10,
        trigger_sell_mode=True,
        fetch_clients=["first", "second"],
        fetch_id=999,
    )

    assert result == {"status": "sell"}
    assert captured["fetch_client"] == "first"
    assert captured["fetch_security_id"] == 999
    assert captured["side"] == "BUY"
