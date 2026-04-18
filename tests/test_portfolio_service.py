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
