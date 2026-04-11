import json

from api.tms_client import TMSClient


def test_place_order_posts_expected_payload(tms_user_config, http_interceptor):
    client = TMSClient(tms_user_config)
    endpoint = "https://example.test/tmsapi/orderApi/order/"

    http_interceptor.add_json(
        "POST",
        endpoint,
        payload={"status": "ok", "orderId": "OID-1"},
    )

    result = client.place_order(
        security_id=101,
        exchange_security_id=202,
        order_price=500.5,
        order_quantity=10,
        buy_or_sell=1,
    )

    assert result == {"status": "ok", "orderId": "OID-1"}
    assert len(http_interceptor.calls) == 1
    call = http_interceptor.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == endpoint
    payload = call["kwargs"]["json"]
    assert payload["orderBook"]["security"]["id"] == 101
    assert payload["orderBook"]["security"]["exchangeSecurityId"] == 202
    assert payload["orderBook"]["orderBookExtensions"][0]["orderPrice"] == 500.5
    assert payload["orderBook"]["orderBookExtensions"][0]["orderQuantity"] == 10
    assert payload["orderBook"]["buyOrSell"] == 1
    assert payload["orderBook"]["client"] == {"id": 42, "name": "Trader"}


def test_place_order_refreshes_and_retries_after_401(tms_user_config, http_interceptor):
    client = TMSClient(tms_user_config)
    order_endpoint = "https://example.test/tmsapi/orderApi/order/"
    refresh_endpoint = "https://example.test/tmsapi/authApi/authenticate/refresh"

    http_interceptor.add_json("POST", order_endpoint, status=401, payload={"detail": "expired"}, reason="Unauthorized")
    http_interceptor.add_json(
        "POST",
        refresh_endpoint,
        payload={"detail": "refreshed"},
        cookies=[
            {"name": "_rid", "value": "new-rid", "domain": ".example.test"},
            {"name": "_aid", "value": "new-aid", "domain": ".example.test"},
        ],
    )
    http_interceptor.add_json("POST", order_endpoint, payload={"status": "ok", "orderId": "OID-2"})

    result = client.place_order(
        security_id=101,
        exchange_security_id=202,
        order_price=500,
        order_quantity=5,
    )

    saved = json.loads(open(tms_user_config._config_file_path, "r", encoding="utf-8").read())
    assert result["orderId"] == "OID-2"
    assert [call["url"] for call in http_interceptor.calls] == [
        order_endpoint,
        refresh_endpoint,
        order_endpoint,
    ]
    assert saved["rid_cookie"] == "new-rid"
    assert saved["access_token"] == "new-aid"


def test_get_ltp_returns_none_on_timeout(tms_user_config, http_interceptor):
    client = TMSClient(tms_user_config)
    endpoint = "https://example.test/tmsapi/rtApi/ws/stockQuote/777"

    import requests

    http_interceptor.add_exception("GET", endpoint, requests.exceptions.Timeout("boom"))

    assert client.get_ltp(777, timeout=0.01) is None


def test_get_ltp_parses_payload_after_refresh_retry(tms_user_config, http_interceptor):
    client = TMSClient(tms_user_config)
    quote_endpoint = "https://example.test/tmsapi/rtApi/ws/stockQuote/321"
    refresh_endpoint = "https://example.test/tmsapi/authApi/authenticate/refresh"

    http_interceptor.add_json("GET", quote_endpoint, status=401, payload={"detail": "expired"}, reason="Unauthorized")
    http_interceptor.add_json("POST", refresh_endpoint, payload={"detail": "refreshed"})
    http_interceptor.add_json(
        "GET",
        quote_endpoint,
        payload={"payload": {"data": [{"ltp": "123.4"}]}},
    )

    assert client.get_ltp(321) == 123.4
