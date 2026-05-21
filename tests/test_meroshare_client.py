import json
from pathlib import Path

import requests

from api import MeroShareClient
from config import MeroShareUserConfig


def _meroshare_config(tmp_path: Path) -> MeroShareUserConfig:
    config_path = tmp_path / "meroshare_user.json"
    config_path.write_text(
        json.dumps(
            {
                "user_id": "meroshare-user",
                "meroshare_base_url": "https://webbackend.test",
                "meroshare_host_url": "meroshare.test",
                "demat": "1301370003522757",
                "dp": "13700",
                "client_id": "174",
                "username": "03522757",
                "password": "secret",
                "crn_number": "23463",
                "pin": "",
                "_headers": {"authorization": ""},
            }
        ),
        encoding="utf-8",
    )
    return MeroShareUserConfig.from_file(str(config_path))


def _response(status: int = 200, payload=None, headers=None, text: str | None = None) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.reason = "OK"
    response.encoding = "utf-8"
    response._content = (text if text is not None else json.dumps(payload if payload is not None else {})).encode("utf-8")
    response.headers.update(headers or {})
    return response


def test_meroshare_config_loads_user_file_shape(tmp_path):
    config = _meroshare_config(tmp_path)

    assert config.user_id == "meroshare-user"
    assert config.client_id_int == 174
    assert config.client_code == "13700"
    assert config.meroshare_login_endpoint == "/api/meroShare/auth/"
    assert config.meroshare_wacc_endpoint == "/api/myPurchase/waccReport/"
    assert config.meroshare_portfolio_endpoint == "/api/meroShareView/myPortfolio/"


def test_meroshare_login_posts_credentials_and_stores_authorization(monkeypatch, tmp_path):
    config = _meroshare_config(tmp_path)
    calls = []

    def fake_request(_session, method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs, "headers": dict(_session.headers)})
        return _response(payload={"message": "SUCCESS"}, headers={"authorization": "Bearer token-1"})

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)

    client = MeroShareClient(config)
    result = client.login()

    assert result == {"message": "SUCCESS"}
    assert client.is_authenticated() is True
    assert config.authorization == "Bearer token-1"
    assert client.session.headers["Authorization"] == "Bearer token-1"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"] == "https://webbackend.test/api/meroShare/auth/"
    assert calls[0]["kwargs"]["json"] == {"clientId": 174, "username": "03522757", "password": "secret"}
    assert calls[0]["kwargs"]["timeout"] == 5.0
    assert calls[0]["headers"]["Authorization"] == "null"
    assert calls[0]["headers"]["User-Agent"] == (
        "Mozilla/5.0 (X11; Linux x86_64; rv:150.0) Gecko/20100101 Firefox/150.0"
    )
    assert calls[0]["headers"]["Origin"] == "https://meroshare.test"
    assert calls[0]["headers"]["Sec-Fetch-Site"] == "same-site"


def test_meroshare_get_wacc_report_logs_in_and_posts_demat(monkeypatch, tmp_path):
    config = _meroshare_config(tmp_path)
    calls = []
    responses = [
        _response(payload={"message": "SUCCESS"}, headers={"authorization": "Bearer token-1"}),
        _response(
            payload={
                "isWaccPending": False,
                "message": "SUCCESS.",
                "viewWaccSummaryReport": False,
                "waccReportResponse": [
                    {
                        "averageBuyRate": 985.5803,
                        "demat": "1301370003522757",
                        "scrip": "ACLBSL",
                        "totalCost": 147837.04,
                        "totalQuantity": 150,
                    }
                ],
            }
        ),
    ]

    def fake_request(_session, method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        return responses.pop(0)

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)

    client = MeroShareClient(config)
    result = client.get_wacc_report()

    assert result["message"] == "SUCCESS."
    assert result["waccReportResponse"][0]["scrip"] == "ACLBSL"
    assert calls[1]["url"] == "https://webbackend.test/api/myPurchase/waccReport/"
    assert calls[1]["kwargs"]["json"] == {"demat": "1301370003522757"}


def test_meroshare_clears_login_cookies_before_authenticated_api_calls(monkeypatch, tmp_path):
    config = _meroshare_config(tmp_path)
    cookie_counts = []
    responses = [
        _response(payload={"message": "SUCCESS"}, headers={"authorization": "Bearer token-1"}),
        _response(payload={"meroShareMyPortfolio": []}),
    ]

    def fake_request(_session, method, url, **kwargs):
        if url.endswith("/api/meroShare/auth/"):
            _session.cookies.set("TS01c40bbd", "edge-cookie", domain="webbackend.test", path="/")
        if url.endswith("/api/meroShareView/myPortfolio/"):
            cookie_counts.append(len(_session.cookies))
        return responses.pop(0)

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)

    client = MeroShareClient(config)
    rows = client.get_portfolio()

    assert rows == []
    assert cookie_counts == [0]


def test_meroshare_get_portfolio_returns_portfolio_rows(monkeypatch, tmp_path):
    config = _meroshare_config(tmp_path)
    config.update_authorization("Bearer saved-token")
    calls = []
    responses = [
        _response(payload={"message": "valid"}),
        _response(
            payload={
                "meroShareMyPortfolio": [
                    {
                        "currentBalance": 150.0,
                        "lastTransactionPrice": "950.0",
                        "previousClosingPrice": "956.0",
                        "script": "ACLBSL",
                        "scriptDesc": "AARAMBHA CHAUTARI LAGHUBITTA BITTIYA SANSTHA LIMITED - ORDINARY SHARE",
                        "valueAsOfLastTransactionPrice": "142500.00",
                        "valueAsOfPreviousClosingPrice": "143400.00",
                        "valueOfLastTransPrice": 142500.0,
                        "valueOfPrevClosingPrice": 143400.0,
                    }
                ]
            }
        ),
    ]

    def fake_request(_session, method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        return responses.pop(0)

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)

    client = MeroShareClient(config)
    rows = client.get_portfolio()

    assert rows[0]["script"] == "ACLBSL"
    assert calls[0]["method"] == "GET"
    assert calls[0]["url"] == "https://webbackend.test/api/meroShareView/myDetail/1301370003522757"
    assert calls[1]["method"] == "POST"
    assert calls[1]["url"] == "https://webbackend.test/api/meroShareView/myPortfolio/"
    assert calls[1]["kwargs"]["json"] == {
        "sortBy": "script",
        "demat": ["1301370003522757"],
        "clientCode": "13700",
        "page": 1,
        "size": 200,
        "sortAsc": True,
    }
    assert calls[1]["kwargs"]["timeout"] == 5.0


def test_meroshare_issue_report_and_edis_methods(monkeypatch, tmp_path):
    config = _meroshare_config(tmp_path)
    calls = []
    responses = [
        _response(payload={"message": "SUCCESS"}, headers={"authorization": "Bearer token-1"}),
        _response(payload={"object": [{"scrip": "RSY2"}]}),
        _response(payload={"object": [{"scrip": "SNOW"}]}),
        _response(status=409, payload={"message": "No EDIS"}),
    ]

    def fake_request(_session, method, url, **kwargs):
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        return responses.pop(0)

    monkeypatch.setattr(requests.sessions.Session, "request", fake_request)

    client = MeroShareClient(config)

    assert client.get_applicable_issues() == [{"scrip": "RSY2"}]
    assert client.get_application_report() == [{"scrip": "SNOW"}]
    assert client.check_edis_status(status=True) is False
    assert calls[1]["url"] == "https://webbackend.test/api/meroShare/companyShare/applicableIssue/"
    assert calls[2]["url"] == "https://webbackend.test/api/meroShare/applicantForm/active/search/"
    assert calls[3]["method"] == "GET"
    assert calls[3]["url"] == "https://webbackend.test/api/EDIS/check/"
