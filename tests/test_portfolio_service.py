from pathlib import Path

from tui.services.portfolio import PortfolioService


def test_fetch_account_summary_returns_client_summary(monkeypatch, tmp_path: Path):
    class FakeClient:
        def __init__(self, _config) -> None:
            pass

        def get_account_summary(self):
            return {
                    "clientSummary": {
                        "totalPortfolioCost": "2531584.412109375",
                        "buyingPower": "1512527.0",
                },
            }

    monkeypatch.setattr("tui.services.portfolio.ATRADClient", FakeClient)
    config_path = tmp_path / "atrad_user.json"
    config_path.write_text(
        """{
            "user_id": "atrad-user",
            "atrad_base_url": "https://atrad.test",
            "atrad_host": "atrad.test",
            "username": "demo-user",
            "password": "demo-pass",
            "account_id": "ACC-1"
        }""",
        encoding="utf-8",
    )

    service = PortfolioService()
    summary, last_updated_time = service.fetch_account_summary(config_path)

    assert summary["totalPortfolioCost"] == "2531584.412109375"
    assert summary["buyingPower"] == "1512527.0"
    assert last_updated_time


def test_fetch_sector_summary_formats_turnover_as_devanagari_lakhs(monkeypatch, tmp_path: Path):
    class FakeClient:
        def __init__(self, _config) -> None:
            pass

        def get_sector_data(self):
            return [
                {
                    "pr1": "2786.94",
                    "n1": "-17.23",
                    "p1": "-0.61",
                    "to": "3,554,257,960.46",
                }
            ]

    monkeypatch.setattr("tui.services.portfolio.ATRADClient", FakeClient)
    config_path = tmp_path / "atrad_user.json"
    config_path.write_text(
        """{
            "user_id": "atrad-user",
            "atrad_base_url": "https://atrad.test",
            "atrad_host": "atrad.test",
            "username": "demo-user",
            "password": "demo-pass",
            "account_id": "ACC-1"
        }""",
        encoding="utf-8",
    )

    service = PortfolioService()
    summary = service.fetch_sector_summary(config_path)

    assert summary is not None
    assert summary.turnover == "3,55,42,57,960.46"


def test_fetch_portfolio_returns_selected_holding_columns(monkeypatch, tmp_path: Path):
    class FakeClient:
        def __init__(self, _config) -> None:
            pass

        def get_portfolio(self):
            return [
                {
                    "security": "RLEL",
                    "quantity": "40",
                    "avgPrice": "1075.01625",
                    "totCost": "43000.6484375",
                    "lastTraded": "995.0",
                    "marketValue": "39800.0",
                    "netGain": "-3200.6484375",
                    "netchange": "8.5",
                    "clearedBalance": "40",
                    "availableQty": "40",
                    "unsetBuy": "0",
                    "unsetSell": "0",
                    "pendBuy": "0",
                    "pendSell": "0",
                },
                {
                    "security": "SKHEL",
                    "quantity": "320",
                    "avgPrice": "1468.272859",
                    "totCost": "469847.3125",
                    "lastTraded": "1262.0",
                    "marketValue": "403840.0",
                    "netGain": "-66007.3125",
                    "netchange": "3.0",
                    "clearedBalance": "320",
                    "availableQty": "320",
                    "unsetBuy": "0",
                    "unsetSell": "0",
                    "pendBuy": "0",
                    "pendSell": "0",
                },
            ]

    monkeypatch.setattr("tui.services.portfolio.ATRADClient", FakeClient)
    config_path = tmp_path / "atrad_user.json"
    config_path.write_text(
        """{
            "user_id": "atrad-user",
            "atrad_base_url": "https://atrad.test",
            "atrad_host": "atrad.test",
            "username": "demo-user",
            "password": "demo-pass",
            "account_id": "ACC-1"
        }""",
        encoding="utf-8",
    )

    service = PortfolioService()
    rows, last_updated_time = service.fetch_portfolio(config_path)

    assert [row.security_code for row in rows] == ["RLEL", "SKHEL"]
    assert rows[0].quantity == "40"
    assert rows[0].avg_price == "1075.01625"
    assert rows[0].total_cost == "43000.6484375"
    assert rows[0].last_traded == "995.0"
    assert rows[0].market_value == "39800.0"
    assert rows[0].net_gain == "-3200.6484375"
    assert rows[0].net_change == "8.5"
    assert rows[0].cleared_balance == "40"
    assert rows[0].available_quantity == "40"
    assert rows[0].unset_buy == "0"
    assert rows[0].unset_sell == "0"
    assert rows[0].pending_buy == "0"
    assert rows[0].pending_sell == "0"
    assert last_updated_time
