import asyncio
import time
from pathlib import Path

import pytest


textual = pytest.importorskip("textual")

from textual.widgets import Checkbox, TabbedContent

from tui.app import TMSAutomationTUI
from tui.screens.main_menu import MainMenuScreen
from tui.screens.orders import ORDER_TEMPLATE, OrderEditorScreen
from tui.screens.portfolio import OrderBookScreen


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

            assert screen.query_one("#order-just_buy", Checkbox).disabled is True
            assert screen.query_one("#order-multi_queue", Checkbox).disabled is True

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
