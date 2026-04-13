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


def test_get_order_book_retries_after_html_session_expiry_and_returns_payload(atrad_user_config, http_interceptor):
    client = ATRADClient(atrad_user_config)
    client._is_authenticated = True

    order_book_matcher = (
        lambda url: url.startswith(
            "https://atrad.test/atsweb/order?action=getUCCActiveBlotterData&format=json"
        )
        and "&dojo.preventCache=" in url
    )
    login_endpoint = "https://atrad.test/atsweb/login"

    http_interceptor.add_text("GET", order_book_matcher, text="<html>expired</html>")
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
        cookies=[{"name": "JSESSIONID", "value": "session-9", "domain": "atrad.test"}],
    )
    http_interceptor.add_text(
        "GET",
        order_book_matcher,
        text=(
            '{"code":"0","description":"success","data":{"blotterdata":[{"clientorderid":"76071192",'
            '"securitycode":"SKHEL","orderplacedate":"2026-04-10 11:18:29"}],'
            '"lastUpdatedTime":"2026-04-10 12:53:16"}}'
        ),
    )

    result = client.get_order_book()

    assert result["lastUpdatedTime"] == "2026-04-10 12:53:16"
    assert result["blotterdata"][0]["clientorderid"] == "76071192"


def test_get_completed_order_book_uses_completed_endpoint(atrad_user_config, http_interceptor):
    client = ATRADClient(atrad_user_config)
    client._is_authenticated = True

    completed_matcher = (
        lambda url: url.startswith(
            "https://atrad.test/atsweb/order?action=getUCCInactiveBlotterData&format=json"
        )
        and "&dojo.preventCache=" in url
    )

    http_interceptor.add_text(
        "GET",
        completed_matcher,
        text=(
            '{"code":"0","description":"success","data":{"blotterdata":[{"clientorderid":"9001",'
            '"securitycode":"NABIL","orderplacedate":"2026-04-10 11:18:29"}],'
            '"lastUpdatedTime":"2026-04-10 12:53:16"}}'
        ),
    )

    result = client.get_order_book(completed=True)

    assert result["blotterdata"][0]["clientorderid"] == "9001"


def test_get_custom_watchlists_returns_watch_list_names(atrad_user_config, http_interceptor):
    client = ATRADClient(atrad_user_config)
    client._is_authenticated = True

    matcher = (
        lambda url: url.startswith(
            "https://atrad.test/atsweb/watch?action=getCustomWatches&format=json&exchange=NEPSE"
        )
        and "&dojo.preventCache=" in url
    )

    http_interceptor.add_text(
        "GET",
        matcher,
        text=(
            '{"code":"0","description":"success","customwatches":{"watchListName":['
            '{"watchListID":"101305","watchListName":"IPO","exchangeID":"NEPSE"},'
            '{"watchListID":"207815","watchListName":"Buy List","exchangeID":"NEPSE"}],'
            '"size":[{"size":"2"}]}}'
        ),
    )

    result = client.get_custom_watchlists()

    assert result[0]["watchListName"] == "IPO"
    assert result[1]["watchListID"] == "207815"


def test_get_watchlist_returns_watch_rows(atrad_user_config, http_interceptor):
    client = ATRADClient(atrad_user_config)
    client._is_authenticated = True

    matcher = (
        lambda url: url.startswith(
            "https://atrad.test/atsweb/watch?action=userWatch&format=json&exchange=NEPSE&bookDefId=1&watchId=101305&lastUpdatedId=0"
        )
        and "&dojo.preventCache=" in url
    )

    http_interceptor.add_text(
        "GET",
        matcher,
        text=(
            '{"code":"0","description":"success","data":{"watch":['
            '{"securitycode":"NABIL","tradeprice":"501.2","bidprice":"500.9","askprice":"501.4","change":"1.2","tradeqty":"10000"},'
            '{"securitycode":"SKBBL","tradeprice":"799.0","bidprice":"798.5","askprice":"799.5","change":"-2.5","tradeqty":"8000"}'
            ']}}'
        ),
    )

    result = client.get_watchlist(101305)

    assert result[0]["securitycode"] == "NABIL"
    assert result[1]["tradeqty"] == "8000"


def test_build_cancel_order_url_encodes_cancel_payload(atrad_user_config):
    client = ATRADClient(atrad_user_config)
    order = {
        "exchangeid": "NEPSE",
        "clientaccountcode": "201811020977513",
        "securitycode": "SKHEL",
        "board": "REGULAR",
        "clientorderid": "76071192",
        "orderid": "00000",
        "exchangeorderid": "2026041001015927",
        "orderplacedate": "2026-04-10 11:18:29",
        "action": "BUY",
        "orderstatus": "NEW",
        "typeoforder": "REGULAR",
        "contrabroker": "0",
        "cpmemberid": "0",
    }

    url = client.build_cancel_order_url(order, request_id=1775805058924)

    assert url.startswith("https://atrad.test/atsweb/order?action=cancelOrder&format=json&order=")
    assert '"clientorderid":"76071192"' in url
    assert '"securitycode":"SKHEL"' in url
    assert url.endswith("&dojo.preventCache=1775805058924")


def test_cancel_order_logs_in_and_uses_built_url(atrad_user_config, http_interceptor):
    client = ATRADClient(atrad_user_config)

    login_endpoint = "https://atrad.test/atsweb/login"
    cancel_matcher = (
        lambda url: url.startswith("https://atrad.test/atsweb/order?action=cancelOrder&format=json&order=")
        and "&dojo.preventCache=" in url
    )

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
        cookies=[{"name": "JSESSIONID", "value": "session-10", "domain": "atrad.test"}],
    )
    http_interceptor.add_text(
        "GET",
        cancel_matcher,
        text='{"code":"0", "description":"javascriptOrderSuccessesFullySubmitted", "data":"success"}',
    )

    result = client.cancel_order(
        {
            "exchangeid": "NEPSE",
            "clientaccountcode": "201811020977513",
            "securitycode": "SKHEL",
            "board": "REGULAR",
            "clientorderid": "76071192",
            "orderid": "00000",
            "exchangeorderid": "2026041001015927",
            "orderplacedate": "2026-04-10 11:18:29",
            "action": "BUY",
            "orderstatus": "NEW",
            "typeoforder": "REGULAR",
            "contrabroker": "0",
            "cpmemberid": "0",
        }
    )

    assert result["code"] == "0"
    assert http_interceptor.calls[-1]["method"] == "GET"


def test_cancel_order_raises_runtime_error_on_failed_atrad_response(atrad_user_config, http_interceptor):
    client = ATRADClient(atrad_user_config)
    client._is_authenticated = True

    cancel_matcher = (
        lambda url: url.startswith("https://atrad.test/atsweb/order?action=cancelOrder&format=json&order=")
        and "&dojo.preventCache=" in url
    )
    http_interceptor.add_text(
        "GET",
        cancel_matcher,
        text='{"code":"9", "description":"rejected", "data":"failed"}',
    )

    with pytest.raises(RuntimeError, match="Order cancellation failed: rejected"):
        client.cancel_order(
            {
                "exchangeid": "NEPSE",
                "clientaccountcode": "201811020977513",
                "securitycode": "SKHEL",
                "board": "REGULAR",
                "clientorderid": "76071192",
                "orderid": "00000",
                "exchangeorderid": "2026041001015927",
                "orderplacedate": "2026-04-10 11:18:29",
                "action": "BUY",
                "orderstatus": "NEW",
                "typeoforder": "REGULAR",
                "contrabroker": "0",
                "cpmemberid": "0",
            }
        )
