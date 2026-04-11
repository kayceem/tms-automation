import asyncio

import pytest


textual = pytest.importorskip("textual")

from tui.app import TMSAutomationTUI
from tui.screens.main_menu import MainMenuScreen


def test_tui_main_screen_mounts():
    async def run() -> None:
        app = TMSAutomationTUI()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, MainMenuScreen)

    asyncio.run(run())
