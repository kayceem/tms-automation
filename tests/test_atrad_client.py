import pytest

from api.atrad_client import ATRADClient


def test_login_updates_session_and_persists_cookies(atrad_user_config, http_interceptor):
    client = ATRADClient(atrad_user_config)
    login_endpoint = "https://atrad.test/atsweb/login"

    http_interceptor.add_json(
        "POST",
        login_endpoint,
        payload={
            "code": "0",
            "role": "OnlineUser",
            "broker_code": "NSH",
            "max_basket_limit": "25",
            "watchID": "77",
            "is_dvp_enabled": "Y",
        },
        cookies=[
            {"name": "JSESSIONID", "value": "session-1", "domain": "atrad.test"},
        ],
    )

    result = client.login()

    assert result["code"] == "0"
    assert client.is_authenticated() is True
    assert atrad_user_config._session_id == "session-1"
    assert atrad_user_config._watch_id == 77
    assert atrad_user_config._cookies["JSESSIONID"] == "session-1"


def test_place_order_logs_in_and_posts_form_body(atrad_user_config, http_interceptor, monkeypatch):
    client = ATRADClient(atrad_user_config)
    monkeypatch.setattr(client, "_generate_duplicate_order_id", lambda: "DUPLICATE1")

    login_endpoint = "https://atrad.test/atsweb/login"
    order_endpoint = "https://atrad.test/atsweb/order"

    http_interceptor.add_json(
        "POST",
        login_endpoint,
        payload={
            "code": "0",
            "role": "OnlineUser",
            "broker_code": "NSH",
            "max_basket_limit": "25",
            "watchID": "77",
            "is_dvp_enabled": "Y",
        },
        cookies=[{"name": "JSESSIONID", "value": "session-1", "domain": "atrad.test"}],
    )
    http_interceptor.add_json("POST", order_endpoint, payload={"code": "0", "description": "accepted"})

    result = client.place_order(symbol="NABIL", quantity=10, price=500.5, side="BUY", market_price=501.0)

    assert result["code"] == "0"
    order_call = http_interceptor.calls[-1]
    assert order_call["url"] == order_endpoint
    body = order_call["kwargs"]["data"]
    assert "txtSecurity=NABIL" in body
    assert "spnQuantity=10" in body
    assert "spnPrice=500.5" in body
    assert "marketPrice=501.0" in body
    assert "duplicateOrderId=DUPLICATE1" in body
    assert "actionSelect=1" in body


def test_place_order_reauthenticates_after_html_session_expiry(atrad_user_config, http_interceptor, monkeypatch):
    client = ATRADClient(atrad_user_config)
    client._is_authenticated = True
    monkeypatch.setattr(client, "_generate_duplicate_order_id", lambda: "DUPLICATE1")

    order_endpoint = "https://atrad.test/atsweb/order"
    login_endpoint = "https://atrad.test/atsweb/login"

    http_interceptor.add_text("POST", order_endpoint, text="<html>expired</html>")
    http_interceptor.add_json(
        "POST",
        login_endpoint,
        payload={
            "code": "0",
            "role": "OnlineUser",
            "broker_code": "NSH",
            "max_basket_limit": "25",
            "watchID": "77",
            "is_dvp_enabled": "Y",
        },
        cookies=[{"name": "JSESSIONID", "value": "session-2", "domain": "atrad.test"}],
    )
    http_interceptor.add_json("POST", order_endpoint, payload={"code": "0", "description": "accepted"})

    result = client.place_order(symbol="NABIL", quantity=10, price=500.5, side="SELL")

    assert result["code"] == "0"
    assert [call["url"] for call in http_interceptor.calls] == [
        order_endpoint,
        login_endpoint,
        order_endpoint,
    ]


def test_get_ltp_retries_after_401_and_parses_tradeprice(atrad_user_config, http_interceptor):
    client = ATRADClient(atrad_user_config)
    client._is_authenticated = True
    quote_matcher = lambda url: url.startswith(
        "https://atrad.test/atsweb/watch?action=getWatchForSecurity&format=json&exchange=NEPSE&bookDefId=1&securityid=NABIL&dojo.preventCache="
    )
    login_endpoint = "https://atrad.test/atsweb/login"

    http_interceptor.add_json("GET", quote_matcher, status=401, payload={"detail": "expired"}, reason="Unauthorized")
    http_interceptor.add_json(
        "POST",
        login_endpoint,
        payload={
            "code": "0",
            "role": "OnlineUser",
            "broker_code": "NSH",
            "max_basket_limit": "25",
            "watchID": "77",
            "is_dvp_enabled": "Y",
        },
        cookies=[{"name": "JSESSIONID", "value": "session-3", "domain": "atrad.test"}],
    )
    http_interceptor.add_text(
        "GET",
        quote_matcher,
        text="{'data': {'tradeprice': '1,234.5', 'bidqty': '100', 'bidprice': '1230.0'}}",
    )

    assert client.get_ltp("NABIL") == 1234.5


def test_place_order_raises_runtime_error_on_failed_atrad_response(atrad_user_config, http_interceptor, monkeypatch):
    client = ATRADClient(atrad_user_config)
    monkeypatch.setattr(client, "_generate_duplicate_order_id", lambda: "DUPLICATE1")

    login_endpoint = "https://atrad.test/atsweb/login"
    order_endpoint = "https://atrad.test/atsweb/order"

    http_interceptor.add_json(
        "POST",
        login_endpoint,
        payload={
            "code": "0",
            "role": "OnlineUser",
            "broker_code": "NSH",
            "max_basket_limit": "25",
            "watchID": "77",
            "is_dvp_enabled": "Y",
        },
        cookies=[{"name": "JSESSIONID", "value": "session-1", "domain": "atrad.test"}],
    )
    http_interceptor.add_json("POST", order_endpoint, payload={"code": "9", "description": "rejected"})

    with pytest.raises(RuntimeError, match="Order placement failed: rejected"):
        client.place_order(symbol="NABIL", quantity=10, price=500.5, side="BUY")


def test_place_order_raises_runtime_error_on_invalid_json_response(atrad_user_config, http_interceptor, monkeypatch):
    client = ATRADClient(atrad_user_config)
    monkeypatch.setattr(client, "_generate_duplicate_order_id", lambda: "DUPLICATE1")

    login_endpoint = "https://atrad.test/atsweb/login"
    order_endpoint = "https://atrad.test/atsweb/order"

    http_interceptor.add_json(
        "POST",
        login_endpoint,
        payload={
            "code": "0",
            "role": "OnlineUser",
            "broker_code": "NSH",
            "max_basket_limit": "25",
            "watchID": "77",
            "is_dvp_enabled": "Y",
        },
        cookies=[{"name": "JSESSIONID", "value": "session-1", "domain": "atrad.test"}],
    )
    http_interceptor.add_text("POST", order_endpoint, text="not-json")

    with pytest.raises(RuntimeError, match="Invalid response from ATRAD server: not-json"):
        client.place_order(symbol="NABIL", quantity=10, price=500.5, side="BUY")
