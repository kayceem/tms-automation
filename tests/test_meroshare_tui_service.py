import json
from pathlib import Path

from tui.services.meroshare import MeroShareService


def _write_meroshare_user(path: Path) -> None:
    path.write_text(
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
                "_headers": {"authorization": "Bearer token"},
            }
        ),
        encoding="utf-8",
    )


def test_meroshare_service_lists_meroshare_users(tmp_path):
    user_path = tmp_path / "meroshare_user1.json"
    _write_meroshare_user(user_path)
    (tmp_path / "atrad_user1.json").write_text("{}", encoding="utf-8")

    service = MeroShareService(users_dir=tmp_path)

    assert service.list_users() == [user_path]
    assert service.get_user_label(user_path) == "03522757"


def test_meroshare_service_shapes_portfolio_rows(monkeypatch, tmp_path):
    user_path = tmp_path / "meroshare_user1.json"
    _write_meroshare_user(user_path)

    class FakeClient:
        def __init__(self, _config):
            pass

        def get_portfolio(self):
            return [
                {
                    "currentBalance": 150.0,
                    "lastTransactionPrice": "950.0",
                    "previousClosingPrice": "956.0",
                    "script": "ACLBSL",
                    "scriptDesc": "AARAMBHA CHAUTARI LAGHUBITTA BITTIYA SANSTHA LIMITED - ORDINARY SHARE",
                    "valueAsOfLastTransactionPrice": "142500.00",
                    "valueAsOfPreviousClosingPrice": "143400.00",
                }
            ]

    monkeypatch.setattr("tui.services.meroshare.MeroShareClient", FakeClient)

    rows, last_updated_time = MeroShareService(users_dir=tmp_path).fetch_portfolio(user_path)

    assert rows[0].script == "ACLBSL"
    assert rows[0].current_balance == "150.0"
    assert rows[0].last_transaction_price == "950.0"
    assert rows[0].value_as_of_last_transaction_price == "142500.00"
    assert last_updated_time


def test_meroshare_service_shapes_wacc_rows(monkeypatch, tmp_path):
    user_path = tmp_path / "meroshare_user1.json"
    _write_meroshare_user(user_path)

    class FakeClient:
        def __init__(self, _config):
            pass

        def get_wacc_report(self):
            return {
                "isWaccPending": False,
                "message": "SUCCESS.",
                "waccReportResponse": [
                    {
                        "averageBuyRate": 985.5803,
                        "demat": "1301370003522757",
                        "lastModifiedDate": "2026-04-07 20:23:11",
                        "scrip": "ACLBSL",
                        "totalCost": 147837.04,
                        "totalQuantity": 150,
                    }
                ],
            }

    monkeypatch.setattr("tui.services.meroshare.MeroShareClient", FakeClient)

    rows, payload, last_updated_time = MeroShareService(users_dir=tmp_path).fetch_wacc(user_path)

    assert payload["message"] == "SUCCESS."
    assert rows[0].script == "ACLBSL"
    assert rows[0].average_buy_rate == "985.5803"
    assert rows[0].total_cost == "147837.04"
    assert rows[0].last_modified_date == "2026-04-07 20:23:11"
    assert last_updated_time


def test_meroshare_service_shapes_current_issue_rows(monkeypatch, tmp_path):
    user_path = tmp_path / "meroshare_user1.json"
    _write_meroshare_user(user_path)

    class FakeClient:
        def __init__(self, _config):
            pass

        def get_applicable_issues(self):
            return [
                {
                    "scrip": "RSY2",
                    "companyName": "Reliable Samriddhi Yojana-2",
                    "shareTypeName": "IPO",
                    "shareGroupName": "Close Ended Mutual Fund",
                    "statusName": "EDIT_APPROVE",
                    "issueOpenDate": "May 12, 2026 9:00:00 AM",
                    "issueCloseDate": "May 22, 2026 5:00:00 PM",
                }
            ]

    monkeypatch.setattr("tui.services.meroshare.MeroShareClient", FakeClient)

    rows, last_updated_time = MeroShareService(users_dir=tmp_path).fetch_current_issues(user_path)

    assert rows[0].script == "RSY2"
    assert rows[0].company_name == "Reliable Samriddhi Yojana-2"
    assert rows[0].share_group == "Close Ended Mutual Fund"
    assert rows[0].close_date == "May 22, 2026 5:00:00 PM"
    assert last_updated_time


def test_meroshare_service_shapes_application_report_rows_and_edis(monkeypatch, tmp_path):
    user_path = tmp_path / "meroshare_user1.json"
    _write_meroshare_user(user_path)

    class FakeClient:
        def __init__(self, _config):
            pass

        def get_application_report(self):
            return [
                {
                    "scrip": "SNOW",
                    "companyName": "Snow Rivers Limited.",
                    "shareTypeName": "IPO",
                    "shareGroupName": "Ordinary Shares",
                    "statusName": "BLOCKED_APPROVE",
                    "appliedDate": "May 20, 2026",
                    "appliedKitta": 10,
                    "amount": 1000,
                }
            ]

        def check_edis_status(self, status=False):
            return True

    monkeypatch.setattr("tui.services.meroshare.MeroShareClient", FakeClient)

    service = MeroShareService(users_dir=tmp_path)
    rows, last_updated_time = service.fetch_application_report(user_path)

    assert rows[0].script == "SNOW"
    assert rows[0].status == "BLOCKED_APPROVE"
    assert rows[0].applied_units == "10"
    assert rows[0].amount == "1000"
    assert service.check_edis_status(user_path) is True
    assert last_updated_time


def test_meroshare_service_preserves_application_report_order(monkeypatch, tmp_path):
    user_path = tmp_path / "meroshare_user1.json"
    _write_meroshare_user(user_path)

    class FakeClient:
        def __init__(self, _config):
            pass

        def get_application_report(self):
            return [
                {"scrip": "ZZZ", "companyName": "Last"},
                {"scrip": "AAA", "companyName": "First"},
            ]

    monkeypatch.setattr("tui.services.meroshare.MeroShareClient", FakeClient)

    rows, _last_updated_time = MeroShareService(users_dir=tmp_path).fetch_application_report(user_path)

    assert [row.script for row in rows] == ["ZZZ", "AAA"]
