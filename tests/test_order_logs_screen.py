import json

from tui.screens.order_logs import OrderLogsScreen
from tui.services.order_logs import OrderLogsPayload, OrderLogsService


def test_order_logs_service_merges_rows_by_symbol_and_fetch_time(tmp_path):
    logs_dir = tmp_path / "orders"
    date_dir = logs_dir / "2026-04-15"
    date_dir.mkdir(parents=True)
    (date_dir / "market.json").write_text(
        json.dumps(
            [
                {
                    "price": "100",
                    "qty": "1",
                    "splits": "1",
                    "fetched_time_ms": 1776255470299,
                    "symbol": "NABIL",
                },
                {
                    "price": "105",
                    "qty": "9",
                    "splits": "2",
                    "fetched_time_ms": 1776255470305,
                    "symbol": "NABIL",
                },
                {
                    "price": "999",
                    "qty": "3",
                    "splits": "1",
                    "fetched_time_ms": 1776255470200,
                    "symbol": "IGNORED",
                },
            ]
        )
    )
    (date_dir / "completed.json").write_text(
        json.dumps(
            [
                {
                    "price": "100",
                    "qty": "10",
                    "start_time_ms": 1776255470299,
                    "end_time_ms": 1776255470359,
                    "symbol": "NABIL",
                    "user_id": "test",
                },
                {
                    "price": "120",
                    "qty": "20",
                    "start_time_ms": 1776255470310,
                    "end_time_ms": 1776255470399,
                    "symbol": "NABIL",
                    "user_id": "test",
                },
                {
                    "price": "200",
                    "qty": "5",
                    "start_time_ms": 1776255470250,
                    "end_time_ms": 1776255470280,
                    "symbol": "ADBL",
                    "user_id": "test",
                },
            ]
        )
    )

    service = OrderLogsService(logs_dir=logs_dir)
    payload = service.load("2026-04-15")

    assert payload.symbols == ["ADBL", "NABIL"]
    assert "IGNORED" not in payload.rows_by_symbol

    nabil_rows = payload.rows_by_symbol["NABIL"]
    assert [row.fetch_time_ms for row in nabil_rows] == [
        1776255470299,
        1776255470305,
        1776255470310,
    ]

    merged_row = nabil_rows[0]
    assert merged_row.bid_quantity == "1"
    assert merged_row.bid_price == "100"
    assert merged_row.splits == "1"
    assert merged_row.order_quantity == "10"
    assert merged_row.order_price == "100"
    assert merged_row.fetch_time == service._fmt_ms(1776255470299)
    assert merged_row.end_time == service._fmt_ms(1776255470359)
    assert merged_row.highlight is True

    market_only_row = nabil_rows[1]
    assert market_only_row.order_quantity == "-"
    assert market_only_row.order_price == "-"
    assert market_only_row.end_time == "-"
    assert market_only_row.highlight is False

    completed_only_row = nabil_rows[2]
    assert completed_only_row.bid_quantity == "-"
    assert completed_only_row.bid_price == "-"
    assert completed_only_row.splits == "-"
    assert completed_only_row.order_quantity == "20"
    assert completed_only_row.order_price == "120"


def test_order_logs_service_highlights_market_row_against_all_completed_entries(tmp_path):
    logs_dir = tmp_path / "orders"
    date_dir = logs_dir / "2026-04-15"
    date_dir.mkdir(parents=True)
    (date_dir / "market.json").write_text(
        json.dumps(
            [
                {
                    "price": "100",
                    "qty": "1",
                    "splits": "1",
                    "fetched_time_ms": 1776255470200,
                    "symbol": "NABIL",
                }
            ]
        )
    )
    (date_dir / "completed.json").write_text(
        json.dumps(
            [
                {
                    "price": "100",
                    "qty": "10",
                    "start_time_ms": 1776255470400,
                    "end_time_ms": 1776255470450,
                    "symbol": "NABIL",
                    "user_id": "test",
                }
            ]
        )
    )

    service = OrderLogsService(logs_dir=logs_dir)
    payload = service.load("2026-04-15")

    rows = payload.rows_by_symbol["NABIL"]
    assert len(rows) == 2
    assert rows[0].bid_price == "100"
    assert rows[0].order_price == "-"
    assert rows[0].highlight is True
    assert rows[1].bid_price == "-"
    assert rows[1].order_price == "100"
    assert rows[1].highlight is False


def test_order_logs_screen_symbol_toggle_and_date_change():
    class FakeService:
        def load(self, _date: str) -> OrderLogsPayload:
            return OrderLogsPayload(
                symbols=["ADBL", "NABIL"],
                rows_by_symbol={"ADBL": [], "NABIL": []},
                market_counts={"ADBL": 0, "NABIL": 0},
                completed_counts={"ADBL": 1, "NABIL": 2},
            )

    screen = OrderLogsScreen(service=FakeService())
    render_calls: list[str] = []
    reload_calls: list[str] = []

    screen.payload = screen.service.load("2026-04-15")
    screen._render_table = lambda: render_calls.append("render")  # type: ignore[method-assign]
    screen._reload = lambda: reload_calls.append("reload")  # type: ignore[method-assign]

    assert any(binding[0] == "r" and binding[1] == "refresh" for binding in screen.BINDINGS)
    assert any(binding[0] == "t" and binding[1] == "toggle_symbol" for binding in screen.BINDINGS)
    assert any(binding[0] == "k" and binding[1] == "change_date" for binding in screen.BINDINGS)

    assert screen.symbol_index == 0
    screen.action_toggle_symbol()
    assert screen.symbol_index == 1
    assert render_calls == ["render"]

    screen._on_date_selected("2026-04-14")
    assert screen.date == "2026-04-14"
    assert screen.symbol_index == 0
    assert reload_calls == ["reload"]
