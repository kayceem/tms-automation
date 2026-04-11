from datetime import datetime as real_datetime, timedelta

import pytest

from services.scheduling.scheduler import OrderScheduler


class FrozenDateTime(real_datetime):
    current = real_datetime(2026, 4, 10, 10, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls.current


class RefreshClient:
    def __init__(self, user_id, result=True, error=None):
        self.user_id = user_id
        self.result = result
        self.error = error
        self.calls = 0

    def refresh_tokens(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def test_parse_time_returns_today_when_future(monkeypatch):
    monkeypatch.setattr("services.scheduling.scheduler.datetime", FrozenDateTime)

    scheduled = OrderScheduler.parse_time("10:30")

    assert scheduled == real_datetime(2026, 4, 10, 10, 30, 0)


def test_parse_time_rolls_to_tomorrow_when_past(monkeypatch):
    monkeypatch.setattr("services.scheduling.scheduler.datetime", FrozenDateTime)

    scheduled = OrderScheduler.parse_time("09:30")

    assert scheduled == real_datetime(2026, 4, 11, 9, 30, 0)


def test_parse_time_rejects_invalid_format():
    with pytest.raises(ValueError, match="Invalid time format"):
        OrderScheduler.parse_time("invalid")


def test_wait_until_refreshes_main_and_fetch_clients(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("services.scheduling.scheduler.time.sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr("services.scheduling.scheduler.datetime", FrozenDateTime)

    main_client = RefreshClient("main-user", result=True)
    fetch_ok = RefreshClient("fetch-1", result=True)
    fetch_fail = RefreshClient("fetch-2", result=False)
    fetch_error = RefreshClient("fetch-3", error=RuntimeError("boom"))

    target_time = FrozenDateTime.current + timedelta(seconds=40)
    OrderScheduler.wait_until(
        target_time,
        main_client=main_client,
        fetch_clients=[fetch_ok, fetch_fail, fetch_error],
        user_id="main-user",
    )

    assert main_client.calls == 1
    assert fetch_ok.calls == 1
    assert fetch_fail.calls == 1
    assert fetch_error.calls == 1
    assert sleep_calls[0] == 25.0
    assert sleep_calls[1] == 30.0
    assert sleep_calls[2:] == [1] * 10


def test_schedule_order_passes_fetch_clients_to_order_func(monkeypatch):
    calls = {}

    def fake_wait_until(target_time, main_client=None, fetch_clients=None, user_id="unknown"):
        calls["wait"] = {
            "target_time": target_time,
            "main_client": main_client,
            "fetch_clients": fetch_clients,
            "user_id": user_id,
        }

    def fake_order_func(**kwargs):
        calls["order"] = kwargs
        return {"status": "ok"}

    monkeypatch.setattr(OrderScheduler, "parse_time", classmethod(lambda cls, _: real_datetime(2026, 4, 10, 12, 0, 0)))
    monkeypatch.setattr(OrderScheduler, "wait_until", staticmethod(fake_wait_until))

    fetch_clients = [object(), object()]
    result = OrderScheduler.schedule_order(
        "12:00",
        fake_order_func,
        main_client="main-client",
        fetch_clients=fetch_clients,
        user_id="user-1",
        symbol="NABIL",
    )

    assert result == {"status": "ok"}
    assert calls["wait"]["main_client"] == "main-client"
    assert calls["wait"]["fetch_clients"] == fetch_clients
    assert calls["order"] == {"symbol": "NABIL", "fetch_clients": fetch_clients}


def test_schedule_order_sell_buy_refreshes_all_clients(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("services.scheduling.scheduler.time.sleep", lambda seconds: sleep_calls.append(seconds))
    monkeypatch.setattr("services.scheduling.scheduler.datetime", FrozenDateTime)
    monkeypatch.setattr(OrderScheduler, "parse_time", classmethod(lambda cls, _: FrozenDateTime.current + timedelta(seconds=40)))

    seller = RefreshClient("seller")
    buyer = RefreshClient("buyer")
    fetch = RefreshClient("fetch")
    calls = {}

    def fake_order_func(**kwargs):
        calls["order"] = kwargs
        return {"status": "ok"}

    result = OrderScheduler.schedule_order_sell_buy(
        "10:00",
        fake_order_func,
        seller_client=seller,
        buyer_client=buyer,
        fetch_clients=[fetch],
        user_id="coordinator",
        symbol="NABIL",
    )

    assert result == {"status": "ok"}
    assert seller.calls == 1
    assert buyer.calls == 1
    assert fetch.calls == 1
    assert calls["order"] == {"symbol": "NABIL", "fetch_clients": [fetch]}
    assert sleep_calls[0] == 25.0
