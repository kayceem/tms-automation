import asyncio

import pytest


textual = pytest.importorskip("textual")

from textual.widgets import Checkbox, TabbedContent

from tui.app import TMSAutomationTUI
from tui.screens.main_menu import MainMenuScreen
from tui.screens.orders import ORDER_TEMPLATE, OrderEditorScreen


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
