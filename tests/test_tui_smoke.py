import asyncio
import time
from pathlib import Path

import pytest


textual = pytest.importorskip("textual")

from textual.widgets import Checkbox, Input, TabbedContent

from tui.app import TMSAutomationTUI
from tui.screens.main_menu import MainMenuScreen
from tui.screens.orders import ORDER_TEMPLATE, OrderEditorScreen
from tui.screens.portfolio import OrderBookScreen
from tui.screens.orders import OrdersScreen


def test_tui_main_screen_mounts():
    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    asyncio.run(run())


def test_order_editor_uses_main_buy_sell_tabs():
    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()

            screen = OrderEditorScreen("Add Order", ORDER_TEMPLATE)
            app.push_screen(screen)
            await pilot.pause()

            tabs = screen.query_one(TabbedContent)
            assert tabs.active == "tab-main"
            assert screen.query_one("#tab-main") is not None
            assert screen.query_one("#tab-buy") is not None
            assert screen.query_one("#tab-sell") is not None

            assert screen.query_one("#order-execute", Checkbox) is not None
            assert screen.query_one("#order-success", Checkbox) is not None
            assert screen.query_one("#order-sell", Checkbox) is not None
            assert screen.query_one("#order-user_id", Input) is not None

            assert screen.query_one("#order-just_buy", Checkbox).disabled is True
            assert screen.query_one("#order-multi_queue", Checkbox).disabled is True

    asyncio.run(run())


def test_order_editor_submits_user_id_field():
    class TestScreen(OrderEditorScreen):
        def __init__(self) -> None:
            super().__init__("Edit Order", {**ORDER_TEMPLATE, "user_id": "pool-main"})
            self.result = None

        def dismiss(self, result=None):
            self.result = result

    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()

            screen = TestScreen()
            app.push_screen(screen)
            await pilot.pause()

            screen.query_one("#order-user_id", Input).value = "pool-main"
            screen.action_submit()

            assert screen.result is not None
            payload = screen.result[1]
            assert payload["user_id"] == "pool-main"

    asyncio.run(run())


def test_order_book_auto_refresh_only_targets_active_panel():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    class FakeTimer:
        def __init__(self) -> None:
            self.resume_calls = 0
            self.pause_calls = 0
            self.reset_calls = 0

        def resume(self) -> None:
            self.resume_calls += 1

        def pause(self) -> None:
            self.pause_calls += 1

        def reset(self) -> None:
            self.reset_calls += 1

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())
    timer = FakeTimer()
    messages: list[tuple[str, str]] = []
    refresh_requests: list[str] = []

    screen._auto_refresh_timer = timer
    screen._active_panel = lambda: "tab-completed"  # type: ignore[method-assign]
    screen._update_refresh_button = lambda: None  # type: ignore[method-assign]
    screen._set_status = lambda message, panel="active": messages.append((message, panel))  # type: ignore[method-assign]
    screen._trigger_refresh = lambda *, source: refresh_requests.append(f"{source}:{screen._active_panel()}")  # type: ignore[method-assign]
    original_localtime = time.localtime
    time.localtime = lambda: type("FakeNow", (), {"tm_hour": 12})()

    try:
        assert screen._auto_refresh_enabled is False
        assert any(binding[0] == "l" for binding in screen.BINDINGS)

        screen._handle_auto_refresh_tick()
        assert refresh_requests == []

        screen.action_toggle_auto_refresh()
        assert screen._auto_refresh_enabled is True
        assert timer.reset_calls == 1
        assert timer.resume_calls == 1
        assert messages[-1] == ("Auto-refresh enabled for active panel every 30s", "completed")

        screen._handle_auto_refresh_tick()
        assert refresh_requests == ["auto:tab-completed"]

        screen.action_toggle_auto_refresh()
        assert screen._auto_refresh_enabled is False
        assert timer.pause_calls == 1
        assert messages[-1] == ("Auto-refresh disabled for active panel every 30s", "completed")
    finally:
        time.localtime = original_localtime


def test_order_book_top_tab_defaults_and_toggle_behavior():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())
    refresh_calls: list[str] = []
    statuses: list[tuple[str, str]] = []

    screen._active_panel = lambda: "tab-top"  # type: ignore[method-assign]
    screen.action_refresh_book = lambda: refresh_calls.append("refresh")  # type: ignore[method-assign]
    screen._set_status = lambda message, panel="active": statuses.append((message, panel))  # type: ignore[method-assign]

    assert screen._top_gainers_mode is True
    assert any(binding[0] == "ctrl+4" and binding[1] == "show_top_panel" for binding in screen.BINDINGS)
    assert any(binding[0] == "ctrl+5" and binding[1] == "show_market_panel" for binding in screen.BINDINGS)
    assert screen._top_sort_mode == "chng_pct"

    screen.action_toggle_top_or_cycle_watchlist()
    assert screen._top_gainers_mode is False
    assert refresh_calls == ["refresh"]
    assert statuses[-1] == ("Top 10 mode: Losers", "top")


def test_order_book_t_binding_is_noop_outside_watchlists_and_top():
    class FakePortfolioService:
        def get_user_label(self, _path: Path) -> str:
            return "demo"

        def load_tickers(self) -> list[dict]:
            return []

    screen = OrderBookScreen(Path("users/default.json"), service=FakePortfolioService())
    calls: list[str] = []

    screen._active_panel = lambda: "tab-active"  # type: ignore[method-assign]
    screen.action_cycle_watchlist = lambda: calls.append("cycle")  # type: ignore[method-assign]
    screen.action_refresh_book = lambda: calls.append("refresh")  # type: ignore[method-assign]

    screen.action_toggle_top_or_cycle_watchlist()
    assert calls == []


def test_orders_screen_can_reload_store_from_disk():
    class FakeOrderStoreService:
        def __init__(self) -> None:
            self.refresh_calls = 0

        def list_rows(self):
            return []

        def refresh_store(self) -> None:
            self.refresh_calls += 1

    class FakePriceRefreshService:
        pass

    service = FakeOrderStoreService()
    screen = OrdersScreen(service=service, price_refresh_service=FakePriceRefreshService())
    reload_calls: list[str] = []
    statuses: list[str] = []

    screen.reload_table = lambda: reload_calls.append("reload")  # type: ignore[method-assign]
    screen._set_status = lambda message: statuses.append(message)  # type: ignore[method-assign]

    assert any(binding[0] == "u" and binding[1] == "refresh_store" for binding in screen.BINDINGS)

    screen.action_refresh_store()

    assert service.refresh_calls == 1
    assert reload_calls == ["reload"]
    assert statuses == ["Reloaded order store from disk."]
